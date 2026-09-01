#!/usr/bin/env python3
"""Durable compare-and-swap state for the production deployment controller."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from typing import Any


STATE_VERSION = 1
CONTROLLER_VERSION = 1
SERVICE = "telescan-bot-app"
ACTIVE_DIR = "/home/ubuntu/telescan/Telescan-bot-app"
RELEASES_DIR = "/home/ubuntu/telescan/.releases/Telescan-bot-app"
SNAPSHOTS_DIR = "/home/ubuntu/telescan/.rollback/Telescan-bot-app"
DEFAULT_ROOT = Path("/home/ubuntu/telescan/.transactions/Telescan-bot-app")
PHASES = frozenset({"prepared", "committed"})
DEPLOY_ID_RE = re.compile(r"^[a-f0-9]{7,64}-[0-9]{1,20}-[0-9]{1,10}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,254}$")
FIELDS = frozenset(
    {
        "version",
        "controller_version",
        "service",
        "deploy_id",
        "phase",
        "active_dir",
        "release_dir",
        "snapshot_dir",
        "previous_image_id",
        "previous_image_ref",
        "rollback_image_ref",
        "candidate_image_ref",
    }
)


class IntentError(RuntimeError):
    """The durable intent is absent, corrupt, unsafe, or changed concurrently."""


def _validate_child_path(value: Any, parent: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise IntentError(f"{field} must be a non-empty string")
    if not value.startswith("/") or os.path.normpath(value) != value:
        raise IntentError(f"{field} must be a normalized absolute path")
    if not value.startswith(f"{parent}/"):
        raise IntentError(f"{field} is outside its protected directory")
    return value


def validate(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict) or set(state) != FIELDS:
        raise IntentError("intent fields do not match controller version 1")
    if state["version"] != STATE_VERSION:
        raise IntentError("unsupported intent state version")
    if state["controller_version"] != CONTROLLER_VERSION:
        raise IntentError("unsupported deployment controller version")
    if state["service"] != SERVICE:
        raise IntentError("intent belongs to another service")
    deploy_id = state["deploy_id"]
    if not isinstance(deploy_id, str) or DEPLOY_ID_RE.fullmatch(deploy_id) is None:
        raise IntentError("invalid deployment id")
    if state["phase"] not in PHASES:
        raise IntentError("invalid deployment phase")
    if state["active_dir"] != ACTIVE_DIR:
        raise IntentError("invalid active directory")
    release_dir = _validate_child_path(
        state["release_dir"], RELEASES_DIR, "release_dir"
    )
    snapshot_dir = _validate_child_path(
        state["snapshot_dir"], SNAPSHOTS_DIR, "snapshot_dir"
    )
    if Path(release_dir).name != deploy_id or Path(snapshot_dir).name != deploy_id:
        raise IntentError("deployment directories do not match the deployment id")
    for field in (
        "previous_image_id",
        "previous_image_ref",
        "rollback_image_ref",
        "candidate_image_ref",
    ):
        value = state[field]
        if not isinstance(value, str) or IMAGE_RE.fullmatch(value) is None:
            raise IntentError(f"invalid {field}")
    return state


class IntentStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "active.json"

    def _ensure_root(self) -> None:
        try:
            root_stat = self.root.lstat()
        except FileNotFoundError:
            self.root.mkdir(mode=0o700, parents=True)
        else:
            if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
                raise IntentError("intent root must be a real directory")
        os.chmod(self.root, 0o700)

    def _fsync_root(self) -> None:
        directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _atomic_write(self, state: dict[str, Any]) -> None:
        self._ensure_root()
        payload = (
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        temp_path = self.root / f".active.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        file_fd = os.open(temp_path, flags, 0o600)
        try:
            with os.fdopen(file_fd, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
            self._fsync_root()
        finally:
            os.close(file_fd)
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def exists(self) -> bool:
        try:
            path_stat = self.path.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode):
            raise IntentError("active intent must be a regular file")
        return True

    def read(self) -> dict[str, Any]:
        self._ensure_root()
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            file_fd = os.open(self.path, flags)
        except FileNotFoundError as exc:
            raise IntentError("no active deployment intent") from exc
        try:
            path_stat = os.fstat(file_fd)
            if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_size > 65_536:
                raise IntentError("active intent is not a small regular file")
            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                raw = stream.read(65_537)
        finally:
            os.close(file_fd)
        if len(raw) > 65_536:
            raise IntentError("active intent is too large")
        try:
            return validate(json.loads(raw))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise IntentError("active intent is not valid JSON") from exc

    def publish(self, state: dict[str, Any]) -> None:
        validate(state)
        self._ensure_root()
        if self.exists():
            raise IntentError("another deployment intent is already active")
        self._atomic_write(state)

    def set_phase(self, expected: str, new: str) -> None:
        if expected not in PHASES or new not in PHASES or expected == new:
            raise IntentError("invalid phase transition")
        state = self.read()
        if state["phase"] != expected:
            raise IntentError("deployment phase changed concurrently")
        state["phase"] = new
        self._atomic_write(state)

    def clear(self, expected: str) -> None:
        state = self.read()
        if expected not in PHASES or state["phase"] != expected:
            raise IntentError("deployment phase changed concurrently")
        self.path.unlink()
        self._fsync_root()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)

    publish = commands.add_parser("publish")
    publish.add_argument("--deploy-id", required=True)
    publish.add_argument("--release-dir", required=True)
    publish.add_argument("--snapshot-dir", required=True)
    publish.add_argument("--previous-image-id", required=True)
    publish.add_argument("--previous-image-ref", required=True)
    publish.add_argument("--rollback-image-ref", required=True)
    publish.add_argument("--candidate-image-ref", required=True)

    get = commands.add_parser("get")
    get.add_argument("field", choices=sorted(FIELDS))

    phase = commands.add_parser("phase")
    phase.add_argument("--expected", required=True, choices=sorted(PHASES))
    phase.add_argument("--new", required=True, choices=sorted(PHASES))

    clear = commands.add_parser("clear")
    clear.add_argument("--expected", required=True, choices=sorted(PHASES))

    commands.add_parser("exists")
    commands.add_parser("validate")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = IntentStore(args.root)
    try:
        if args.command == "publish":
            store.publish(
                {
                    "version": STATE_VERSION,
                    "controller_version": CONTROLLER_VERSION,
                    "service": SERVICE,
                    "deploy_id": args.deploy_id,
                    "phase": "prepared",
                    "active_dir": ACTIVE_DIR,
                    "release_dir": args.release_dir,
                    "snapshot_dir": args.snapshot_dir,
                    "previous_image_id": args.previous_image_id,
                    "previous_image_ref": args.previous_image_ref,
                    "rollback_image_ref": args.rollback_image_ref,
                    "candidate_image_ref": args.candidate_image_ref,
                }
            )
        elif args.command == "get":
            print(store.read()[args.field])
        elif args.command == "phase":
            store.set_phase(args.expected, args.new)
        elif args.command == "clear":
            store.clear(args.expected)
        elif args.command == "exists":
            return 0 if store.exists() else 1
        elif args.command == "validate":
            store.read()
        else:  # pragma: no cover - argparse enforces the command set
            raise IntentError("unknown command")
    except IntentError as exc:
        print(f"deploy intent error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
