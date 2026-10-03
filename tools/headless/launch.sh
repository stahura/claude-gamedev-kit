#!/usr/bin/env bash
# launch.sh: start an unattended headless Claude Code run in this repo (Linux/macOS/Git Bash). See docs/headless.md.
#
#   tools/headless/launch.sh --branch <run-branch> [--prompt "<handoff line>"] [--python python3] [--skip-selftest]
#                            [--dry-run]
#
# Checks the pre-launch list (run branch checked out, .claude/settings.json committed, auth, folder trust, selftest),
# refuses while the session in .claude/run-state/session.json is still alive (use resume.sh), generates the session id,
# prints the resume command, then runs
#   claude -p "<handoff line>" --permission-mode acceptEdits --session-id <id> --output-format stream-json --verbose
# with KIT_HEADLESS=1 (the PermissionRequest hook denies and logs anything off the allowlist) and writes
# session.json {session_id, pid, started, branch, head, mode, log_path, stream, launcher, resumes}. The stream goes to
# build/headless/<id>.stream.jsonl; afterwards the result's permission_denials are appended to
# .claude/run-state/denied.jsonl. Never bypassPermissions / --dangerously-skip-permissions.
set -u

BRANCH="" PROMPT="" PY="" SKIP_SELFTEST=0 DRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --branch) BRANCH=${2-}; shift 2 ;;
        --prompt) PROMPT=${2-}; shift 2 ;;
        --python) PY=${2-}; shift 2 ;;
        --skip-selftest) SKIP_SELFTEST=1; shift ;;
        --dry-run) DRY=1; shift ;;
        -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
        *) echo "launch: unknown argument $1" >&2; exit 2 ;;
    esac
done

die() { echo "launch: $*" >&2; exit 2; }
warn() { echo "launch: WARNING: $*" >&2; }

ROOT=$(cd "$(dirname "$0")/../.." && pwd) || die "cannot find the repo root"
cd "$ROOT" || die "cannot cd to $ROOT"
if [ -z "$PY" ]; then
    if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
fi
command -v "$PY" >/dev/null 2>&1 || die "$PY not found"
command -v git >/dev/null 2>&1 || die "git not found"
command -v claude >/dev/null 2>&1 || [ "$DRY" = 1 ] || die "claude CLI not found"

CUR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || die "not a git repository"
[ -n "$BRANCH" ] || BRANCH=$CUR
[ "$CUR" = "$BRANCH" ] || die "run branch $BRANCH is not checked out (on $CUR): git fetch origin $BRANCH && git checkout $BRANCH"
git ls-files --error-unmatch .claude/settings.json >/dev/null 2>&1 || die ".claude/settings.json is not committed"
git diff --quiet HEAD -- .claude/settings.json || die ".claude/settings.json has uncommitted changes: commit the allowlist before launch (the run cannot edit it)"
[ -z "$(git status --porcelain --untracked-files=no)" ] || warn "uncommitted changes in tracked files"
[ -n "${CLAUDE_CODE_OAUTH_TOKEN-}" ] || [ -n "${ANTHROPIC_API_KEY-}" ] || warn "neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set (fine only if this user is logged in)"
TRUST=$("$PY" -c 'import json,os,sys
p=os.path.join(os.path.expanduser("~"),".claude.json")
try: d=json.load(open(p,encoding="utf-8"))
except Exception: print("unknown"); sys.exit()
print(str(bool((d.get("projects") or {}).get(sys.argv[1],{}).get("hasTrustDialogAccepted"))).lower())' "$ROOT")
[ "$TRUST" = true ] || warn "folder trust not recorded for $ROOT (run \`claude\` here once interactively and accept, or set hasTrustDialogAccepted in ~/.claude.json)"
if [ "$SKIP_SELFTEST" = 0 ]; then
    "$PY" tests/selftest.py | tail -n 1 | grep -q "SELFTEST OK" || die "selftest failed: run $PY tests/selftest.py"
fi

ORIGIN=$(git remote get-url origin 2>/dev/null | sed -E 's#(\.git)?$##; s#.*[:/]([^/:]+/[^/]+)$#\1#')
[ -n "$PROMPT" ] || PROMPT="Read BRIEF.md in ${ORIGIN:-this repo} on branch $BRANCH; run it unattended per the run-protocol skill; report via run-report.json."
SID=$("$PY" -c 'import uuid; print(uuid.uuid4())')
SLUG=$(printf '%s' "$ROOT" | sed 's/[^A-Za-z0-9]/-/g')
LOGP="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$SLUG/$SID.jsonl"
HEAD=$(git rev-parse HEAD)
mkdir -p .claude/run-state build/headless
OUT="build/headless/$SID.stream.jsonl"
RESUME="tools/headless/resume.sh --prompt \"<what changed, continue>\"   (kills a live session first; never two at once)"
echo "launch: session $SID on $BRANCH ($HEAD)" >&2
echo "launch: session log $LOGP; stream $OUT" >&2
echo "launch: resume with: $RESUME" >&2
CMD=(claude -p "$PROMPT" --permission-mode acceptEdits --session-id "$SID" --output-format stream-json --verbose)
if [ "$DRY" = 1 ]; then
    printf 'launch: dry run, would run:'; printf ' %q' "${CMD[@]}"; printf '\n'
    exit 0
fi
SESS="tools/headless/session.py"
if [ -f .claude/run-state/session.json ]; then
    "$PY" "$SESS" alive; ALIVE=$?
    if [ "$ALIVE" = 0 ] || [ "$ALIVE" = 3 ]; then
        die "session $("$PY" "$SESS" get session_id) (pid $("$PY" "$SESS" get pid)) is still running: use tools/headless/resume.sh, or stop it first"
    fi
fi
rm -f .claude/run-state/session.json
"$PY" "$SESS" set "session_id=$SID" "started=$(date -u +%Y-%m-%dT%H:%M:%SZ)" "branch=$BRANCH" "head=$HEAD" \
    mode=headless "log_path=$LOGP" "stream=$OUT" launcher=launch.sh resumes=0 || die "cannot write session.json"
export KIT_HEADLESS=1
"${CMD[@]}" >"$OUT" &
CPID=$!
trap 'kill -TERM "$CPID" 2>/dev/null' INT TERM HUP
"$PY" "$SESS" set "pid=$CPID" || warn "cannot record pid $CPID in session.json"
echo "launch: claude pid $CPID (recorded in .claude/run-state/session.json)" >&2
wait "$CPID"
RC=$?
"$PY" "$SESS" denials "$OUT" "$SID"
echo "launch: claude exited $RC; resume with: $RESUME" >&2
exit $RC
