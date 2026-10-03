"""Stop hook: keeps an unattended run going while PLAN.md has open phases.

Lets Claude stop when any of these holds:
  - .claude/HALT exists (create it to end the run cleanly),
  - run-state.json status is blocked (e.g. the kit set it after 2 visual review rounds in a row without a captured
    verdict; blocked_reason says why): the watcher exits 3 and the orchestrator picks up,
  - no open phase is left ("- [ ] **P..." lines in PLAN.md) and every [x] phase passes the close check,
  - the continue budget (kit.json max_continues) is used up,
  - a review is pending and younger than review_timeout_min (review hold: the review's completion notification or a
    scheduled wakeup resumes the session; run 2 got pushed past a running review three times).
A pending review older than the timeout blocks the stop with instructions: stop it, relaunch once, then log unreviewed.
Visual projects (kit.json visual.required): a phase marked [x] that fails the close check (no stored visual-reviewer
pass and not closed below bar, no perf record, a stored verdict not matching its logged hash) blocks the stop until it
is reopened or marked [-]. A visual stage at its review cap without a pass never ends the run: the continue message
says to close it below bar (`tools/review.py close <phase> --known-issues`) and go on. Every decision is logged to
hooks.log.jsonl.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib as K  # noqa: E402

HOOK = "stop_guard"


def block(reason: str, why: str) -> int:
    K.emit({"decision": "block", "reason": reason})
    K.log_hook(HOOK, "blocked", reason=why)
    return 0


def allow(why: str) -> int:
    K.log_hook(HOOK, "allowed", reason=why)
    return 0


def main() -> int:
    try:
        K.read_stdin_json()
    except K.HookInputError as e:
        K.log_hook(HOOK, "input_error", problems=[str(e)])   # input is unused; keeping the run going is the safe side
    cfg = K.config()
    if os.path.exists(K.HALT):
        return allow("HALT")
    rs = K.load_rs()
    if rs.get("status") == "blocked":
        return allow("run blocked: %s" % (rs.get("blocked_reason") or "run-state.json status blocked"))
    if K.counter("continues.txt") >= int(cfg.get("max_continues", 300)):
        return allow("continue budget used up")
    phases = K.open_phases(cfg)
    vis = K.visual(cfg)
    if vis.get("required"):
        bad = [(p, K.close_problems(cfg, p)) for s, p, _ in K.plan_phases(cfg) if s == "x"]
        bad = [(p, e) for p, e in bad if e]
        if bad:
            n = K.counter("continues.txt", bump=True)
            return block((
                "Phase(s) marked [x] without passing the close check: %s. Set each back to [ ] and finish it "
                "(phases close only via `python tools/review.py close <phase>`, below bar via `--known-issues` once a "
                "stage is at its review cap), or mark it [-] with the reason and log it. [continue %d]" % (
                    "; ".join("%s: %s" % (p, " / ".join(e)) for p, e in bad), n)), "close check failed: %s" % [p for p, _ in bad])
    if not phases:
        return allow("no open phase")
    timeout = float(cfg.get("review_timeout_min", 25))
    pending = K.pending_reviews()
    stale = [(rid, age) for rid, age in pending if age >= timeout]
    if stale:
        n = K.counter("continues.txt", bump=True)
        names = ", ".join("%s (%.0f min)" % s for s in stale)
        return block((
            "Review(s) timed out: %s. Stop each reviewer (TaskStop), relaunch it ONCE with a tighter prompt "
            "(`python tools/review.py relaunch <id>`); if it times out again run `python tools/review.py unreviewed <id>` "
            "and log it in PROGRESS.md. Then continue the plan. [continue %d]" % (names, n)), "stale review " + names)
    if pending:
        return allow("review hold: " + ", ".join(r for r, _ in pending))
    hint = ""
    if vis.get("required"):
        pid = phases[0].strip().split(":")[0].split()[0]
        states = {st: K.stage_state(cfg, pid, st) for st in K.phase_stages(cfg, pid)}
        capped = [st for st, s in states.items() if s["capped"]]
        if capped and all(s["capped"] or s["passed"] for s in states.values()):
            hint = (" %s of %s is at its review cap without a pass: do not stop or wait; close the phase below bar with "
                    "honest scores (`python tools/review.py close %s --known-issues`) and start the next phase." % (
                        " and ".join(K.stage_name(s) for s in capped), pid, pid))
        elif capped:
            hint = (" %s of %s is at its review cap without a pass: leave it below bar and go on with the main stage "
                    "(%s-visual-r<N>, its own review budget); the phase closes with --known-issues if needed." % (
                        K.stage_name(capped[0]), pid, pid))
    n = K.counter("continues.txt", bump=True)
    return block((
        "Unattended run in progress (the owner is away; never wait for replies). Open phase: %s.%s Re-read PLAN.md "
        "'Run rules' and the tail of PROGRESS.md, then continue. If truly blocked, follow 'When stuck' (log BLOCKED, "
        "mark the phase [-], move on). Create .claude/HALT only if continuing would damage the repo or overspend. "
        "[continue %d]" % (phases[0].strip(), hint, n)), "open phase " + phases[0].strip())


if __name__ == "__main__":
    sys.exit(K.guarded(HOOK, main))
