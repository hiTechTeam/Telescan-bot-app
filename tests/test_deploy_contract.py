from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_in_order(content: str, *tokens: str) -> None:
    position = -1
    for token in tokens:
        next_position = content.find(token, position + 1)
        assert next_position >= 0, token
        assert next_position > position
        position = next_position


def test_workflow_keeps_production_main_only_and_uploads_immutable_release() -> None:
    workflow = text(".github/workflows/deploy.yml")

    assert "github.ref == 'refs/heads/main'" in workflow
    assert "group: production-telescan-bot" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "test ! -e '$TARGET_DIR'" in workflow
    assert "mktemp -d '$RELEASES_DIR/.upload-$RELEASE_ID.XXXXXX'" in workflow
    assert "sudo chown -R root:root '$UPLOAD_DIR'" in workflow
    assert "mv '$UPLOAD_DIR' '$TARGET_DIR'" in workflow
    assert "--exclude '.env'" in workflow
    assert_in_order(
        workflow,
        "fsync_paths.py' tree '$UPLOAD_DIR'",
        "mv '$UPLOAD_DIR' '$TARGET_DIR'",
        "fsync_paths.py' parents '$RELEASES_DIR'",
    )


def test_systemd_supervises_deploy_and_boot_recovery_watcher() -> None:
    workflow = text(".github/workflows/deploy.yml")
    timer = text("ops/telescan-bot-deploy-recovery.timer")
    service = text("ops/telescan-bot-deploy-recovery.service")

    assert "sudo systemd-run --wait --collect" in workflow
    assert "--uid=ubuntu" in workflow
    assert "--gid=ubuntu" in workflow
    assert '--property="OnFailure=$RECOVERY_SERVICE"' in workflow
    assert 'systemctl enable --now "$RECOVERY_TIMER"' in workflow
    assert 'systemctl is-enabled --quiet "$RECOVERY_TIMER"' in workflow
    assert "OnBootSec=15s" in timer
    assert "OnUnitInactiveSec=60s" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    assert "ConditionPathExists=" in service
    assert "User=ubuntu" in service
    assert "Group=ubuntu" in service
    assert "TimeoutStartSec=35min" in service
    assert_in_order(
        workflow,
        'systemctl enable --now "$RECOVERY_TIMER"',
        '"$RELEASE_DIR/ops/fsync_recovery_install.py"',
        'systemctl is-enabled --quiet "$RECOVERY_TIMER"',
        'systemctl is-active --quiet "$RECOVERY_TIMER"',
        "sudo systemd-run --wait --collect",
    )


def test_controller_has_one_durable_precommit_boundary_and_shared_lock() -> None:
    controller = text("ops/deploy-production.sh")

    assert 'readonly LOCK_FILE="/tmp/telescan-production-deploy.lock"' in controller
    assert 'exec 9>"$LOCK_FILE"' in controller
    assert "flock -w 1800 9" in controller
    assert "rsync -a --delete --exclude='.env'" in controller
    assert "rollback-$deploy_id" in controller
    assert "candidate-$deploy_id" in controller
    assert "docker compose ps --all --quiet" in controller
    assert "docker ps --all --quiet" in controller
    assert "docker ps --all --no-trunc --quiet" in controller
    assert "\"$all_ids\" == *$'\\n'*" in controller
    assert '"$container_id" != "$global_ids"' in controller
    assert_in_order(
        controller,
        'rsync -a --delete --exclude=\'.env\' "$ACTIVE_DIR/" "$snapshot_dir/"',
        '"$FSYNC_TOOL" tree "$snapshot_dir"',
        '"$FSYNC_TOOL" parents "$SNAPSHOTS_DIR"',
        'docker tag "$previous_image_id" "$rollback_image_ref"',
        '"$FSYNC_TOOL" parents "$INTENT_ROOT"',
        "intent publish",
        'rsync -a --delete --exclude=\'.env\' "$release_dir/" "$ACTIVE_DIR/"',
        "wait_for_one_healthy",
        "intent phase --expected prepared --new committed",
        "intent clear --expected committed",
    )


def test_precommit_failure_restores_config_and_protected_image() -> None:
    controller = text("ops/deploy-production.sh")

    assert "handle_deploy_exit" in controller
    assert "recover_active_intent" in controller
    assert "restore_prepared_intent" in controller
    assert (
        'rsync -a --delete --exclude=\'.env\' "$snapshot_dir/" "$ACTIVE_DIR/"'
        in controller
    )
    assert 'docker tag "$rollback_image_ref" "$previous_image_ref"' in controller
    assert "intent clear --expected prepared" in controller
    assert (
        "CRITICAL: durable deployment recovery requires operator action" in controller
    )
    assert "cat .env" not in controller
    assert "source .env" not in controller


def test_recovery_dispatches_the_controller_recorded_by_the_intent() -> None:
    launcher = text("ops/recover-deployment.sh")

    assert "exec 9>/tmp/telescan-production-deploy.lock" in launcher
    assert "flock -w 1800 9" in launcher
    assert 'value["release_dir"]' in launcher
    assert '"$RELEASES_DIR"/*' in launcher
    assert 'exec "$release_dir/ops/deploy-production.sh" recover-locked' in launcher
