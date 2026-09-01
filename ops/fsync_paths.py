#!/usr/bin/env python3
"""Fsync deployment trees and their directory-entry ancestry."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path


HOST_ROOT = Path("/home/ubuntu/telescan")
ACTIVE_DIR = HOST_ROOT / "Telescan-bot-app"
RELEASES_DIR = HOST_ROOT / ".releases" / "Telescan-bot-app"
SNAPSHOTS_DIR = HOST_ROOT / ".rollback" / "Telescan-bot-app"
INTENT_ROOT = HOST_ROOT / ".transactions" / "Telescan-bot-app"


class FsyncError(RuntimeError):
    pass


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def fsync_directory(path: Path) -> None:
    directory_fd = _open_directory(path)
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise FsyncError(f"not a directory: {path}")
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def fsync_tree(root: Path, *, exclude_env: bool = False) -> None:
    root_stat = root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise FsyncError(f"tree root is not a real directory: {root}")

    directories: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directories.append(directory_path)
        for name in tuple(dirnames):
            child = directory_path / name
            child_stat = child.lstat()
            if stat.S_ISLNK(child_stat.st_mode):
                raise FsyncError(f"symlink is forbidden in deployment tree: {child}")
            if not stat.S_ISDIR(child_stat.st_mode):
                raise FsyncError(f"unexpected tree entry: {child}")
        for name in filenames:
            if exclude_env and name == ".env":
                continue
            child = directory_path / name
            child_stat = child.lstat()
            if not stat.S_ISREG(child_stat.st_mode) or stat.S_ISLNK(child_stat.st_mode):
                raise FsyncError(f"non-regular deployment file: {child}")
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            file_fd = os.open(child, flags)
            try:
                if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                    raise FsyncError(f"non-regular deployment file: {child}")
                os.fsync(file_fd)
            finally:
                os.close(file_fd)
    for directory in reversed(directories):
        fsync_directory(directory)


def fsync_parents(path: Path, *, stop: Path = HOST_ROOT) -> None:
    current = path
    while True:
        fsync_directory(current)
        if current == stop:
            return
        if current == current.parent or stop not in current.parents:
            raise FsyncError(f"path is outside the protected host root: {path}")
        current = current.parent


def _normalized(path: Path) -> Path:
    if not path.is_absolute() or Path(os.path.normpath(path)) != path:
        raise FsyncError("path must be normalized and absolute")
    return path


def _is_child(path: Path, parent: Path) -> bool:
    return parent in path.parents


def _validate_tree_path(path: Path) -> None:
    allowed = (
        path == ACTIVE_DIR
        or _is_child(path, RELEASES_DIR)
        or _is_child(path, SNAPSHOTS_DIR)
    )
    if not allowed:
        raise FsyncError("tree path is outside deployment storage")


def _validate_parent_path(path: Path) -> None:
    allowed = path in {RELEASES_DIR, SNAPSHOTS_DIR, INTENT_ROOT}
    if not allowed:
        raise FsyncError("parent path is outside deployment storage")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    tree = commands.add_parser("tree")
    tree.add_argument("path", type=Path)
    tree.add_argument("--exclude-env", action="store_true")
    parents = commands.add_parser("parents")
    parents.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    try:
        path = _normalized(args.path)
        if args.command == "tree":
            _validate_tree_path(path)
            fsync_tree(path, exclude_env=args.exclude_env)
        else:
            _validate_parent_path(path)
            fsync_parents(path)
    except (FsyncError, OSError) as exc:
        print(f"deployment fsync error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
