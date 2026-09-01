from __future__ import annotations

import os
import signal
import stat
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = "telescan-bot-app"
ACTIVE_NAME = "Telescan-bot-app"


def executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def wait_for(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"controller exited before the crash point: {stdout}\n{stderr}"
            )
        time.sleep(0.02)
    raise AssertionError("controller did not reach the crash point")


def test_sigkill_after_prepare_is_recovered_from_snapshot_and_image(
    tmp_path: Path,
) -> None:
    host = tmp_path / "host"
    active = host / ACTIVE_NAME
    deploy_id = "abcdef0123456789-123-1"
    release = host / ".releases" / ACTIVE_NAME / deploy_id
    ops = release / "ops"
    shims = tmp_path / "bin"
    docker_state = tmp_path / "docker-state"
    signals = tmp_path / "signals"
    for directory in (active, ops, shims, docker_state, signals):
        directory.mkdir(parents=True, exist_ok=True)

    (active / ".env").write_text("not-read-by-the-controller\n", encoding="utf-8")
    (active / "old.marker").write_text("old\n", encoding="utf-8")
    (active / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (release / "new.marker").write_text("new\n", encoding="utf-8")
    for name in ("deploy-production.sh", "recover-deployment.sh"):
        executable(ops / name, "#!/bin/sh\nexit 0\n")
    for name in ("deploy_intent.py", "fsync_paths.py"):
        (ops / name).write_text("# fixture\n", encoding="utf-8")
    for path in sorted(release.rglob("*"), reverse=True):
        path.chmod(
            0o555 if path.is_dir() else (0o555 if os.access(path, os.X_OK) else 0o444)
        )
    release.chmod(0o555)

    for name, value in {
        "exists": "1",
        "running": "1",
        "health": "healthy",
        "image_id": "sha256:oldimage",
        "image_ref": f"{SERVICE}-{SERVICE}:latest",
    }.items():
        (docker_state / name).write_text(value, encoding="utf-8")

    executable(
        shims / "python",
        r"""#!/bin/bash
set -eu
script="$1"
shift
case "$script" in
  */fsync_paths.py) exit 0 ;;
esac
test "$1" = "--root"
root="$2"
shift 2
command="$1"
shift
mkdir -p "$root/fields"
case "$command" in
  exists)
    test -f "$root/active.json"
    ;;
  validate)
    test -f "$root/active.json"
    ;;
  get)
    cat "$root/fields/$1"
    ;;
  publish)
    while [ "$#" -gt 0 ]; do
      key="${1#--}"
      value="$2"
      printf '%s\n' "$value" >"$root/fields/${key//-/_}"
      shift 2
    done
    printf '%s\n' prepared >"$root/fields/phase"
    printf '%s\n' "$MOCK_ACTIVE_DIR" >"$root/fields/active_dir"
    : >"$root/active.json"
    : >"$MOCK_SIGNALS/prepared"
    ;;
  phase)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "--new" ]; then
        printf '%s\n' "$2" >"$root/fields/phase"
      fi
      shift 2
    done
    ;;
  clear)
    rm -f "$root/active.json"
    ;;
  *) exit 2 ;;
esac
""",
    )
    executable(
        shims / "docker",
        r"""#!/bin/bash
set -eu
state="$MOCK_DOCKER_STATE"
command="$1"
shift
case "$command" in
  compose)
    subcommand="$1"
    shift
    case "$subcommand" in
      config) exit 0 ;;
      ps)
        all=false
        for argument in "$@"; do
          [ "$argument" != "--all" ] || all=true
        done
        if [ "$(cat "$state/exists")" = 1 ]; then
          if $all || [ "$(cat "$state/running")" = 1 ]; then
            printf '%s\n' fixture-container
          fi
        fi
        ;;
      stop)
        printf '%s' 0 >"$state/running"
        ;;
      up)
        printf '%s' 1 >"$state/exists"
        printf '%s' 1 >"$state/running"
        printf '%s' healthy >"$state/health"
        ;;
      *) exit 2 ;;
    esac
    ;;
  ps)
    [ "$(cat "$state/exists")" != 1 ] || printf '%s\n' fixture-container
    ;;
  inspect)
    format="$2"
    case "$format" in
      *Health.Status*) cat "$state/health" ;;
      *Config.Image*) cat "$state/image_ref" ;;
      *Image*) cat "$state/image_id" ;;
      *) exit 2 ;;
    esac
    ;;
  build|tag) exit 0 ;;
  image) exit 0 ;;
  stop)
    printf '%s' 0 >"$state/running"
    ;;
  rm)
    printf '%s' 0 >"$state/running"
    printf '%s' 0 >"$state/exists"
    ;;
  *) exit 2 ;;
esac
""",
    )
    executable(
        shims / "rsync",
        r"""#!/bin/bash
set -eu
previous=""
last=""
for argument in "$@"; do
  previous="$last"
  last="$argument"
done
source_path="${previous%/}"
destination="${last%/}"
mkdir -p "$destination"
chmod -R u+w "$destination" 2>/dev/null || true
for item in "$destination"/* "$destination"/.[!.]* "$destination"/..?*; do
  [ -e "$item" ] || continue
  [ "$(basename "$item")" = .env ] && continue
  rm -rf "$item"
done
for item in "$source_path"/* "$source_path"/.[!.]* "$source_path"/..?*; do
  [ -e "$item" ] || continue
  [ "$(basename "$item")" = .env ] && continue
  cp -R "$item" "$destination/"
done
if [ "$source_path" = "$MOCK_RELEASE_DIR" ]; then
  : >"$MOCK_SIGNALS/promoting"
  while :; do /bin/sleep 1; done
fi
""",
    )
    executable(shims / "flock", "#!/bin/sh\nexit 0\n")
    executable(shims / "find", "#!/bin/sh\nexit 0\n")
    executable(shims / "sleep", "#!/bin/sh\nexit 0\n")

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{shims}:{environment['PATH']}",
            "TELESCAN_DEPLOY_TEST_MODE": "1",
            "TELESCAN_DEPLOY_TEST_ROOT": str(host),
            "TELESCAN_DEPLOY_TEST_LOCK": str(tmp_path / "deploy.lock"),
            "TELESCAN_DEPLOY_TEST_PYTHON": str(shims / "python"),
            "MOCK_ACTIVE_DIR": str(active),
            "MOCK_DOCKER_STATE": str(docker_state),
            "MOCK_RELEASE_DIR": str(release),
            "MOCK_SIGNALS": str(signals),
        }
    )
    controller = ROOT / "ops" / "deploy-production.sh"
    deployment = subprocess.Popen(
        ["/bin/bash", str(controller), "deploy", str(release), deploy_id],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    wait_for(signals / "promoting", deployment)
    os.killpg(deployment.pid, signal.SIGKILL)
    deployment.wait(timeout=5)

    intent = host / ".transactions" / ACTIVE_NAME / "active.json"
    assert intent.exists()
    assert (active / "new.marker").exists()

    recovery = subprocess.run(
        ["/bin/bash", str(controller), "recover"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert recovery.returncode == 0, recovery.stdout + recovery.stderr
    assert not intent.exists()
    assert (active / "old.marker").exists()
    assert not (active / "new.marker").exists()
    assert (docker_state / "exists").read_text(encoding="utf-8") == "1"
    assert (docker_state / "running").read_text(encoding="utf-8") == "1"
    assert (docker_state / "health").read_text(encoding="utf-8") == "healthy"
