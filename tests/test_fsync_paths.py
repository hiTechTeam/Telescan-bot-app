from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "user_bot_fsync_paths", ROOT / "ops" / "fsync_paths.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fsync_tree_covers_nested_regular_files_and_directories(
    tmp_path: Path,
) -> None:
    module = load_module()
    tree = tmp_path / "tree"
    nested = tree / "nested"
    nested.mkdir(parents=True)
    (tree / "root.txt").write_text("root", encoding="utf-8")
    (nested / "leaf.txt").write_text("leaf", encoding="utf-8")

    module.fsync_tree(tree)


def test_fsync_tree_rejects_symlinks(tmp_path: Path) -> None:
    module = load_module()
    tree = tmp_path / "tree"
    tree.mkdir()
    target = tmp_path / "target"
    target.write_text("value", encoding="utf-8")
    (tree / "link").symlink_to(target)

    with pytest.raises((module.FsyncError, OSError)):
        module.fsync_tree(tree)
