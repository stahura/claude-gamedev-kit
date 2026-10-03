#!/usr/bin/env bash
# run_watch.sh: block until an unattended Claude Code run ends or stalls, then print ONE JSON line on stdout.
#
#   tools/watch/run_watch.sh --repo <owner>/<repo> --branch <run-branch> [--mode box|pc] [--session-id <id>]
#       [--project-dir <local clone>] [--log <session jsonl>] [--heartbeat-branch <b>] [--interval-sec 300]
#       [--stall-min 30] [--max-hours 6] [--once] [--offline]
#
# Final line: {"repo","branch","session_id","reason","last_log_write","head_sha","phase","stall_min",
#   "stall_min_source","pid","pid_alive","below_bar","headline"[,"detail"]}
#   reason done -> exit 0 | stall -> 2 | blocked, halted -> 3 | error -> 4 | timeout (--max-hours) -> 5
#   --once: one poll; if nothing ended or stalled: reason "running", exit 1.
# Run end: run-state.json "status" done/blocked/halted (local clone in box mode, and the branch on GitHub), a
# run-report.json / RUN-REPORT.md of this run on the branch, or .claude/HALT in the local clone.
# Stall: no write to the Claude session log (box: ~/.claude/projects/<slug>/<session>.jsonl + subagents/*.jsonl) or
# heartbeat (pc: heartbeat.json on <branch>-heartbeat) for the stall limit, or (box) the claude pid recorded in
# .claude/run-state/session.json is dead. Not commits. Stall limit of the current phase (run-state.json
# current_phase): run-state.json "stall_min", else kit.json stall_min.phases[<phase>], else stall_min.default, else
# --stall-min (default 30).
# pid_alive: true/false from session.json's pid (box mode with --project-dir), else null. below_bar/headline: the
# run report's headline, else the phases run-state.json records done_below_bar.
# Optional wake: WAKE_URL (+ WAKE_AUTH) gets the same JSON by POST before exit. Progress goes to stderr only.
# Needs bash, coreutils, python3, and gh (or curl + GH_TOKEN/GITHUB_TOKEN) for GitHub. See tools/watch/README.md.
set -u

REPO="" BRANCH="" MODE="box" SESSION_ID="" PROJECT_DIR="" LOG="" HB_BRANCH=""
INTERVAL=300 STALL_MIN=30 MAX_HOURS=6 ONCE=0 OFFLINE=0
START=$(date +%s)
LAST_LOG="" LOG_SRC="" HEAD_SHA="" NOTFOUND=0 BASELINE=""
PHASE="" STALL_SRC="--stall-min" CPID="" PID_ALIVE=""
TMPD=$(mktemp -d 2>/dev/null || echo "/tmp/run_watch.$$")
mkdir -p "$TMPD"
trap 'rm -rf "$TMPD"' EXIT
trap 'finish error 4 "terminated by signal"' INT TERM HUP

say() { printf '[run_watch %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }

jstr() {  # JSON string or null
    if [ -z "${1-}" ]; then printf 'null'; return; fi
    local s=$1
    s=${s//\\/\\\\}; s=${s//\"/\\\"}; s=${s//$'\n'/\\n}; s=${s//$'\r'/}; s=${s//$'\t'/ }
    printf '"%s"' "$s"
}

jnum() { if [[ ${1-} =~ ^[0-9]+([.][0-9]+)?$ ]]; then printf '%s' "$1"; else printf 'null'; fi; }

json_line() {  # reason detail
    local out below
    out="{\"repo\":$(jstr "$REPO"),\"branch\":$(jstr "$BRANCH"),\"session_id\":$(jstr "$SESSION_ID"),"
    out+="\"reason\":$(jstr "$1"),\"last_log_write\":$(jstr "$LAST_LOG"),\"head_sha\":$(jstr "$HEAD_SHA"),"
    out+="\"phase\":$(jstr "$PHASE"),\"stall_min\":$(jnum "$STALL_MIN"),\"stall_min_source\":$(jstr "$STALL_SRC"),"
    out+="\"pid\":$(jnum "$CPID"),\"pid_alive\":${PID_ALIVE:-null},"
    below=$(below_bar_json 2>/dev/null)
    out+="${below:-\"below_bar\":[],\"headline\":null}"
    if [ -n "${2-}" ]; then out+=",\"detail\":$(jstr "$2")"; fi
    printf '%s}' "$out"
}

state_file() {  # <name>: the local clone's copy, else the one fetched from GitHub this poll
    if [ -n "$PROJECT_DIR" ] && [ -f "$PROJECT_DIR/$1" ]; then printf '%s' "$PROJECT_DIR/$1"
    elif [ -f "$TMPD/remote/$1" ]; then printf '%s' "$TMPD/remote/$1"
    elif [ "$1" = run-state.json ] && [ -f "$TMPD/rs.json" ]; then printf '%s' "$TMPD/rs.json"
    elif [ "$1" = kit.json ] && [ -f "$TMPD/kit.json" ]; then printf '%s' "$TMPD/kit.json"
    fi
}

below_bar_json() {  # "below_bar":[...],"headline":... from run-report.json (headline) and run-state.json phases
    python3 -c 'import json,sys
def load(p):
    try:
        d=json.load(open(p,encoding="utf-8-sig")) if p else {}
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
rep,rs=load(sys.argv[1]),load(sys.argv[2])
ph=rs.get("phases") if isinstance(rs.get("phases"),dict) else {}
below=[p for p,v in ph.items() if isinstance(v,dict) and v.get("status")=="done_below_bar"]
if isinstance(rep.get("below_bar"),list):
    below+= [p for p in rep["below_bar"] if isinstance(p,str) and p not in below]
head=rep.get("headline") if isinstance(rep.get("headline"),str) and rep.get("headline") else None
if below and not head:
    head="BELOW BAR: %d visual phase(s) closed without a reviewer pass: %s" % (len(below), ", ".join(below))
print("\"below_bar\":%s,\"headline\":%s" % (json.dumps(below), json.dumps(head)))' \
        "$(state_file run-report.json)" "$(state_file run-state.json)"
}

stall_limit() {  # sets STALL_MIN STALL_SRC PHASE from run-state.json + kit.json (fallback: --stall-min)
    local r
    r=$(python3 -c 'import json,re,sys
def load(p):
    try:
        d=json.load(open(p,encoding="utf-8-sig")) if p else {}
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
rs,kit=load(sys.argv[1]),load(sys.argv[2])
m=re.match(r"\s*(P\d+)",str(rs.get("current_phase") or ""))
ph=m.group(1) if m else ""
num=lambda v: isinstance(v,(int,float)) and not isinstance(v,bool) and v>0
sm=kit.get("stall_min")
per=(sm.get("phases") or {}) if isinstance(sm,dict) else {}
out=lambda v,s: print("%s|%s|%s" % (v,s,ph))
if num(rs.get("stall_min")): out(rs["stall_min"],"run-state.json stall_min")
elif ph and num(per.get(ph)): out(per[ph],"kit.json stall_min.phases."+ph)
elif isinstance(sm,dict) and num(sm.get("default")): out(sm["default"],"kit.json stall_min.default")
elif num(sm): out(sm,"kit.json stall_min")
else: out("-","--stall-min")' "$(state_file run-state.json)" "$(state_file kit.json)" 2>/dev/null)
    local v s p
    IFS='|' read -r v s p <<<"$r"
    PHASE=${p-}
    if isnum "${v-}"; then STALL_MIN=$v; STALL_SRC=$s; else STALL_MIN=$STALL_CLI; STALL_SRC="--stall-min"; fi
}

pid_status() {  # box mode: CPID / PID_ALIVE from the local clone's .claude/run-state/session.json
    CPID="" PID_ALIVE=""
    local sj="$PROJECT_DIR/.claude/run-state/session.json"
    [ -n "$PROJECT_DIR" ] && [ "$MODE" = box ] && [ -f "$sj" ] || return 0
    CPID=$(json_field "$sj" pid)
    [[ $CPID =~ ^[0-9]+$ ]] || { CPID=""; return 0; }
    if kill -0 "$CPID" 2>/dev/null || ps -p "$CPID" >/dev/null 2>&1; then PID_ALIVE=true; else PID_ALIVE=false; fi
}

wake() {
    [ -n "${WAKE_URL-}" ] || return 0
    command -v curl >/dev/null 2>&1 || { say "wake: curl not found"; return 0; }
    local hdr=()
    if [ -n "${WAKE_AUTH-}" ]; then
        case "$WAKE_AUTH" in
            *:*) hdr=(-H "$WAKE_AUTH") ;;
            *) hdr=(-H "Authorization: $WAKE_AUTH") ;;
        esac
    fi
    local host=${WAKE_URL#*://}; host=${host%%/*}; host=${host##*@}
    if curl -sS -m 15 -o /dev/null -X POST -H "Content-Type: application/json" ${hdr[@]+"${hdr[@]}"} \
            --data "$1" "$WAKE_URL" 2>"$TMPD/wake.err"; then
        say "wake: posted to $host"
    else
        say "wake: POST to $host failed ($(head -c 200 "$TMPD/wake.err" | tr '\n' ' '))"
    fi
}

finish() {  # reason exit-code [detail]
    trap - INT TERM HUP
    local line
    line=$(json_line "$1" "${3-}")
    [ "$1" = "running" ] || wake "$line"
    printf '%s\n' "$line"
    exit "$2"
}

usage() { sed -n '2,22p' "$0" >&2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO=${2-}; shift 2 ;;
        --branch) BRANCH=${2-}; shift 2 ;;
        --mode) MODE=${2-}; shift 2 ;;
        --session-id) SESSION_ID=${2-}; shift 2 ;;
        --project-dir) PROJECT_DIR=${2-}; shift 2 ;;
        --log) LOG=${2-}; shift 2 ;;
        --heartbeat-branch) HB_BRANCH=${2-}; shift 2 ;;
        --interval-sec) INTERVAL=${2-}; shift 2 ;;
        --stall-min) STALL_MIN=${2-}; shift 2 ;;
        --max-hours) MAX_HOURS=${2-}; shift 2 ;;
        --once) ONCE=1; shift ;;
        --offline) OFFLINE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) say "unknown argument: $1"; finish error 4 "unknown argument: $1" ;;
    esac
done

isnum() { [[ ${1-} =~ ^[0-9]+([.][0-9]+)?$ ]]; }
[[ $REPO =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || finish error 4 "--repo must be <owner>/<repo>"
[ -n "$BRANCH" ] || finish error 4 "--branch is required"
[ "$MODE" = box ] || [ "$MODE" = pc ] || finish error 4 "--mode must be box or pc"
[[ $INTERVAL =~ ^[0-9]+$ ]] && [ "$INTERVAL" -gt 0 ] || finish error 4 "--interval-sec must be a positive integer"
isnum "$STALL_MIN" || finish error 4 "--stall-min must be a number"
STALL_CLI=$STALL_MIN
isnum "$MAX_HOURS" || finish error 4 "--max-hours must be a number"
command -v python3 >/dev/null 2>&1 || finish error 4 "python3 not found"
if [ -n "$PROJECT_DIR" ] && [ ! -d "$PROJECT_DIR" ]; then finish error 4 "--project-dir not found: $PROJECT_DIR"; fi
[ "$MODE" = pc ] || [ -n "$PROJECT_DIR" ] || [ -n "$LOG" ] || [ -n "$SESSION_ID" ] || \
    say "box mode without --project-dir, --log or --session-id: stall detection has no session log"
HB_BRANCH=${HB_BRANCH:-$BRANCH-heartbeat}
TOKEN=${GH_TOKEN:-${GITHUB_TOKEN:-}}

py() { python3 -c "$@"; }

json_field() {  # file key... -> first non-empty value of the keys (strings/numbers), else empty
    py 'import json,sys
try:
    d=json.load(open(sys.argv[1],encoding="utf-8-sig"))
except Exception:
    sys.exit(0)
for k in sys.argv[2:]:
    v=d.get(k) if isinstance(d,dict) else None
    if isinstance(v,dict): v=v.get("ts_utc") or v.get("ts")
    if v not in (None,""): print(v); break' "$@" 2>/dev/null
}

to_epoch() {  # ISO-8601 (Z or offset) -> epoch seconds, else empty
    py 'import sys,datetime
s=sys.argv[1].strip().replace("Z","+00:00")
for f in (None,"%Y-%m-%d %H:%M:%S%z","%Y-%m-%dT%H:%M%z","%Y-%m-%d %H:%M%z"):
    try:
        d=datetime.datetime.fromisoformat(s) if f is None else datetime.datetime.strptime(s,f)
        if d.tzinfo is None: d=d.replace(tzinfo=datetime.timezone.utc)
        print(int(d.timestamp())); break
    except Exception: pass' "$1" 2>/dev/null
}

to_iso() { py 'import sys,datetime; print(datetime.datetime.fromtimestamp(int(sys.argv[1]),datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$1"; }

mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || py 'import os,sys; print(int(os.path.getmtime(sys.argv[1])))' "$1" 2>/dev/null; }

urlq() { py 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1],safe=""))' "$1"; }

# gh_get <api path> <raw|json> <outfile>: 0 ok, 1 not found (404), 2 other error (retried next poll)
gh_get() {
    local accept="application/vnd.github+json" code
    [ "$2" = raw ] && accept="application/vnd.github.raw"
    if command -v gh >/dev/null 2>&1; then
        local to=()
        command -v timeout >/dev/null 2>&1 && to=(timeout 30)
        if ${to[@]+"${to[@]}"} gh api -H "Accept: $accept" "$1" >"$3" 2>"$TMPD/gh.err"; then return 0; fi
        grep -q -E 'HTTP 404|Not Found' "$TMPD/gh.err" && return 1
        say "gh api $1: $(head -c 200 "$TMPD/gh.err" | tr '\n' ' ')"
        return 2
    fi
    command -v curl >/dev/null 2>&1 || { say "neither gh nor curl found"; return 2; }
    local auth=()
    [ -n "$TOKEN" ] && auth=(-H "Authorization: Bearer $TOKEN")
    code=$(curl -sS -m 20 -o "$3" -w '%{http_code}' -H "Accept: $accept" ${auth[@]+"${auth[@]}"} \
        "https://api.github.com/$1" 2>"$TMPD/curl.err") || { say "curl $1 failed"; return 2; }
    [ "$code" = 200 ] && return 0
    [ "$code" = 404 ] && return 1
    say "GitHub API $1: HTTP $code"
    return 2
}

report_outcome() {  # run-report.json file -> done|blocked|halted|"" (unknown)
    local o
    o=$(json_field "$1" outcome status result)
    case "$o" in
        blocked|halted) printf '%s' "$o" ;;
        *) printf 'done' ;;
    esac
}

run_id_of() { json_field "$1" run; }

check_end() {  # dir-or-"" (local) ; sets END_REASON END_DETAIL; reads files run-state.json, run-report.json, RUN-REPORT.md
    local rs=$1/run-state.json rep=$1/run-report.json md=$1/RUN-REPORT.md st rid
    st=$( [ -f "$rs" ] && json_field "$rs" status )
    case "$st" in
        done|blocked|halted) END_REASON=$st; END_DETAIL="run-state.json status $st ($2)"; return 0 ;;
    esac
    rid=$( [ -f "$rs" ] && run_id_of "$rs" )
    if [ -f "$rep" ]; then
        local rrid; rrid=$(run_id_of "$rep")
        if [ -z "$rid" ] || [ -z "$rrid" ] || [ "$rid" = "$rrid" ]; then
            END_REASON=$(report_outcome "$rep"); END_DETAIL="run-report.json present ($2)"; return 0
        fi
    elif [ -f "$md" ] && { [ -z "$rid" ] || grep -q -- "$rid" "$md"; }; then
        END_REASON=done; END_DETAIL="RUN-REPORT.md present ($2)"; return 0
    fi
    return 1
}

local_log_time() {  # box mode: newest mtime of the session log and its subagent logs -> LAST_LOG / LOG_SRC
    local base="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" dir="" f t best=0 sid=$SESSION_ID files=()
    if [ -n "$LOG" ]; then
        files=("$LOG"); dir=$(dirname "$LOG"); sid=$(basename "$LOG" .jsonl)
    else
        if [ -n "$PROJECT_DIR" ]; then
            local p
            for p in "$(cd "$PROJECT_DIR" && pwd -P)" "$(cd "$PROJECT_DIR" && pwd)"; do
                local slug; slug=$(printf '%s' "$p" | sed 's/[^A-Za-z0-9]/-/g')
                if [ -d "$base/$slug" ]; then dir=$base/$slug; break; fi
            done
            if [ -z "$sid" ] && [ -f "$PROJECT_DIR/.claude/run-state/session.json" ]; then
                sid=$(json_field "$PROJECT_DIR/.claude/run-state/session.json" session_id)
            fi
        fi
        if [ -z "$dir" ] && [ -n "$sid" ]; then
            f=$(ls -1 "$base"/*/"$sid".jsonl 2>/dev/null | head -n 1)
            [ -n "$f" ] && dir=$(dirname "$f")
        fi
        [ -n "$dir" ] || return 0
        if [ -z "$sid" ]; then
            f=$(ls -1t "$dir"/*.jsonl 2>/dev/null | head -n 1)
            [ -n "$f" ] && sid=$(basename "$f" .jsonl)
        fi
        [ -n "$sid" ] && files=("$dir/$sid.jsonl")
    fi
    [ -n "$sid" ] && [ -z "$SESSION_ID" ] && SESSION_ID=$sid
    for f in ${files[@]+"${files[@]}"} "$dir/$sid"/subagents/*.jsonl; do
        [ -f "$f" ] || continue
        t=$(mtime "$f"); [ -n "$t" ] && [ "$t" -gt "$best" ] && best=$t
    done
    if [ "$best" -gt 0 ]; then LAST_LOG=$(to_iso "$best"); LOG_SRC="session log"; fi
}

remote_log_time() {  # pc mode: heartbeat branch, else run-state.json updated/heartbeat, else head commit date
    local t=""
    if gh_get "repos/$REPO/contents/heartbeat.json?ref=$(urlq "$HB_BRANCH")" raw "$TMPD/hb.json"; then
        t=$(json_field "$TMPD/hb.json" ts_utc)
        [ -z "$SESSION_ID" ] && SESSION_ID=$(json_field "$TMPD/hb.json" session_id)
        [ -n "$t" ] && { LAST_LOG=$t; LOG_SRC="heartbeat branch $HB_BRANCH"; return 0; }
    fi
    if [ -f "$TMPD/rs.json" ]; then
        t=$(json_field "$TMPD/rs.json" heartbeat updated)
        if [ -n "$t" ] && [ -n "$(to_epoch "$t")" ]; then LAST_LOG=$t; LOG_SRC="run-state.json updated (no heartbeat)"; return 0; fi
    fi
    if gh_get "repos/$REPO/commits/$(urlq "$BRANCH")" json "$TMPD/head.json"; then
        t=$(py 'import json,sys; d=json.load(open(sys.argv[1])); print(d["commit"]["committer"]["date"])' "$TMPD/head.json" 2>/dev/null)
        [ -n "$t" ] && { LAST_LOG=$t; LOG_SRC="head commit date (no heartbeat, last resort)"; }
    fi
}

end_with() {  # END_REASON -> finish
    case "$END_REASON" in done) finish done 0 "$END_DETAIL" ;; *) finish "$END_REASON" 3 "$END_DETAIL" ;; esac
}

poll() {  # one poll: gather local + GitHub state and the last log write, then decide; calls finish on a terminal state
    END_REASON="" END_DETAIL=""
    local rdir="$TMPD/remote" remote_ok=0
    rm -rf "$rdir"; mkdir -p "$rdir"
    [ -n "$PROJECT_DIR" ] && HEAD_SHA=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || true)
    if [ "$OFFLINE" = 0 ]; then
        local rc
        gh_get "repos/$REPO/branches/$(urlq "$BRANCH")" json "$TMPD/branch.json"; rc=$?
        if [ $rc = 1 ]; then
            NOTFOUND=$((NOTFOUND + 1))
            say "repo or branch not found: $REPO $BRANCH ($NOTFOUND/3)"
            if [ "$NOTFOUND" -ge 3 ] || [ "$ONCE" = 1 ]; then finish error 4 "repo or branch not found: $REPO $BRANCH"; fi
        elif [ $rc = 0 ]; then
            NOTFOUND=0
            [ -z "$PROJECT_DIR" ] && HEAD_SHA=$(py 'import json,sys; print(json.load(open(sys.argv[1]))["commit"]["sha"])' "$TMPD/branch.json" 2>/dev/null)
            local f
            for f in run-state.json run-report.json RUN-REPORT.md kit.json; do
                gh_get "repos/$REPO/contents/$f?ref=$(urlq "$BRANCH")" raw "$rdir/$f" || rm -f "$rdir/$f"
            done
            [ -f "$rdir/run-state.json" ] && cp "$rdir/run-state.json" "$TMPD/rs.json"
            [ -f "$rdir/kit.json" ] && cp "$rdir/kit.json" "$TMPD/kit.json"
            remote_ok=1
        fi
    fi
    LAST_LOG="" LOG_SRC=""
    if [ "$MODE" = box ]; then local_log_time; elif [ "$OFFLINE" = 0 ]; then remote_log_time; fi
    stall_limit
    pid_status
    if [ -n "$PROJECT_DIR" ]; then
        [ -f "$PROJECT_DIR/.claude/HALT" ] && finish halted 3 ".claude/HALT in the local clone"
        check_end "$PROJECT_DIR" "local clone" && end_with
    fi
    [ "$remote_ok" = 1 ] && check_end "$rdir" "GitHub $BRANCH" && end_with
    if [ "$PID_ALIVE" = false ]; then
        finish stall 2 "claude pid $CPID from .claude/run-state/session.json is not running and the run has not ended (resume: tools/headless/resume.sh)"
    fi
    local now last age
    now=$(date +%s)
    if [ -n "$LAST_LOG" ]; then
        last=$(to_epoch "$LAST_LOG")
    else
        [ -n "$BASELINE" ] || BASELINE=$now
        last=$BASELINE; LOG_SRC="no session log or heartbeat found (watcher start)"
    fi
    age=$(( (now - ${last:-$now}) / 60 ))
    say "poll: last write $age min ago via $LOG_SRC; stall limit $STALL_MIN min ($STALL_SRC${PHASE:+, phase $PHASE}); pid ${CPID:-?} alive ${PID_ALIVE:-?}; head ${HEAD_SHA:0:12}"
    if py 'import sys; sys.exit(0 if float(sys.argv[1]) >= float(sys.argv[2])*60 else 1)' "$((now - ${last:-$now}))" "$STALL_MIN"; then
        finish stall 2 "no session log write for $age min (>= $STALL_MIN, $STALL_SRC) via $LOG_SRC"
    fi
}

say "watching $REPO $BRANCH (mode $MODE, every ${INTERVAL}s, stall limit per phase from run-state/kit.json, fallback ${STALL_MIN} min, cap ${MAX_HOURS} h)"
while :; do
    poll
    [ "$ONCE" = 1 ] && finish running 1 "last write via ${LOG_SRC:-none}"
    if py 'import sys; sys.exit(0 if float(sys.argv[1]) >= float(sys.argv[2])*3600 else 1)' "$(( $(date +%s) - START ))" "$MAX_HOURS"; then
        finish timeout 5 "hard cap of $MAX_HOURS h reached"
    fi
    sleep "$INTERVAL"
done
