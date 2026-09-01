#!/usr/bin/env bash
set -Eeuo pipefail

readonly SERVICE="telescan-bot-app"
if [[ "${TELESCAN_DEPLOY_TEST_MODE:-}" == "1" ]]; then
  readonly HOST_ROOT="${TELESCAN_DEPLOY_TEST_ROOT:?test host root is required}"
  readonly LOCK_FILE="${TELESCAN_DEPLOY_TEST_LOCK:?test lock path is required}"
  readonly PYTHON_BIN="${TELESCAN_DEPLOY_TEST_PYTHON:?test Python shim is required}"
else
  readonly HOST_ROOT="/home/ubuntu/telescan"
  readonly LOCK_FILE="/tmp/telescan-production-deploy.lock"
  readonly PYTHON_BIN="/usr/bin/python3"
fi
readonly ACTIVE_DIR="${HOST_ROOT}/Telescan-bot-app"
readonly RELEASES_DIR="${HOST_ROOT}/.releases/Telescan-bot-app"
readonly SNAPSHOTS_DIR="${HOST_ROOT}/.rollback/Telescan-bot-app"
readonly INTENT_ROOT="${HOST_ROOT}/.transactions/Telescan-bot-app"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly INTENT_TOOL="${SCRIPT_DIR}/deploy_intent.py"
readonly FSYNC_TOOL="${SCRIPT_DIR}/fsync_paths.py"
readonly DEPLOY_FAILURE=20
readonly RECOVERY_FAILURE=21

log() {
  printf '[telescan-bot deploy] %s\n' "$*"
}

intent() {
  "$PYTHON_BIN" "$INTENT_TOOL" --root "$INTENT_ROOT" "$@"
}

intent_exists() {
  intent exists >/dev/null 2>&1
}

stop_all_service_containers() {
  local container_ids
  container_ids="$(
    docker ps --all --quiet \
      --filter "label=com.docker.compose.service=${SERVICE}"
  )"
  if [[ -z "$container_ids" ]]; then
    return 0
  fi
  # Docker IDs contain no whitespace, so splitting the newline list is deliberate.
  docker stop --time 30 $container_ids >/dev/null 2>&1 || true
  docker rm --force $container_ids >/dev/null
}

healthy_container_id() {
  local workdir="$1"
  local all_ids running_ids global_ids container_id

  all_ids="$(
    cd "$workdir"
    docker compose ps --all --quiet "$SERVICE" </dev/null
  )"
  running_ids="$(
    cd "$workdir"
    docker compose ps --quiet "$SERVICE" </dev/null
  )"
  global_ids="$(
    docker ps --all --quiet \
      --filter "label=com.docker.compose.service=${SERVICE}"
  )"
  if [[ -z "$all_ids" || "$all_ids" == *$'\n'* ]]; then
    return 1
  fi
  container_id="$all_ids"
  if [[ "$container_id" != "$running_ids" || "$container_id" != "$global_ids" ]]; then
    return 1
  fi
  if [[ "$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null)" != "healthy" ]]; then
    return 1
  fi
  printf '%s\n' "$container_id"
}

wait_for_one_healthy() {
  local workdir="$1"
  local attempt
  for attempt in {1..24}; do
    if healthy_container_id "$workdir" >/dev/null; then
      healthy_container_id "$workdir"
      return 0
    fi
    sleep 5
  done
  return 1
}

restore_prepared_intent() {
  local phase active_dir snapshot_dir previous_image_id previous_image_ref
  local rollback_image_ref
  local rollback_ok=true

  phase="$(intent get phase)" || return 1
  [[ "$phase" == "prepared" ]] || return 1
  active_dir="$(intent get active_dir)" || return 1
  snapshot_dir="$(intent get snapshot_dir)" || return 1
  previous_image_id="$(intent get previous_image_id)" || return 1
  previous_image_ref="$(intent get previous_image_ref)" || return 1
  rollback_image_ref="$(intent get rollback_image_ref)" || return 1

  [[ "$active_dir" == "$ACTIVE_DIR" ]] || return 1
  [[ -d "$snapshot_dir" && ! -L "$snapshot_dir" ]] || return 1
  [[ -s "$ACTIVE_DIR/.env" && ! -L "$ACTIVE_DIR/.env" ]] || return 1
  if ! docker image inspect "$rollback_image_ref" >/dev/null 2>&1; then
    docker image inspect "$previous_image_id" >/dev/null 2>&1 || return 1
    docker tag "$previous_image_id" "$rollback_image_ref" || return 1
  fi

  log "recovering the protected previous release"
  stop_all_service_containers || rollback_ok=false
  rsync -a --delete --exclude='.env' "$snapshot_dir/" "$ACTIVE_DIR/" \
    || rollback_ok=false
  "$PYTHON_BIN" "$FSYNC_TOOL" tree "$ACTIVE_DIR" --exclude-env \
    || rollback_ok=false
  cd "$ACTIVE_DIR" || rollback_ok=false
  docker tag "$rollback_image_ref" "$previous_image_ref" || rollback_ok=false
  docker compose config --quiet </dev/null || rollback_ok=false
  docker compose up -d --no-deps --force-recreate --no-build "$SERVICE" \
    </dev/null || rollback_ok=false
  wait_for_one_healthy "$ACTIVE_DIR" >/dev/null || rollback_ok=false
  if [[ "$rollback_ok" != true ]]; then
    log "CRITICAL: protected previous release did not recover healthy"
    return 1
  fi
  intent clear --expected prepared || return 1
  log "previous release restored; durable intent cleared"
}

finish_committed_intent() {
  local phase active_dir previous_image_ref candidate_image_ref

  phase="$(intent get phase)" || return 1
  [[ "$phase" == "committed" ]] || return 1
  active_dir="$(intent get active_dir)" || return 1
  previous_image_ref="$(intent get previous_image_ref)" || return 1
  candidate_image_ref="$(intent get candidate_image_ref)" || return 1

  [[ "$active_dir" == "$ACTIVE_DIR" ]] || return 1
  [[ -s "$ACTIVE_DIR/.env" && ! -L "$ACTIVE_DIR/.env" ]] || return 1
  if ! healthy_container_id "$ACTIVE_DIR" >/dev/null; then
    log "finishing the durably committed candidate"
    docker image inspect "$candidate_image_ref" >/dev/null 2>&1 || return 1
    stop_all_service_containers || return 1
    docker tag "$candidate_image_ref" "$previous_image_ref" || return 1
    cd "$ACTIVE_DIR"
    docker compose config --quiet </dev/null || return 1
    docker compose up -d --no-deps --force-recreate --no-build "$SERVICE" \
      </dev/null || return 1
    wait_for_one_healthy "$ACTIVE_DIR" >/dev/null || return 1
  fi
  "$PYTHON_BIN" "$FSYNC_TOOL" tree "$ACTIVE_DIR" --exclude-env || return 1
  intent clear --expected committed || return 1
  log "committed candidate verified; durable intent cleared"
}

recover_active_intent() {
  local phase
  if ! intent_exists; then
    return 0
  fi
  intent validate || return 1
  phase="$(intent get phase)" || return 1
  case "$phase" in
    prepared)
      restore_prepared_intent
      ;;
    committed)
      finish_committed_intent
      ;;
    *)
      return 1
      ;;
  esac
}

handle_deploy_exit() {
  local status=$?
  trap - EXIT INT TERM
  if ((status == 0)); then
    return 0
  fi
  if intent_exists; then
    if recover_active_intent; then
      log "failed candidate was recovered safely"
      exit "$DEPLOY_FAILURE"
    fi
    log "CRITICAL: durable deployment recovery requires operator action"
    exit "$RECOVERY_FAILURE"
  fi
  exit "$DEPLOY_FAILURE"
}

deploy_release() {
  local release_dir="$1"
  local deploy_id="$2"
  local snapshot_dir previous_container_id previous_image_id previous_image_ref
  local rollback_image_ref candidate_image_ref

  [[ "$deploy_id" =~ ^[a-f0-9]{7,64}-[0-9]{1,20}-[0-9]{1,10}$ ]]
  [[ "$release_dir" == "$RELEASES_DIR/$deploy_id" ]]
  [[ -d "$release_dir" && ! -L "$release_dir" ]]
  [[ -z "$(find "$release_dir" -xdev -perm /022 -print -quit)" ]]
  [[ -x "$release_dir/ops/deploy-production.sh" ]]
  [[ -f "$release_dir/ops/deploy_intent.py" ]]
  [[ -f "$release_dir/ops/fsync_paths.py" ]]
  [[ -s "$ACTIVE_DIR/.env" && ! -L "$ACTIVE_DIR/.env" ]]
  [[ ! -e "$INTENT_ROOT/active.json" ]]
  "$PYTHON_BIN" "$FSYNC_TOOL" tree "$release_dir"
  "$PYTHON_BIN" "$FSYNC_TOOL" parents "$RELEASES_DIR"

  cd "$ACTIVE_DIR"
  docker compose config --quiet </dev/null
  previous_container_id="$(healthy_container_id "$ACTIVE_DIR")"
  previous_image_id="$(docker inspect --format '{{.Image}}' "$previous_container_id")"
  previous_image_ref="$(docker inspect --format '{{.Config.Image}}' "$previous_container_id")"
  [[ -n "$previous_image_id" && -n "$previous_image_ref" ]]

  snapshot_dir="$SNAPSHOTS_DIR/$deploy_id"
  rollback_image_ref="telescan-bot-app:rollback-$deploy_id"
  candidate_image_ref="telescan-bot-app:candidate-$deploy_id"
  install -d -m 0700 "$SNAPSHOTS_DIR"
  [[ ! -e "$snapshot_dir" ]]
  install -d -m 0700 "$snapshot_dir"
  rsync -a --delete --exclude='.env' "$ACTIVE_DIR/" "$snapshot_dir/"
  "$PYTHON_BIN" "$FSYNC_TOOL" tree "$snapshot_dir"
  "$PYTHON_BIN" "$FSYNC_TOOL" parents "$SNAPSHOTS_DIR"

  docker build --tag "$candidate_image_ref" "$release_dir"
  docker tag "$previous_image_id" "$rollback_image_ref"
  docker image inspect "$rollback_image_ref" >/dev/null
  install -d -m 0700 "$INTENT_ROOT"
  "$PYTHON_BIN" "$FSYNC_TOOL" parents "$INTENT_ROOT"

  intent publish \
    --deploy-id "$deploy_id" \
    --release-dir "$release_dir" \
    --snapshot-dir "$snapshot_dir" \
    --previous-image-id "$previous_image_id" \
    --previous-image-ref "$previous_image_ref" \
    --rollback-image-ref "$rollback_image_ref" \
    --candidate-image-ref "$candidate_image_ref"

  trap handle_deploy_exit EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  rsync -a --delete --exclude='.env' "$release_dir/" "$ACTIVE_DIR/"
  "$PYTHON_BIN" "$FSYNC_TOOL" tree "$ACTIVE_DIR" --exclude-env
  cd "$ACTIVE_DIR"
  docker compose config --quiet </dev/null
  docker compose stop --timeout 30 "$SERVICE" </dev/null
  [[ -z "$(docker compose ps --quiet "$SERVICE" </dev/null)" ]]
  docker tag "$candidate_image_ref" "$previous_image_ref"
  docker compose up -d --no-deps --force-recreate --no-build "$SERVICE" \
    </dev/null
  wait_for_one_healthy "$ACTIVE_DIR" >/dev/null

  # This fsynced compare-and-swap is the only deployment commit point.
  intent phase --expected prepared --new committed
  intent clear --expected committed
  trap - EXIT INT TERM
  log "candidate committed with exactly one healthy container"
}

main() {
  local mode="${1:-}"
  if [[ "$mode" == "recover-locked" ]]; then
    [[ "${TELESCAN_DEPLOY_LOCK_HELD:-}" == "1" ]]
    [[ "$(readlink "/proc/$$/fd/9")" == "$LOCK_FILE" ]]
    flock -n 9
    mode="recover"
  else
    exec 9>"$LOCK_FILE"
    if ! flock -w 1800 9; then
      log "timed out waiting for the shared production deployment lock"
      exit "$RECOVERY_FAILURE"
    fi
  fi

  case "$mode" in
    deploy)
      [[ $# -eq 3 ]]
      if intent_exists; then
        log "refusing a new deployment while durable recovery is pending"
        recover_active_intent || exit "$RECOVERY_FAILURE"
        exit "$DEPLOY_FAILURE"
      fi
      deploy_release "$2" "$3"
      ;;
    recover)
      [[ $# -eq 1 ]]
      recover_active_intent || exit "$RECOVERY_FAILURE"
      ;;
    *)
      printf 'usage: %s deploy RELEASE_DIR DEPLOY_ID | recover\n' "$0" >&2
      exit 64
      ;;
  esac
}

main "$@"
