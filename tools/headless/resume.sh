#!/usr/bin/env bash
# resume.sh: resume the headless run recorded in .claude/run-state/session.json, never as a second live session.
#
#   tools/headless/resume.sh [--prompt "<what changed, continue>"] [--grace 20] [--python python3] [--force] [--dry-run]
#
# Reads session_id and pid from session.json. If that pid is still a live claude process of this session (its command
# line names the session id), logs that it is killing it (.claude/run-state/resume.log and stderr), sends TERM, waits
# --grace seconds (default 20), then KILL. A pid that now belongs to another process (reused) is left alone; a live pid
# whose command line cannot be read is not killed and the resume is refused unless --force. Then runs
#   claude -p --resume <id> "<prompt>" --permission-mode acceptEdits --output-format stream-json --verbose
# with KIT_HEADLESS=1, stream to build/headless/<id>.resume-<n>.stream.jsonl, records the new pid (resumes, resumed_at)
# in session.json and copies the result's permission_denials into denied.jsonl, like launch.sh.
# Never bypassPermissions / --dangerously-skip-permissions.
set -u

PROMPT="" GRACE=20 PY="" FORCE=0 DRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --prompt) PROMPT=${2-}; shift 2 ;;
        --grace) GRACE=${2-}; shift 2 ;;
        --python) PY=${2-}; shift 2 ;;
        --force) FORCE=1; shift ;;
        --dry-run) DRY=1; shift ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "resume: unknown argument $1" >&2; exit 2 ;;
    esac
done

die() { echo "resume: $*" >&2; exit 2; }

ROOT=$(cd "$(dirname "$0")/../.." && pwd) || die "cannot find the repo root"
cd "$ROOT" || die "cannot cd to $ROOT"
if [ -z "$PY" ]; then
    if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
fi
command -v "$PY" >/dev/null 2>&1 || die "$PY not found"
command -v claude >/dev/null 2>&1 || [ "$DRY" = 1 ] || die "claude CLI not found"
[[ $GRACE =~ ^[0-9]+$ ]] || die "--grace must be whole seconds"
SESS="tools/headless/session.py"
[ -f .claude/run-state/session.json ] || die "no .claude/run-state/session.json: start the run with tools/headless/launch.sh"
SID=$("$PY" "$SESS" get session_id)
PID=$("$PY" "$SESS" get pid)
[ -n "$SID" ] || die "session.json has no session_id"
log() { "$PY" "$SESS" log "$*"; }
running() { "$PY" "$SESS" alive; case $? in 0|3) return 0 ;; esac; return 1; }   # a zombie counts as dead

"$PY" "$SESS" alive; ALIVE=$?
case "$ALIVE" in
    0)
        log "session $SID: pid $PID is still alive; killing it before resuming (TERM, KILL after ${GRACE}s)"
        if [ "$DRY" = 0 ]; then
            kill -TERM "$PID" 2>/dev/null
            for _ in $(seq 1 "$GRACE"); do
                running || break
                sleep 1
            done
            if running; then
                log "session $SID: pid $PID survived TERM for ${GRACE}s; sending KILL"
                kill -KILL "$PID" 2>/dev/null
                sleep 1
            fi
            running && die "pid $PID is still alive after KILL: not resuming (would be a second session)"
            log "session $SID: pid $PID stopped"
        fi ;;
    1) log "session $SID: pid ${PID:-none} is not running" ;;
    2) log "session $SID: pid $PID now belongs to another process (reused); not killing it" ;;
    *)
        if [ "$FORCE" = 1 ]; then
            log "session $SID: pid $PID is alive but its command line is unreadable; --force: resuming without killing it"
        else
            log "session $SID: pid $PID is alive but its command line is unreadable; not killing it and not resuming"
            die "check pid $PID by hand (stop it if it is this session's claude), then rerun; --force resumes anyway"
        fi ;;
esac

[ -n "$PROMPT" ] || PROMPT="Resumed after a stall or crash. Re-read run-state.json, the tail of PROGRESS.md and PLAN.md, then continue the run per the run-protocol skill."
R=$("$PY" "$SESS" get resumes | tr -cd '0-9')
N=$(( ${R:-0} + 1 ))
mkdir -p build/headless .claude/run-state
OUT="build/headless/$SID.resume-$N.stream.jsonl"
CMD=(claude -p --resume "$SID" "$PROMPT" --permission-mode acceptEdits --output-format stream-json --verbose)
if [ "$DRY" = 1 ]; then
    printf 'resume: dry run, would run:'; printf ' %q' "${CMD[@]}"; printf '\n'
    exit 0
fi
export KIT_HEADLESS=1
"${CMD[@]}" >"$OUT" &
CPID=$!
trap 'kill -TERM "$CPID" 2>/dev/null' INT TERM HUP
"$PY" "$SESS" set "pid=$CPID" "resumes=$N" "resumed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" "stream=$OUT" launcher=resume.sh \
    || echo "resume: WARNING: cannot record pid $CPID in session.json" >&2
log "session $SID: resumed (resume $N), claude pid $CPID, stream $OUT"
wait "$CPID"
RC=$?
"$PY" "$SESS" denials "$OUT" "$SID"
echo "resume: claude exited $RC" >&2
exit $RC
