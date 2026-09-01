from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "user_bot_recovery_install_fsync",
        ROOT / "ops" / "fsync_recovery_install.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recovery_files(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    host = tmp_path / "host"
    controller = host / ".deploy-controller" / "bot" / "recover.sh"
    systemd = tmp_path / "etc" / "systemd" / "system"
    service = systemd / "recovery.service"
    timer = systemd / "recovery.timer"
    wants = systemd / "timers.target.wants"
    controller.parent.mkdir(parents=True)
    wants.mkdir(parents=True)
    for path in (controller, service, timer):
        path.write_text("fixture\n", encoding="utf-8")
    link = wants / timer.name
    link.symlink_to(Path("..") / timer.name)
    return host, controller, service, timer, link


def test_recovery_install_gate_fsyncs_launcher_units_and_enable_link(
    tmp_path: Path,
) -> None:
    module = load_module()
    host, controller, service, timer, link = recovery_files(tmp_path)

    module.durability_gate(
        controller_file=controller,
        controller_stop=host,
        service_file=service,
        timer_file=timer,
        wants_link=link,
    )


def test_power_cut_during_watcher_fsync_blocks_transaction_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    host, controller, service, timer, link = recovery_files(tmp_path)
    real_fsync = module.os.fsync
    calls = 0
    transaction_started = False

    def fail_before_wants_directory_is_durable(file_descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 7:
            raise OSError("simulated power cut before recovery watcher durability")
        real_fsync(file_descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_before_wants_directory_is_durable)
    with pytest.raises(OSError, match="simulated power cut"):
        module.durability_gate(
            controller_file=controller,
            controller_stop=host,
            service_file=service,
            timer_file=timer,
            wants_link=link,
        )
        transaction_started = True

    assert calls == 7
    assert transaction_started is False


def test_recovery_install_gate_rejects_foreign_timer_link(tmp_path: Path) -> None:
    module = load_module()
    host, controller, service, timer, link = recovery_files(tmp_path)
    foreign = timer.parent / "foreign.timer"
    foreign.write_text("fixture\n", encoding="utf-8")
    link.unlink()
    link.symlink_to(Path("..") / foreign.name)

    with pytest.raises(module.RecoveryInstallError, match="another unit"):
        module.durability_gate(
            controller_file=controller,
            controller_stop=host,
            service_file=service,
            timer_file=timer,
            wants_link=link,
        )
