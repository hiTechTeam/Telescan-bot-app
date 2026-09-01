from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "user_bot_deploy_intent", ROOT / "ops" / "deploy_intent.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_state(module: ModuleType) -> dict[str, object]:
    deploy_id = "abcdef0123456789-123-1"
    return {
        "version": module.STATE_VERSION,
        "controller_version": module.CONTROLLER_VERSION,
        "service": module.SERVICE,
        "deploy_id": deploy_id,
        "phase": "prepared",
        "active_dir": module.ACTIVE_DIR,
        "release_dir": f"{module.RELEASES_DIR}/{deploy_id}",
        "snapshot_dir": f"{module.SNAPSHOTS_DIR}/{deploy_id}",
        "previous_image_id": "sha256:0123456789abcdef",
        "previous_image_ref": "telescan-bot-app-telescan-bot-app:latest",
        "rollback_image_ref": f"telescan-bot-app:rollback-{deploy_id}",
        "candidate_image_ref": f"telescan-bot-app:candidate-{deploy_id}",
    }


def test_prepared_intent_survives_restart_then_commits_and_clears(
    tmp_path: Path,
) -> None:
    module = load_module()
    root = tmp_path / "intent"
    first = module.IntentStore(root)
    first.publish(valid_state(module))

    assert stat.S_IMODE((root / "active.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(root.stat().st_mode) == 0o700

    restarted = module.IntentStore(root)
    assert restarted.read()["phase"] == "prepared"
    restarted.set_phase("prepared", "committed")
    assert restarted.read()["phase"] == "committed"
    restarted.clear("committed")
    assert not restarted.exists()


def test_power_loss_after_atomic_rename_leaves_recoverable_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    store = module.IntentStore(tmp_path / "intent")
    state = valid_state(module)
    real_fsync = module.os.fsync
    calls = 0

    def fail_directory_fsync(file_descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated power loss after rename")
        real_fsync(file_descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="simulated power loss"):
        store.publish(state)
    monkeypatch.setattr(module.os, "fsync", real_fsync)

    # Either name after a real power loss is safe. If the new name survived,
    # it is complete and a fresh recovery process can consume it.
    assert module.IntentStore(tmp_path / "intent").read() == state


def test_phase_compare_and_swap_fails_closed(tmp_path: Path) -> None:
    module = load_module()
    store = module.IntentStore(tmp_path / "intent")
    store.publish(valid_state(module))

    with pytest.raises(module.IntentError, match="changed concurrently"):
        store.set_phase("committed", "prepared")
    with pytest.raises(module.IntentError, match="changed concurrently"):
        store.clear("committed")

    assert store.read()["phase"] == "prepared"


def test_publish_never_overwrites_an_active_recovery(tmp_path: Path) -> None:
    module = load_module()
    store = module.IntentStore(tmp_path / "intent")
    state = valid_state(module)
    store.publish(state)

    with pytest.raises(module.IntentError, match="already active"):
        store.publish(state)

    assert store.read() == state


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release_dir", "/tmp/attacker-release"),
        ("snapshot_dir", "/home/ubuntu/telescan/.rollback/elsewhere/x"),
        ("phase", "rolling-back"),
        ("service", "another-service"),
        ("controller_version", 999),
    ],
)
def test_invalid_or_foreign_intents_are_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    module = load_module()
    state = valid_state(module)
    state[field] = value

    with pytest.raises(module.IntentError):
        module.IntentStore(tmp_path / "intent").publish(state)


def test_corrupt_intent_is_retained_for_operator_recovery(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / "intent"
    root.mkdir()
    path = root / "active.json"
    path.write_text(json.dumps({"phase": "prepared"}), encoding="utf-8")

    store = module.IntentStore(root)
    with pytest.raises(module.IntentError):
        store.read()
    assert path.exists()


def test_symlink_intent_is_rejected(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / "intent"
    root.mkdir()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    (root / "active.json").symlink_to(target)

    with pytest.raises(module.IntentError, match="regular file"):
        module.IntentStore(root).exists()
