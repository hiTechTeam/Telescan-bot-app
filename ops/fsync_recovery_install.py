#!/usr/bin/env python3
"""Durability gate for the installed deployment-recovery watcher."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


HOST_ROOT = Path("/home/ubuntu/telescan")
CONTROLLER_DIR = HOST_ROOT / ".deploy-controller" / "Telescan-bot-app"
CONTROLLER_FILE = CONTROLLER_DIR / "recover-deployment.sh"
SYSTEMD_DIR = Path("/etc/systemd/system")
SERVICE_FILE = SYSTEMD_DIR / "telescan-bot-deploy-recovery.service"
TIMER_FILE = SYSTEMD_DIR / "telescan-bot-deploy-recovery.timer"
WANTS_DIR = SYSTEMD_DIR / "timers.target.wants"
WANTS_LINK = WANTS_DIR / TIMER_FILE.name


class RecoveryInstallError(RuntimeError):
    pass


def fsync_regular_file(path: Path) -> None:
    path_stat = path.lstat()
    if not stat.S_ISREG(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode):
        raise RecoveryInstallError(f"expected a real regular file: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    file_fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise RecoveryInstallError(f"file changed during fsync: {path}")
        os.fsync(file_fd)
    finally:
        os.close(file_fd)


def fsync_directory(path: Path) -> None:
    path_stat = path.lstat()
    if not stat.S_ISDIR(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode):
        raise RecoveryInstallError(f"expected a real directory: {path}")
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    directory_fd = os.open(path, flags)
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise RecoveryInstallError(f"directory changed during fsync: {path}")
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def fsync_directory_chain(path: Path, stop: Path) -> None:
    current = path
    while True:
        fsync_directory(current)
        if current == stop:
            return
        if current == current.parent or stop not in current.parents:
            raise RecoveryInstallError(f"directory is outside durability root: {path}")
        current = current.parent


def verify_timer_link(link: Path, timer_file: Path) -> None:
    link_stat = link.lstat()
    if not stat.S_ISLNK(link_stat.st_mode):
        raise RecoveryInstallError(f"expected the enabled timer symlink: {link}")
    try:
        resolved = link.resolve(strict=True)
        expected = timer_file.resolve(strict=True)
    except OSError as exc:
        raise RecoveryInstallError("enabled timer symlink is broken") from exc
    if resolved != expected:
        raise RecoveryInstallError("enabled timer symlink targets another unit")


def durability_gate(
    *,
    controller_file: Path,
    controller_stop: Path,
    service_file: Path,
    timer_file: Path,
    wants_link: Path,
) -> None:
    verify_timer_link(wants_link, timer_file)
    for path in (controller_file, service_file, timer_file):
        fsync_regular_file(path)

    # Persist the launcher and every newly-created controller directory entry.
    fsync_directory_chain(controller_file.parent, controller_stop)
    # Persist the enable symlink, the wants directory entry, and both unit files.
    fsync_directory(wants_link.parent)
    fsync_directory(service_file.parent)


def main() -> int:
    try:
        durability_gate(
            controller_file=CONTROLLER_FILE,
            controller_stop=HOST_ROOT,
            service_file=SERVICE_FILE,
            timer_file=TIMER_FILE,
            wants_link=WANTS_LINK,
        )
    except (RecoveryInstallError, OSError) as exc:
        print(f"recovery install fsync error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
