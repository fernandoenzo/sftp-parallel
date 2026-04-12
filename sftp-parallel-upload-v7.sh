#!/usr/bin/env bash
set -euo pipefail

readonly MAX_JOBS=16
readonly CONNECT_TIMEOUT=10
readonly SYSTEMD_TIMEOUT=86400
readonly DEFAULT_JOBS=2
readonly DEFAULT_REMOTE_DIR="."
readonly EX_OK=0
readonly EX_USAGE=2
readonly EX_NOINPUT=66
readonly EX_JOBFAIL=74

# Skip systemd-run for help or when already in a cgroup
if [[ -z "${_SFTP_IN_CGROUP:-}" ]] && ! echo " $* " | grep -qE ' -h |--help' && command -v systemd-run >/dev/null 2>&1; then
    exec systemd-run --user --scope --property=RuntimeMaxSec=${SYSTEMD_TIMEOUT}s \
        --setenv=_SFTP_IN_CGROUP=1 --quiet \
        -- "$0" "$@"
fi

# ── sftp-parallel-upload.sh ────────────────────────────────────────────────────
# Upload files via parallel `put -f` sessions (fsync'd).
# Usage: sftp-parallel-upload.sh [-j N] [-r dir] user@host local_dir
#   -j N   Parallel sessions (default: 2, max: 16) | -r dir Remote directory | -h Help
#   e.g: sftp-parallel-upload.sh -j 4 user@host /tmp/uploads
# ────────────────────────────────────────────────────────────────────────────────

# Shared arrays
declare -a PIDS
declare -a FILES
TOTAL=0
declare -a BUCKETS
FAILED=0
WORK_DIR=""
_CLEANUP_DONE=0

usage() {
    sed -n '/^# ──.*──$/,/^# ──.*──$/s/^# \?//p' "$0"
    exit "${1:-0}"
}

log_info()  { printf '→ %s\n' "$*"; }
log_error() { printf '✗ %s\n' "$*" >&2; }
log_debug() { [[ "${DEBUG:-0}" == "1" ]] && printf '[DEBUG] %s\n' "$*" >&2 || true; }

sftp_escape() {
    local str="$1"
    str="${str//\\/\\\\}"
    str="${str//\"/\\\"}"
    printf '%s' "$str"
}

create_batch() {
    local remote_dir="$1"
    local local_dir="$2"
    shift 2
    local -a files=("$@")
    local batch_cmds

    batch_cmds="cd \"$(sftp_escape "$remote_dir")\""
    for FILE in "${files[@]}"; do
        [[ -n "$FILE" ]] || continue
        batch_cmds+=$'\n'"put -f \"$(sftp_escape "${local_dir}/${FILE}")\""
    done
    batch_cmds+=$'\n'"bye"

    printf '%s' "$batch_cmds"
}

cleanup() {
    [[ "$_CLEANUP_DONE" -eq 1 ]] && return
    _CLEANUP_DONE=1
    for pid in "${PIDS[@]:-}"; do
        wait "$pid" 2>/dev/null || true
    done
    [[ -n "${WORK_DIR:-}" && -d "${WORK_DIR:-}" ]] && rm -rf -- "${WORK_DIR:-}"
}

validate_inputs() {
    local host="$1"
    local local_dir="$2"
    local jobs="$3"

    if [[ ! -d "$local_dir" ]]; then
        log_error "Error: '$local_dir' is not a directory"
        return $EX_NOINPUT
    fi

    if ! [[ "$jobs" =~ ^[1-9][0-9]*$ ]]; then
        log_error "Error: -j must be a positive integer, got '$jobs'"
        return $EX_USAGE
    fi

    if [[ "$jobs" -gt $MAX_JOBS ]]; then
        log_error "Error: -j must be at most 16, got '$jobs'"
        return $EX_USAGE
    fi

    command -v sftp >/dev/null 2>&1 || { log_error "Error: sftp command not found in PATH"; return $EX_NOINPUT; }

    mapfile -d '' -t FILES < <(find "$local_dir" -maxdepth 1 -type f -printf '%P\0' | LC_ALL=C sort -z)
    TOTAL=${#FILES[@]}

    if [[ $TOTAL -eq 0 ]]; then
        echo "No files found in '$local_dir'" >&2
        return $EX_NOINPUT
    fi

    for FILE in "${FILES[@]}"; do
        if [[ ! -r "${local_dir}/${FILE}" ]]; then
            log_error "Error: Cannot read '${local_dir}/${FILE}'"
            return $EX_NOINPUT
        fi
        if [[ "$FILE" =~ [[:cntrl:]] ]]; then
            log_error "Error: Filename contains control characters: '$FILE'"
            return $EX_USAGE
        fi
    done
}

distribute_files() {
    local -n _out_buckets=$1; shift
    local -n _in_files=$1; shift
    local _jobs=$1
    local _idx _file

    _out_buckets=()
    for (( _idx = 0; _idx < _jobs; _idx++ )); do
        _out_buckets[_idx]=""
    done

    _idx=0
    for _file in "${_in_files[@]}"; do
        _out_buckets[$_idx]+="$_file"$'\n'
        _idx=$(( (_idx + 1) % _jobs ))
    done
}

run_uploads() {
    local -n _buckets=$1
    local _host=$2
    local _work_dir=$3
    local _bucket_num=0
    local _bucket_contents _batch_cmds
    local -a _bucket_files

    PIDS=()

    for _bucket_contents in "${_buckets[@]}"; do
        [[ -z "$_bucket_contents" ]] && continue

        mapfile -t _bucket_files <<< "$_bucket_contents"
        _batch_cmds=$(create_batch "$REMOTE_DIR" "$LOCAL_DIR" "${_bucket_files[@]}")

        echo "  [session $((_bucket_num + 1))] files: $(echo "$_bucket_contents" | tr '\n' ' ')"
        sftp -o ConnectTimeout=${SFTP_CONNECT_TIMEOUT:-${CONNECT_TIMEOUT}} -o BatchMode=yes -N -b - "$_host" <<< "$_batch_cmds" > "$_work_dir/out_${_bucket_num}.log" 2>&1 &
        PIDS+=($!)

        _bucket_num=$(( _bucket_num + 1 ))
    done
}

collect_results() {
    local _work_dir=$1
    local _i _pid _exit_code

    FAILED=0
    for _i in "${!PIDS[@]}"; do
        _pid=${PIDS[$_i]}
        _exit_code=0
        wait "$_pid" || _exit_code=$?
        if [[ $_exit_code -ne 0 ]]; then
            log_error "Session $((_i + 1)) failed (exit $_exit_code):"
            cat "$_work_dir/out_${_i}.log" >&2
            FAILED=$(( FAILED + 1 ))
        else
            log_info "Session $((_i + 1)) completed"
        fi
    done
}

main() {
    # Convert long options to short for getopts
    local -a NEWARGS=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --jobs=*) NEWARGS+=("-j" "${1#*=}"); shift ;;
            --remote-dir=*) NEWARGS+=("-r" "${1#*=}"); shift ;;
            --help) NEWARGS+=(-h); shift ;;
            *) NEWARGS+=("$1"); shift ;;
        esac
    done
    set -- "${NEWARGS[@]}"

    local JOBS="${SFTP_JOBS:-${DEFAULT_JOBS}}"
    local REMOTE_DIR="${DEFAULT_REMOTE_DIR}"
    local HOST LOCAL_DIR

    while getopts "j:r:h" opt; do
        case "$opt" in
            j) JOBS="$OPTARG" ;;
            r) REMOTE_DIR="$OPTARG" ;;
            h) usage ;;
            *) usage $EX_USAGE ;;
        esac
    done
    shift $((OPTIND - 1))

    HOST="${1:-}"
    LOCAL_DIR="${2:-}"
    if [[ -z "$HOST" || -z "$LOCAL_DIR" ]]; then
        log_error "Error: specify user@host and local_dir as positional arguments"
        exit $EX_USAGE
    fi

    validate_inputs "$HOST" "$LOCAL_DIR" "$JOBS" || exit $?

    if ! sftp -o BatchMode=yes -o ConnectTimeout=${SFTP_CONNECT_TIMEOUT:-${CONNECT_TIMEOUT}} -N -b - "$HOST" >/dev/null 2>&1 <<EOF
cd "$(sftp_escape "$REMOTE_DIR")"
bye
EOF
    then
        log_error "Error: Cannot connect to '$HOST' or remote directory '$REMOTE_DIR' does not exist"
        exit $EX_NOINPUT
    fi

    log_info "Uploading $TOTAL file(s) to $HOST:$REMOTE_DIR with $JOBS parallel session(s)"

    distribute_files BUCKETS FILES "$JOBS"

    trap cleanup EXIT INT TERM
    WORK_DIR=$(mktemp -d)

    run_uploads BUCKETS "$HOST" "$WORK_DIR"

    collect_results "$WORK_DIR"

    if [[ $FAILED -gt 0 ]]; then
        log_error "$FAILED session(s) failed out of ${#PIDS[@]}"
        exit $EX_JOBFAIL
    fi

    log_info "Done: $TOTAL file(s) uploaded"
}

main "$@"