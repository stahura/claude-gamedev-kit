"""SessionStart hook (matcher: compact, also startup/resume): re-injects what an unattended run must not forget after
context compaction: the session id, the run rules, open phases, pending reviews, below-bar phases, spend and the
PROGRESS.md tail."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib as K  # noqa: E402

HOOK = "session_start"


def main() -> int:
    try:
        data = K.read_stdin_json()
    except K.HookInputError as e:
        K.log_hook(HOOK, "input_error", problems=[str(e)])
        data = {}   # only re-injects context, so defaults are the safe direction; never block a session start
    cfg = K.config()
    parts = ["[kit] Session %s (id %s). You are in an unattended run of %s (%s). Record the session id in "
             "run-state.json (session_id) and PROGRESS.md if it is not there yet." % (
                 data.get("source", "start"), data.get("session_id", "?"), cfg.get("project", "?"), cfg.get("run", "?"))]
    plan = K.read_text(os.path.join(K.ROOT, cfg.get("plan_file", "PLAN.md")))
    if "## Run rules" in plan:
        rules = plan.split("## Run rules", 1)[1].split("\n## ", 1)[0]
        parts.append("Run rules (from PLAN.md):" + rules.rstrip())
    phases = K.open_phases(cfg)
    parts.append("Open phases: " + (", ".join(p.strip() for p in phases) if phases else "none (write the run report)"))
    pend = K.pending_reviews()
    if pend:
        parts.append("Pending reviews: " + ", ".join("%s %.0f min" % p for p in pend))
    rs = K.load_rs()
    below = [p for p, v in (rs.get("phases") or {}).items() if isinstance(v, dict) and v.get("status") == "done_below_bar"]
    if below:
        parts.append("Closed below bar (known issues in run-state.json, list them in the run report): " + ", ".join(below))
    if rs:
        parts.append("run-state.json spend: " + json.dumps(rs.get("spend", {})))
    tail = K.read_text(os.path.join(K.ROOT, "PROGRESS.md")).splitlines()[-30:]
    if tail:
        parts.append("PROGRESS.md tail:\n" + "\n".join(tail))
    parts.append("Load the run-protocol skill before continuing.")
    K.emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n\n".join(parts)}})
    K.log_hook(HOOK, "injected", source=data.get("source"), session_id=data.get("session_id"))
    return 0


if __name__ == "__main__":
    sys.exit(K.guarded(HOOK, main))
