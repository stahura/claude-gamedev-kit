"""Review bookkeeping for the Stop hook's review hold, for run-state.json, and the phase-close check.

  python tools/review.py start <id> [--agent NAME]   # just before launching a reviewer in the background
  python tools/review.py done <id> --verdict-file F  # after it reports: F holds its final JSON verdict block
  python tools/review.py relaunch <id>               # it timed out once: reset the clock, count the retry
  python tools/review.py unreviewed <id>             # it timed out twice: give up, record it as unreviewed
  python tools/review.py close <phase> [--known-issues]  # close check; marks the phase [x] in PLAN.md if it passes
  python tools/review.py headline                    # below-bar headline at the top of run-report.json
  python tools/review.py list
Ids: <phase>-<area>-r<round>, e.g. P4-terrain-r1. Visual reviews use <phase>-visualA-r<N> (stage A: lighting on
placeholders) or <phase>-visual-r<N> (the main asset stage); their verdicts are captured from the visual-reviewer's
transcript by the SubagentStop hook (.claude/hooks/subagent_stop.py), so `done` refuses them. Verdicts are validated
(kitlib.validate_verdict) and stored in .claude/run-state/reviews/<id>.json; run-state.json gets a summary.

Visual `start` accepts only the next round of the stage (highest started round + 1; no skipping ahead, no reuse, not
while a round is pending) and refuses once the stage has used its cap of *reviewed* rounds (rounds with a captured
verdict; kit.json visual.review_caps: stage A default 3, main stage default 6, per-phase overrides). Two rounds in a
row of one stage without a captured verdict (invalid, unreviewed, abandoned) set run-state.json status blocked with
the reason: the watcher exits 3 and the orchestrator picks up. `start` snapshots the current shots
(docs/shots/<run>/<phase>/final/*.png) into docs/shots/<run>/<phase>/rounds/<id>/, prints the reviewer brief (saved as
review-brief.md) and writes previous-round.md there: the previous round's top problems and open findings, never its
scores (the reviewer scores this round first and writes its blind scores, then opens it; the SubagentStop hook
rejects a verdict that looked earlier or raised a blind score).
`close` refuses a visual phase without a stored visual-reviewer pass (and perf record), and any stored visual verdict
whose sha256 differs from the one the SubagentStop hook logged. A stage at its cap without a pass closes below bar
with `--known-issues` (refused unless the stage has at least one captured verdict): the phase is marked [x]
"(below bar)" and run-state.json records status done_below_bar, known_issues, last_scores and rounds; never a pass.
Later phases then close as usual.
"""
import glob
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".claude", "hooks"))
import kitlib as K  # noqa: E402

extract_verdict = K.extract_verdict
REPORT = os.path.join(K.ROOT, "run-report.json")


def close(pid: str, known_issues: bool) -> int:
    cfg = K.config()
    errs = K.close_problems(cfg, pid, known_issues=known_issues)
    for e in errs:
        print("CLOSE REFUSED: %s: %s" % (pid, e))
    if errs:
        return 1
    rest = next((r for s, p, r in K.plan_phases(cfg) if p == pid), "")
    below = K.below_bar_summary(cfg, pid) if K.is_visual_phase(cfg, pid, rest) else {}
    path = os.path.join(K.ROOT, cfg.get("plan_file", "PLAN.md"))
    plan = K.read_text(path)
    pattern = r"^- \[ \] (\*\*%s\b.*)$" % re.escape(pid)
    repl = (lambda m: "- [x] " + m.group(1) + (" (below bar)" if below else ""))
    new, n = re.subn(pattern, repl, plan, count=1, flags=re.M)
    if n:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
    if below:
        record_below_bar(pid, below)
        for st, b in below.items():
            print("BELOW BAR: %s %s: %s after %d/%d reviewed rounds; open: %s" % (
                pid, st, b["verdict"], b["rounds"], b["cap"], " | ".join(b["top_problems"]) or "-"))
    print("CLOSE OK: %s %s%s" % (pid, "marked [x]" if n else "(already [x] or not open)",
                                 " below bar (known issues recorded in run-state.json; list them in the run report)"
                                 if below else ""))
    return 0


def record_below_bar(pid: str, below: dict) -> None:
    """run-state.json phases[pid] (and run-report.json known_issues + headline when it exists already)."""
    rs = K.load_rs()
    ph = rs.setdefault("phases", {}).setdefault(pid, {})
    # the last stage that ran first: its open problems supersede stage A's (kitlib.below_bar_headline leads with them)
    issues = ["%s %s: %s" % (pid, st, p) for st, b in sorted(below.items(), key=lambda x: x[0] != "main")
              for p in b["top_problems"]]
    ph.update(status="done_below_bar", closed_below_bar=True, known_issues=issues,
              last_scores={st: b["last_scores"] for st, b in below.items()},
              rounds={st: "%d/%d" % (b["rounds"], b["cap"]) for st, b in below.items()},
              last_reviews={st: b["last_review"] for st, b in below.items()}, closed_at=K.utc_now())
    K.save_rs(rs)
    if os.path.exists(REPORT):
        update_report(issues)


def update_report(issues=()) -> str:
    """Put the below-bar headline and phase list first in run-report.json (when it exists) and merge known issues.
    Returns the headline ("" when no phase closed below bar)."""
    headline, below = K.below_bar_headline(K.load_rs())
    if not os.path.exists(REPORT):
        return headline
    try:
        with open(REPORT, encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return headline
    if not isinstance(rep, dict):
        return headline
    ki = rep.setdefault("known_issues", [])
    ki += [i for i in issues if i not in ki]
    head = {"headline": headline, "below_bar": below} if headline else {"below_bar": []}
    if not headline and rep.get("headline", "").startswith("BELOW BAR"):
        rep.pop("headline")
    rep = dict(head, **{k: v for k, v in rep.items() if k not in head})
    with open(REPORT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, indent=2)
    return headline


def previous_round(pid: str, stage: str, n: int) -> str:
    ids = K.visual_ids(pid, stage)
    prev = [r for r in ids if r < n]
    return ids[max(prev)] if prev else ""


def scrub_scores(text: str, items: list) -> str:
    """Remove numeric rubric scores from free text ("depth 3", "light=2", "3/5"): the reviewer must not anchor on
    its previous numbers."""
    names = sorted({i for i in items} | {i.replace("_", " ") for i in items}, key=len, reverse=True)
    rx = r"\b(%s)\b\s*(?:[=:]|is|at|of)?\s*[1-5](?:\s*/\s*5)?\b" % "|".join(re.escape(x) for x in names)
    text = re.sub(rx, r"\1", str(text), flags=re.I)
    text = re.sub(r"\b[1-5]\s*/\s*5\b", "", text)
    return re.sub(r"\bscored?\s+[1-5]\b", "score", text, flags=re.I)


def previous_round_notes(prev: str, rel: str, cfg: dict) -> str:
    """previous-round.md: what the reviewer opens only after scoring this round. Top problems and open findings of
    the previous round, scrubbed of scores; no score matrix, no verdict."""
    items = K.rubric(cfg)
    pv = K.stored_review(prev)
    rec = K.load_rs().get("reviews", {}).get(prev, {})
    lines = ["# Previous round: %s (open this only after you have scored every shot of this round)" % prev,
             "- Shots: %s/rounds/%s/ (compare each shot before/after: better, same or worse)" % (rel, prev)]
    if K.is_captured(pv):
        lines.append("- Its top problems (scores deliberately left out; judge this round on what you see):")
        lines += ["  %d. %s" % (i + 1, scrub_scores(p, items)) for i, p in enumerate(pv.get("top_problems") or [])]
        if not pv.get("top_problems"):
            lines.append("  (none listed)")
        fs = [f for f in pv.get("findings", []) if isinstance(f, dict)]
        if fs:
            lines.append("- Its findings: %s" % json.dumps(
                [{k: scrub_scores(f[k], items) if isinstance(f[k], str) else f[k]
                  for k in ("id", "severity", "scenario", "fix") if k in f} for f in fs]))
    else:
        lines.append("- No verdict stored for it (%s%s): compare the shots only" % (
            rec.get("status", "unknown"), ": " + "; ".join(rec.get("problems", [])) if rec.get("problems") else ""))
    lines.append("- Check whether those problems were fixed. Do not reverse your own previous request unless that "
                 "change made the shot worse; say so explicitly. Add \"vs_previous\" to your JSON verdict (and what "
                 "still separates each shot from the reference). This comparison can lower a blind score for a flaw "
                 "you can name, never raise one: \"better than last round\" is not \"close to the reference\".")
    return "\n".join(lines) + "\n"


def start_visual(rid: str, cfg: dict) -> int:
    """Order, streak and cap checks, shot snapshot and reviewer brief for a visual review id. Returns an exit code
    (0 = start)."""
    pid, stage, n = K.VISUAL_ID.match(rid).groups()
    n = int(n)
    name = K.stage_name(stage)
    bad = K.calibration_config_problems(cfg)
    if bad:
        print("START REFUSED: %s (the owner fixes kit.json between runs; log it in PROGRESS.md)" % "; ".join(bad))
        return 2
    blocked = K.check_failed_streak(pid, stage, "review.py")
    if blocked:
        print("START REFUSED: the run is blocked: %s. run-state.json status is now blocked; log it in PROGRESS.md and "
              "end the session (the Stop hook lets it end); the orchestrator picks up." % blocked)
        return 3
    s = K.stage_state(cfg, pid, stage)
    if s["pending"]:
        print("START REFUSED: %s still pending: wait for its verdict (or relaunch / unreviewed after a timeout)"
              % ", ".join(s["pending"]))
        return 2
    if n != s["next"]:
        print("START REFUSED: %s is not the next round of the %s of %s: the next round is %s-visual%s-r%d (%s). "
              "Rounds start in order; never skip ahead or reuse a round number." % (
                  rid, name, pid, pid, stage, s["next"],
                  "no round started yet" if not s["started"] else "r%d was the last one started" % s["started"]))
        return 2
    cap = s["cap"]
    if s["rounds"] >= cap and not s["passed"]:
        print("START REFUSED: the %s of %s has used its cap of %d reviewed rounds (kit.json visual.review_caps). Do "
              "not run more rounds: %s" % (name, pid, cap,
                                           "the stage stays below bar; go on with the main stage (%s-visual-r...) and close the "
                                           "phase with `python tools/review.py close %s --known-issues`" % (pid, pid)
                                           if stage == "A" and len(K.phase_stages(cfg, pid)) > 1 else
                                           "close the phase below bar with honest scores: `python tools/review.py close %s "
                                           "--known-issues`, log the known issues, continue the run." % pid))
        return 3
    rel = K.shots_dir(cfg, pid)
    base = os.path.join(K.ROOT, *rel.split("/"))
    final, snap = os.path.join(base, "final"), os.path.join(base, "rounds", rid)
    os.makedirs(snap, exist_ok=True)
    pngs = sorted(glob.glob(os.path.join(final, "*.png")))
    for p in pngs:
        shutil.copy2(p, snap)
    if not pngs:
        print("WARNING: no PNGs in %s/final/ to snapshot: render the shot set there before the review" % rel)
    prev = previous_round(pid, stage, n)
    lines = ["# Reviewer brief: %s (%s of %s, round %d; %d of %d reviewed rounds used)" % (
                 rid, name, pid, n, s["rounds"], cap),
             "- This round's shots (review these; open every PNG): %s/rounds/%s/ (snapshot of %s/final/)" % (rel, rid, rel)]
    cal = K.calibration_cfg(cfg)
    if cal:
        lines.append("- Calibration first: score the reference image(s) themselves on the rubric, then judge each "
                     "shot's whole frame (overall style, scene density, composition and framing) against them, at the "
                     "reference's display size. A style or density mismatch caps %s at %d (\"calibration\" in your "
                     "JSON verdict)." % (cal["cap_item"] or "the style item", cal["cap"]))
    if not stage and n >= cap:
        lines.append("- Final round of the main stage: in run r2 the in-run reviewer was lenient by ~12 of 21 cells "
                     "against an external blind score (19/21 vs 7/21 at 4+). Score as the external scorer would; an "
                     "in-run pass here stays provisional until an external blind score.")
    notes = os.path.join(snap, "previous-round.md")
    if prev:
        with open(notes, "w", encoding="utf-8", newline="\n") as f:
            f.write(previous_round_notes(prev, rel, cfg))
        lines.append("- Previous round: %s. **First** score every shot of this round on its own and write the blind "
                     "scores block (```json {\"blind_scores\": {shot: {item: score}}}```). **Only then** open "
                     "%s/rounds/%s/previous-round.md (its top problems, no scores) and the previous shots in "
                     "%s/rounds/%s/, compare, and add \"vs_previous\" to your JSON verdict; final scores may only "
                     "stay or go down from the blind ones." % (prev, rel, rid, rel, prev))
    else:
        if os.path.exists(notes):
            os.remove(notes)
        lines.append("- Previous round: none (first round of this stage)")
    brief = "\n".join(lines) + "\n"
    with open(os.path.join(snap, "review-brief.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(brief)
    print(brief, end="")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    rid = sys.argv[2] if len(sys.argv) > 2 else ""
    os.makedirs(K.REVIEWS, exist_ok=True)
    pend = os.path.join(K.REVIEWS, rid + ".pending")
    vm = K.VISUAL_ID.match(rid)
    if cmd == "start":
        cfg = K.config()
        if vm and K.visual(cfg).get("required"):
            rc = start_visual(rid, cfg)
            if rc:
                return rc
        open(pend, "w").close()
        K.set_review(rid, status="pending", attempts=1)
    elif cmd == "relaunch":
        open(pend, "w").close()   # fresh mtime = fresh timeout
        K.set_review(rid, status="pending", attempts=2)
    elif cmd == "unreviewed":
        if os.path.exists(pend):
            os.remove(pend)
        K.set_review(rid, status="unreviewed")
        blocked = K.check_failed_streak(vm.group(1), vm.group(2), "review.py") if vm else ""
        if blocked:
            print("RUN BLOCKED: %s. run-state.json status is blocked; log it in PROGRESS.md and end the session." % blocked)
            return 3
    elif cmd == "done":
        if vm:
            print("%s is a visual review: its verdict is captured from the visual-reviewer by the SubagentStop hook, "
                  "never supplied by the builder" % rid, file=sys.stderr)
            return 2
        if "--verdict-file" not in sys.argv:
            print("done needs --verdict-file", file=sys.stderr)
            return 2
        with open(sys.argv[sys.argv.index("--verdict-file") + 1], encoding="utf-8") as f:
            v = extract_verdict(f.read())
        errs = K.validate_verdict(v, rid, K.config())
        if errs:
            raise SystemExit("verdict rejected: " + "; ".join(errs))
        K.store_review(rid, v)
    elif cmd == "close":
        return close(rid, "--known-issues" in sys.argv)
    elif cmd == "headline":
        h = update_report()
        print(h or "no phase closed below bar")
    elif cmd == "list":
        print(json.dumps({"pending": K.pending_reviews(), "reviews": K.load_rs().get("reviews", {})}, indent=2))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
