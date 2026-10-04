#!/usr/bin/env bash
# run-loop.sh: own an unattended run end to end: launch (or pick up), watch, auto-resume, mark blocked, close out.
#
#   scripts/run-loop.sh [--branch <run-branch>] [--prompt "<handoff line>"] [--repo <owner>/<repo>]
#                       [--max-resumes 5] [--stall-min 20] [--max-hours 48] [--interval-sec 120]
#                       [--tmux <name>] [--new-run] [--no-closeout] [--skip-selftest] [--python python3] [--offline] [--dry-run]
#
# A thin loop over the kit's own tools, never a second implementation of them:
#   start   tools/headless/launch.sh (no session.json), tools/headless/resume.sh (recorded session dead while the run
#           has not ended), or just watch (recorded session still alive)
#   watch   tools/watch/run_watch.sh --mode box --project-dir . (end = run-state.json status / run report / HALT;
#           stall = no session-log write for the phase's stall limit, or the recorded claude pid is dead).
#           --stall-min is only the fallback when kit.json / run-state.json set no limit.
#   stall   tools/headless/resume.sh (it kills a still-live session first, so never two at once), up to --max-resumes;
#           then run-state.json status blocked + blocked_reason
#   end     done or blocked: wait for the claude process to exit, then resume the same session once with the
#           close-out prompt (lessons-writer, STATUS.md, RUN-REPORT.md, push). halted (.claude/HALT): no close-out.
# A run-state.json that already says done/blocked/halted is refused (it would end the watch at once) unless
# --new-run, which sets it back to running before launch.
# --tmux <name> re-runs this script detached in tmux session <name> (nohup when tmux is missing) and returns.
# --offline: the watcher skips GitHub (tests). Loop log: .claude/run-state/run-loop.log. Never bypassPermissions / --dangerously-skip-permissions.
set -u

BRANCH="" PROMPT="" REPO="" MAX_RESUMES=5 STALL_MIN=20 MAX_HOURS=48 INTERVAL=120 TMUX_NAME="" CLOSEOUT=1
SKIP_SELFTEST=0 PY="" DRY=0 NEW_RUN=0 LAST="" OFFLINE=()
ARGS=("$@")
while [ $# -gt 0 ]; do
    case "$1" in
        --branch) BRANCH=${2-}; shift 2 ;;
        --prompt) PROMPT=${2-}; shift 2 ;;
        --repo) REPO=${2-}; shift 2 ;;
        --max-resumes) MAX_RESUMES=${2-}; shift 2 ;;
        --stall-min) STALL_MIN=${2-}; shift 2 ;;
        --max-hours) MAX_HOURS=${2-}; shift 2 ;;
        --interval-sec) INTERVAL=${2-}; shift 2 ;;
        --tmux) TMUX_NAME=${2-}; shift 2 ;;
        --no-closeout) CLOSEOUT=0; shift ;;
        --new-run) NEW_RUN=1; shift ;;
        --skip-selftest) SKIP_SELFTEST=1; shift ;;
        --python) PY=${2-}; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        --offline) OFFLINE=(--offline); shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "run-loop: unknown argument $1" >&2; exit 2 ;;
    esac
done

die() { echo "run-loop: $*" >&2; exit 2; }
[[ $MAX_RESUMES =~ ^[0-9]+$ ]] || die "--max-resumes must be a whole number"

ROOT=$(cd "$(dirname "$0")/.." && pwd) || die "cannot find the repo root"
cd "$ROOT" || die "cannot cd to $ROOT"
if [ -z "$PY" ]; then
    if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
fi
SESS="tools/headless/session.py"
LAUNCH="tools/headless/launch.sh"
RESUME="tools/headless/resume.sh"
WATCH="tools/watch/run_watch.sh"
for f in "$SESS" "$LAUNCH" "$RESUME" "$WATCH"; do [ -f "$f" ] || die "missing $f (run from a kit project)"; done

# Detach: re-run inside tmux (or nohup) without --tmux, then return.
if [ -n "$TMUX_NAME" ]; then
    INNER=()
    skip=0
    for a in "${ARGS[@]}"; do
        if [ "$skip" = 1 ]; then skip=0; continue; fi
        if [ "$a" = --tmux ]; then skip=1; continue; fi
        INNER+=("$a")
    done
    Q=$(printf ' %q' "$ROOT/scripts/run-loop.sh" ${INNER[@]+"${INNER[@]}"})
    mkdir -p .claude/run-state
    if command -v tmux >/dev/null 2>&1; then
        CMD=(tmux new-session -d -s "$TMUX_NAME" -c "$ROOT" "$Q; echo; echo run-loop exited \$?; exec bash")
        WHERE="tmux attach -t $TMUX_NAME"
    else
        CMD=(nohup bash -c "$Q" ">>.claude/run-state/run-loop.out" "2>&1")
        WHERE="tail -f .claude/run-state/run-loop.log"
    fi
    if [ "$DRY" = 1 ]; then printf 'run-loop: dry run, would detach:'; printf ' %q' "${CMD[@]}"; printf '\n'; exit 0; fi
    if command -v tmux >/dev/null 2>&1; then
        tmux has-session -t "$TMUX_NAME" 2>/dev/null && die "tmux session $TMUX_NAME already exists"
        "${CMD[@]}" || die "tmux new-session failed"
    else
        echo "run-loop: tmux not found, using nohup" >&2
        nohup bash -c "$Q" >>.claude/run-state/run-loop.out 2>&1 &
    fi
    echo "run-loop: detached; follow with: $WHERE" >&2
    exit 0
fi

[ -n "$BRANCH" ] || BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || die "not a git repository"
[ -n "$REPO" ] || REPO=$(git remote get-url origin 2>/dev/null | sed -E 's#(\.git)?$##; s#.*[:/]([^/:]+/[^/]+)$#\1#')
[[ $REPO =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "cannot tell <owner>/<repo> from origin: pass --repo"
mkdir -p .claude/run-state build/headless
LOOPLOG=.claude/run-state/run-loop.log
log() { local l; l="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; echo "$l" >>"$LOOPLOG"; echo "run-loop: $*" >&2; }

run_status() { "$PY" -c 'import json,sys
try: d=json.load(open("run-state.json",encoding="utf-8-sig"))
except Exception: d={}
print(d.get("status","") if isinstance(d,dict) else "")'; }

mark_blocked() {  # reason -> run-state.json status blocked + blocked_reason (the script, not the session, writes it)
    "$PY" -c 'import json,sys,time
p="run-state.json"
try: d=json.load(open(p,encoding="utf-8-sig"))
except Exception: d={}
if not isinstance(d,dict): d={}
d.update(status="blocked",blocked_reason=sys.argv[1],updated=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()))
json.dump(d,open(p,"w",encoding="utf-8"),indent=2)' "$1"
    log "marked blocked: $1"
}

wait_exit() {  # wait up to $1 s for the recorded claude process to exit on its own
    local i
    for i in $(seq 1 "$1"); do
        "$PY" "$SESS" alive; case $? in 0|3) sleep 1 ;; *) return 0 ;; esac
    done
    return 1
}

BG=()
start_bg() {  # <launch|resume> [prompt]: run the kit launcher in the background, wait until it records its pid
    local before after i
    before=$("$PY" "$SESS" get pid 2>/dev/null)
    if [ "$1" = launch ]; then
        local a=(--branch "$BRANCH" --python "$PY")
        [ -n "$PROMPT" ] && a+=(--prompt "$PROMPT")
        [ "$SKIP_SELFTEST" = 1 ] && a+=(--skip-selftest)
        bash "$LAUNCH" "${a[@]}" >>"$LOOPLOG" 2>&1 &
    else
        bash "$RESUME" --python "$PY" ${2:+--prompt "$2"} >>"$LOOPLOG" 2>&1 &
    fi
    LAST=$!; BG+=("$LAST")
    for i in $(seq 1 60); do
        after=$("$PY" "$SESS" get pid 2>/dev/null)
        [ -n "$after" ] && [ "$after" != "$before" ] && { log "$1: claude pid $after"; return 0; }
        kill -0 "$LAST" 2>/dev/null || break
        sleep 1
    done
    wait "$LAST"; local rc=$?
    log "$1 did not start a session (exit $rc; see $LOOPLOG)"
    return 1
}

# --- pick the start ---
"$PY" "$SESS" alive >/dev/null 2>&1; ALIVE=$?
ST=$(run_status)
if [ -f .claude/run-state/session.json ] && { [ "$ALIVE" = 0 ] || [ "$ALIVE" = 3 ]; }; then
    START=watch
elif [ -f .claude/run-state/session.json ] && [ -n "$("$PY" "$SESS" get session_id)" ] && \
     [ "$ST" != done ] && [ "$ST" != blocked ] && [ "$ST" != halted ]; then
    START=resume
else
    START=launch
    case "$ST" in
        done|blocked|halted)
            [ "$NEW_RUN" = 1 ] || [ "$DRY" = 1 ] || die "run-state.json already says '$ST': pass --new-run to start a new run" ;;
    esac
fi
if [ "$DRY" = 1 ]; then
    echo "run-loop: dry run: repo $REPO branch $BRANCH start=$START (run-state status '${ST:-none}')"
    echo "run-loop: watch: bash $WATCH --repo $REPO --branch $BRANCH --mode box --project-dir . --stall-min $STALL_MIN"
    echo "run-loop: on stall: bash $RESUME (max $MAX_RESUMES), then mark blocked; close-out $( [ $CLOSEOUT = 1 ] && echo on || echo off)"
    exit 0
fi
log "start: $START (repo $REPO, branch $BRANCH, run-state status '${ST:-none}', max resumes $MAX_RESUMES)"
[ "$START" = launch ] && [ "$NEW_RUN" = 1 ] && case "$ST" in done|blocked|halted)
    "$PY" -c 'import json
p="run-state.json"; d=json.load(open(p,encoding="utf-8-sig")); d["status"]="running"; d.pop("blocked_reason",None)
json.dump(d,open(p,"w",encoding="utf-8"),indent=2)' && log "--new-run: run-state.json status $ST -> running" ;; esac
case "$START" in
    launch) start_bg launch || { mark_blocked "run-loop: launch.sh did not start a session"; } ;;
    resume) start_bg resume "Picked up by run-loop. Re-read run-state.json, STATUS.md, the tail of PROGRESS.md and PLAN.md, then continue the run." \
                || mark_blocked "run-loop: resume.sh did not start a session" ;;
esac

# --- watch, resume on stall ---
RESUMES=0 ERRORS=0 END=""
while [ -z "$END" ]; do
    J=$(bash "$WATCH" --repo "$REPO" --branch "$BRANCH" --mode box --project-dir . --stall-min "$STALL_MIN" ${OFFLINE[@]+"${OFFLINE[@]}"} \
        --max-hours "$MAX_HOURS" --interval-sec "$INTERVAL" 2>>"$LOOPLOG")
    RC=$?
    log "watch exit $RC: $J"
    case "$RC" in
        0) END=done ;;
        3) if [ -f .claude/HALT ] || [ "$(run_status)" = halted ]; then END=halted; else END=blocked; fi ;;
        2)
            if [ "$RESUMES" -ge "$MAX_RESUMES" ]; then
                mark_blocked "run-loop: stalled after $MAX_RESUMES auto-resumes"; END=blocked
            else
                RESUMES=$((RESUMES + 1))
                log "stall: auto-resume $RESUMES/$MAX_RESUMES"
                start_bg resume || { mark_blocked "run-loop: resume.sh failed after a stall"; END=blocked; }
            fi ;;
        5) mark_blocked "run-loop: watcher hard cap of $MAX_HOURS h reached"; END=blocked ;;
        *)
            ERRORS=$((ERRORS + 1))
            [ "$ERRORS" -ge 3 ] && { mark_blocked "run-loop: watcher error 3 times (exit $RC)"; END=blocked; }
            sleep 30 ;;
    esac
done
log "run ended: $END"

# --- close-out ---
if [ "$END" != halted ] && [ "$CLOSEOUT" = 1 ]; then
    wait_exit 900 || log "claude still alive 15 min after the run ended; resume.sh will stop it for the close-out"
    start_bg resume "Run ended ($END). Close-out, mandatory: use the lessons-writer subagent (LESSONS.md, the asset recipe skill and presets, kit and rubric fixes as a PR, before/after pairs in docs/progress/), then update STATUS.md and RUN-REPORT.md and push." \
        && wait_exit 7200
    log "close-out finished"
fi
wait ${BG[@]+"${BG[@]}"} 2>/dev/null
git push origin "HEAD:$BRANCH" >>"$LOOPLOG" 2>&1 && log "pushed $BRANCH" || log "push of $BRANCH failed (see $LOOPLOG)"
log "done: $END"
[ "$END" = done ] && exit 0 || exit 3
