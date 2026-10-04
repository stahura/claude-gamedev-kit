"""Shared helpers for the kit's hooks and tools (Python 3.8+, Windows and Linux, stdlib only)."""
import hashlib
import json
import os
import re
import sys
import time
import traceback

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(ROOT, ".claude", "run-state")
REVIEWS = os.path.join(STATE, "reviews")
PERF = os.path.join(STATE, "perf")
HALT = os.path.join(ROOT, ".claude", "HALT")
HOOK_LOG = os.path.join(STATE, "hooks.log.jsonl")

# Visual review ids: <phase>-visualA-r<N> (stage A: lighting/placeholders) or <phase>-visual-r<N> (main asset stage).
VISUAL_ID = re.compile(r"^(P\d+)-visual(A?)-r(\d+)$")
DEFAULT_RUBRIC = ["silhouette", "depth", "light", "palette", "cohesion", "style_match", "secondary_detail", "ground",
                  "life"]
DEFAULT_STAGE_A = ["silhouette", "depth", "light", "palette"]
DEFAULT_CAPS = {"stage_a": 3, "default": 6}
# Rounds in a row of one stage that ended without a stored verdict (invalid, unreviewed, abandoned) before the run is
# set to status blocked: the reviewer or the capture is broken, and more rounds would only burn the budget.
FAILED_STREAK_LIMIT = 2
PHASE_LINE = re.compile(r"^- \[([ x-])\] \*\*(P\d+)\b[^*]*\*\*(.*)$", re.M)


def config() -> dict:
    try:
        with open(os.path.join(ROOT, "kit.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class HookInputError(ValueError):
    """Hook stdin was empty, undecodable, not JSON, or not a JSON object."""


def read_stdin_json() -> dict:
    """Parse the hook's stdin as a JSON object. Raises HookInputError (fail closed) instead of returning {}.

    Reads raw bytes: Windows hosts may write UTF-8 with a BOM (or UTF-16), which text-mode stdin cannot parse."""
    try:
        raw = sys.stdin.buffer.read()
    except (OSError, ValueError, AttributeError) as e:
        raise HookInputError("cannot read stdin: %s" % e)
    if raw.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16"
    else:
        enc = "utf-8"
    try:
        text = raw.decode(enc)
    except UnicodeDecodeError:
        raise HookInputError("undecodable bytes")
    text = text.lstrip("﻿").strip()
    if not text:
        raise HookInputError("empty input")
    try:
        data = json.loads(text)
    except ValueError:
        raise HookInputError("invalid JSON")
    if not isinstance(data, dict):
        raise HookInputError("top level is not a JSON object")
    return data


def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def file_sha256(path: str) -> str:
    """sha256 hex of a file's bytes, "" when unreadable."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def open_phases(cfg: dict) -> list:
    plan = read_text(os.path.join(ROOT, cfg.get("plan_file", "PLAN.md")))
    rx = cfg.get("open_phase_regex", r"^- \[ \] \*\*(P\d+[^*]*)\*\*")
    return re.findall(rx, plan, flags=re.M)


def pending_reviews() -> list:
    """[(id, age_minutes)] for every .claude/run-state/reviews/<id>.pending file."""
    out = []
    if os.path.isdir(REVIEWS):
        now = time.time()
        for f in os.listdir(REVIEWS):
            if f.endswith(".pending"):
                age = (now - os.path.getmtime(os.path.join(REVIEWS, f))) / 60.0
                out.append((f[:-8], age))
    return out


def counter(name: str, bump: bool = False) -> int:
    os.makedirs(STATE, exist_ok=True)
    path = os.path.join(STATE, name)
    try:
        n = int(read_text(path).strip() or 0)
    except ValueError:
        n = 0
    if bump:
        n += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(n))
    return n


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- hook log: one JSON line per hook call in .claude/run-state/hooks.log.jsonl ---

def log_hook(hook: str, outcome: str, **kv) -> None:
    """Append one JSON line (ts, hook, outcome, extra fields) to the hook log. Never raises."""
    rec = {"ts": utc_now(), "hook": hook, "outcome": outcome}
    rec.update({k: v for k, v in kv.items() if v not in (None, "", [], {})})
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(HOOK_LOG, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, default=str)[:20000] + "\n")
    except OSError:
        pass


def logged_verdict_hashes() -> dict:
    """{review id: sha256} of the last verdict file the SubagentStop hook logged as stored for each id."""
    out = {}
    try:
        with open(HOOK_LOG, encoding="utf-8") as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                if (isinstance(e, dict) and e.get("hook") == "subagent_stop" and e.get("outcome") == "stored"
                        and e.get("review_id") and e.get("sha256")):
                    out[e["review_id"]] = e["sha256"]
    except OSError:
        pass
    return out


def guarded(hook: str, main, on_error=None) -> int:
    """Run a hook's main(). An exception is logged (outcome error) and printed to stderr, never silently swallowed;
    on_error(exc) may emit the hook's fail-safe output (the guard denies). Returns the exit code."""
    try:
        return main() or 0
    except SystemExit:
        raise
    except BaseException as e:  # noqa: B902 - a killed or crashing hook is logged too
        tb = traceback.format_exc()
        log_hook(hook, "error", problems=[("%s: %s" % (type(e).__name__, e))[:500]], traceback=tb[-2000:])
        sys.stderr.write(tb)
        if on_error is not None:
            try:
                on_error(e)
            except Exception:
                pass
        return 0


# --- run-state.json and stored reviews ---

def load_rs() -> dict:
    try:
        with open(os.path.join(ROOT, "run-state.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_rs(rs: dict) -> None:
    with open(os.path.join(ROOT, "run-state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rs, f, indent=2)


def set_review(rid: str, **kv) -> None:
    rs = load_rs()
    rs.setdefault("reviews", {}).setdefault(rid, {}).update(kv)
    save_rs(rs)


def block_run(reason: str, source: str) -> None:
    """Set run-state.json status blocked with the reason (the watcher exits 3, the orchestrator picks up; the Stop
    hook lets the session end). Idempotent."""
    rs = load_rs()
    if rs.get("status") == "blocked" and rs.get("blocked_reason") == reason:
        return
    now = utc_now()
    rs.update(status="blocked", blocked_reason=reason, blocked_at=now, updated=now)
    save_rs(rs)
    log_hook(source, "run_blocked", reason=reason)


def record_invalid(rid: str, problems: list) -> str:
    """The reviewer ended without a storable verdict: drop its .pending marker and record status invalid (the builder
    sees it in run-state.json and starts a new round). Returns the blocked reason when this was the second failed
    round in a row of the stage (run-state.json is then status blocked), else ""."""
    pend = os.path.join(REVIEWS, rid + ".pending")
    if os.path.exists(pend):
        os.remove(pend)
    set_review(rid, status="invalid", problems=list(problems)[:10])
    m = VISUAL_ID.match(rid)
    return check_failed_streak(m.group(1), m.group(2), "subagent_stop") if m else ""


def extract_verdict(text: str) -> dict:
    """The last ```json block (or bare object) containing "verdict"."""
    blocks = [b.split("```", 1)[0] for b in text.split("```json")[1:]]
    for key in ('{"verdict"', '{"review_id"'):
        if key in text:
            blocks.append(text[text.rfind(key):].split("```", 1)[0])
    for b in reversed(blocks):
        try:
            v = json.loads(b.strip())
            if isinstance(v, dict) and "verdict" in v:
                return v
        except ValueError:
            continue
    raise ValueError("no JSON verdict block found")


def store_review(rid: str, v: dict) -> str:
    """Store the verdict in reviews/<id>.json and summarise it in run-state.json. Returns the file's sha256."""
    os.makedirs(REVIEWS, exist_ok=True)
    path = os.path.join(REVIEWS, rid + ".json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(v, f, indent=2)
    pend = os.path.join(REVIEWS, rid + ".pending")
    if os.path.exists(pend):
        os.remove(pend)
    blocking = [x.get("id") for x in v.get("findings", []) if isinstance(x, dict) and x.get("blocking")]
    set_review(rid, status="done", verdict=v["verdict"], findings=len(v.get("findings", [])), blocking_open=blocking)
    return file_sha256(path)


def stored_review(rid: str) -> dict:
    try:
        with open(os.path.join(REVIEWS, rid + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# --- visual pipeline: rubric, shot set, verdict validation, review caps, phase close ---

def visual(cfg: dict) -> dict:
    return cfg.get("visual") or {}


def rubric(cfg: dict) -> list:
    return list(visual(cfg).get("rubric") or DEFAULT_RUBRIC)


def stage_a_items(cfg: dict) -> list:
    return list(visual(cfg).get("stage_a_items") or DEFAULT_STAGE_A)


def min_score(cfg: dict, stage_a: bool = False) -> int:
    """Pass floor: visual.rubric_min_score (default 4); stage A uses visual.stage_a_min_score when set."""
    vis = visual(cfg)
    floor = vis.get("rubric_min_score", 4)
    return vis.get("stage_a_min_score", floor) if stage_a else floor


def stage_name(stage: str) -> str:
    return "stage A" if stage == "A" else "main stage"


def review_cap(cfg: dict, pid: str, stage: str) -> int:
    """Max reviewed rounds (rounds with a stored verdict) for one stage of a phase (stage 'A' = <phase>-visualA-r<N>,
    '' = <phase>-visual-r<N>).

    visual.review_caps: {"stage_a": 3, "default": 6, "phases": {"P1": {"A": 3, "": 8}, "P3": 5}}; a bare number for
    a phase is its main-stage cap. Main stage falls back to the retired visual.look_fix_max_iterations, then 6."""
    vis = visual(cfg)
    caps = vis.get("review_caps") or {}
    per = (caps.get("phases") or {}).get(pid)
    if isinstance(per, dict):
        for k in ((stage,) if stage else ("", "main")):
            if isinstance(per.get(k), int):
                return per[k]
    elif isinstance(per, int) and not stage:
        return per
    if stage:
        return int(caps.get("stage_a", DEFAULT_CAPS["stage_a"]))
    if isinstance(caps.get("default"), int):
        return caps["default"]
    if isinstance(vis.get("look_fix_max_iterations"), int):
        return vis["look_fix_max_iterations"]
    return DEFAULT_CAPS["default"]


def on_cap(cfg: dict) -> str:
    """What a stage at its cap without a pass does: proceed_with_known_issues (default: close it below bar) or
    mark_skipped (the phase is marked [-] with its known issues). Neither halts the run."""
    return visual(cfg).get("on_cap", "proceed_with_known_issues")


def visual_ids(pid: str, stage: str) -> dict:
    """{round: id} of every visual review started for this phase and stage (run-state, stored, pending)."""
    names = set(load_rs().get("reviews", {}))
    if os.path.isdir(REVIEWS):
        names |= {f.rsplit(".", 1)[0] for f in os.listdir(REVIEWS) if f.endswith((".json", ".pending"))}
    out = {}
    for n in names:
        m = VISUAL_ID.match(n)
        if m and m.group(1) == pid and m.group(2) == stage:
            out[int(m.group(3))] = n
    return out


def is_captured(v: dict) -> bool:
    """A real visual verdict: stored by the SubagentStop hook (never by the builder)."""
    return bool(v) and v.get("captured_by") == "subagent_stop"


def stage_rounds(pid: str, stage: str) -> list:
    """[(round, id, state)] in round order; state: verdict (a captured verdict is stored), pending (.pending marker),
    failed (ended without a stored verdict: invalid, unreviewed or abandoned)."""
    ids = visual_ids(pid, stage)
    pend = {rid for rid, _ in pending_reviews()}
    out = []
    for n in sorted(ids):
        rid = ids[n]
        st = "pending" if rid in pend else "verdict" if is_captured(stored_review(rid)) else "failed"
        out.append((n, rid, st))
    return out


def failed_streak(pid: str, stage: str) -> list:
    """Ids of the trailing rounds of the stage that ended without a stored verdict (most recent last)."""
    streak = []
    for _, rid, st in stage_rounds(pid, stage):
        streak = streak + [rid] if st == "failed" else []
    return streak


def check_failed_streak(pid: str, stage: str, source: str) -> str:
    """FAILED_STREAK_LIMIT rounds in a row without a stored verdict -> run-state.json status blocked; returns the
    reason ("" when not blocked)."""
    streak = failed_streak(pid, stage)
    if len(streak) < FAILED_STREAK_LIMIT:
        return ""
    rs = load_rs().get("reviews", {})
    why = ", ".join("%s (%s)" % (r, (rs.get(r) or {}).get("status", "no verdict")) for r in streak[-FAILED_STREAK_LIMIT:])
    reason = ("visual review not captured for %d consecutive rounds of the %s of %s: %s. The reviewer or the verdict "
              "capture is broken (see .claude/run-state/hooks.log.jsonl); more rounds would only burn the budget"
              % (len(streak), stage_name(stage), pid, why))
    block_run(reason, source)
    return reason


def shot_set(cfg: dict):
    """(version, [shot names]) of the current shot set; raises ValueError when unreadable."""
    path = os.path.join(ROOT, visual(cfg).get("shot_set", "docs/shots/shots.json"))
    try:
        with open(path, encoding="utf-8-sig") as f:
            s = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError("shot set unreadable: %s (%s)" % (path, e))
    names = [sh.get("name") for sh in s.get("shots") or [] if isinstance(sh, dict) and sh.get("name")]
    if not isinstance(s.get("version"), int) or not names:
        raise ValueError("shot set needs an integer version and named shots: " + path)
    return s["version"], names


def shots_dir(cfg: dict, pid: str) -> str:
    """docs/shots/<run>/<phase> (relative to the project), the parent of final/, changes/ and rounds/."""
    base = visual(cfg).get("shots_dir", "docs/shots")
    return "/".join([base.rstrip("/"), cfg.get("run", "r1"), pid])


def calibration_cfg(cfg: dict) -> dict:
    """kit.json visual.calibration {required, cap_item, cap}: the reviewer scores the reference first and caps the
    style item of every shot whose overall style or scene density does not match it. {} when not configured."""
    c = visual(cfg).get("calibration")
    if not isinstance(c, dict):
        return {}
    cap = c.get("cap", 3)
    return {"required": bool(c.get("required")), "cap_item": str(c.get("cap_item") or ""),
            "cap": cap if isinstance(cap, int) and not isinstance(cap, bool) else 3}


def calibration_config_problems(cfg: dict) -> list:
    """kit.json visual.calibration that cannot work: required (or a cap_item set) but cap_item is not an item of the
    effective rubric, so a "mismatch" would cap nothing. `review.py start` refuses visual rounds on it."""
    c = calibration_cfg(cfg)
    if not c or not (c["required"] or c["cap_item"]):
        return []
    items = rubric(cfg)
    if c["cap_item"] in items:
        return []
    return ["kit.json visual.calibration.cap_item %r is not an item of visual.rubric (%s): a style/density mismatch "
            "would cap nothing. Set cap_item to the project's style item (e.g. \"style_match\" or \"stylization\")"
            % (c["cap_item"], ", ".join(items))]


def calibration_problems(v: dict, cfg: dict, names: list) -> list:
    """Loose check of a visual verdict's "calibration" {"reference": {item: score}, "shots": {shot: "match: why" |
    "mismatch: why"}}: present when required, a verdict per shot, and the cap on the style item of mismatched shots.
    A cap_item outside the rubric is an error, never a silent no-op."""
    c = calibration_cfg(cfg)
    errs = calibration_config_problems(cfg)
    cal = v.get("calibration")
    if cal is None:
        return errs + (["calibration missing: score the reference image itself on the rubric first, then judge each "
                        "shot's overall style and scene density against it (\"calibration\": {\"reference\": {...}, "
                        "\"shots\": {shot: \"match|mismatch: why\"}})"] if c.get("required") else [])
    if not isinstance(cal, dict) or not isinstance(cal.get("shots", {}), dict):
        return errs + ["calibration must be an object with \"reference\" (item -> score) and \"shots\" (shot -> "
                       "match|mismatch: why)"]
    shots = cal.get("shots", {})
    if c.get("required"):
        if not isinstance(cal.get("reference"), dict) or not cal["reference"]:
            errs.append("calibration.reference: score the reference image on the rubric before the shots")
        errs += ["calibration.shots: no style/density judgement for shot %s" % s for s in names
                 if not str(shots.get(s, "")).strip().lower().startswith(("match", "mismatch"))]
    item, cap = c.get("cap_item"), c.get("cap", 3)
    for s, j in shots.items():
        n = ((v.get("scores") or {}).get(s) or {}).get(item) if item else None
        if str(j).strip().lower().startswith("mismatch") and isinstance(n, int) and not isinstance(n, bool) and n > cap:
            errs.append("shot %s: style/density mismatch with the reference caps %s at %d, got %d" % (s, item, cap, n))
    return errs


def validate_verdict(v, rid: str, cfg: dict) -> list:
    """Reasons the verdict cannot be stored (empty = valid). Visual ids need the full score matrix: every shot in the
    current shot set x every rubric item; "n/a" only on stage-A ids for items outside visual.stage_a_items; the
    current shot_set_version; "pass" only when every scored item meets the floor (min_score)."""
    if not isinstance(v, dict):
        return ["verdict is not a JSON object"]
    errs = ["verdict lacks %r" % k for k in ("verdict", "findings") if k not in v]
    if v.get("verdict") not in ("pass", "fix_needed", "block"):
        errs.append("verdict must be pass, fix_needed or block")
    if not isinstance(v.get("findings", []), list):
        errs.append("findings must be a list")
    if "vs_previous" in v and not isinstance(v["vs_previous"], (dict, list, str)):
        errs.append("vs_previous must be an object (shot -> better|same|worse + why), a list or a string")
    m = VISUAL_ID.match(rid)
    floor = min_score(cfg, bool(m and m.group(2) == "A"))
    scores = v.get("scores") or {}
    if not isinstance(scores, dict):
        return errs + ["scores must be an object"]
    low = []
    if not m:
        low = ["%s %s=%s" % (s, i, n) for s, items in scores.items() if isinstance(items, dict)
               for i, n in items.items() if isinstance(n, int) and n < floor]
    else:
        stage_a = m.group(2) == "A"
        items = rubric(cfg)
        scored = [i for i in items if i in stage_a_items(cfg)] if stage_a else items
        try:
            version, names = shot_set(cfg)
        except ValueError as e:
            return errs + [str(e)]
        if v.get("shot_set_version") != version:
            errs.append("shot_set_version %r is not the current shot set version %d" % (v.get("shot_set_version"), version))
        errs += ["score for unknown shot %s" % s for s in scores if s not in names]
        for shot in names:
            got = scores.get(shot)
            if not isinstance(got, dict):
                errs.append("no scores for shot %s" % shot)
                continue
            errs += ["shot %s: unknown rubric item %s" % (shot, i) for i in got if i not in items]
            for i in items:
                n = got.get(i)
                if n == "n/a":
                    if i in scored:
                        errs.append("shot %s: n/a not allowed for %s%s" % (shot, i, " in stage A" if stage_a else ""))
                elif isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 5:
                    errs.append("shot %s: %s needs a score 1-5, got %r" % (shot, i, n))
                elif i in scored and n < floor:
                    low.append("%s %s=%s" % (shot, i, n))
        if v.get("verdict") == "pass" and v.get("incomplete"):
            errs.append("an incomplete review cannot pass")
        errs += calibration_problems(v, cfg, names)
    if v.get("verdict") == "pass" and low:
        errs.append("verdict pass but rubric scores below %s: %s" % (floor, ", ".join(low)))
    return errs


def plan_phases(cfg: dict) -> list:
    """[(status ' '|'x'|'-', phase id, rest of the line)] in PLAN.md order."""
    return PHASE_LINE.findall(read_text(os.path.join(ROOT, cfg.get("plan_file", "PLAN.md"))))


def _num(pid: str) -> int:
    return int(pid[1:])


def is_visual_phase(cfg: dict, pid: str, rest: str = "") -> bool:
    vis = visual(cfg)
    return bool(vis.get("required")) and (pid == vis.get("lock_phase", "P1") or "[visual]" in rest)


def latest_visual(pid: str, stage: str) -> dict:
    """The stored visual verdict with the highest round for this phase and stage ('A' or '')."""
    best, out = -1, {}
    if os.path.isdir(REVIEWS):
        for f in os.listdir(REVIEWS):
            m = VISUAL_ID.match(f[:-5]) if f.endswith(".json") else None
            if m and m.group(1) == pid and m.group(2) == stage and int(m.group(3)) > best:
                try:
                    with open(os.path.join(REVIEWS, f), encoding="utf-8") as fh:
                        best, out = int(m.group(3)), json.load(fh)
                except (OSError, ValueError):
                    continue
    return out


def phase_stages(cfg: dict, pid: str) -> list:
    """Visual stages a phase is gated on: the style slice (lock phase) has stage A and the main stage."""
    return ["A", ""] if pid == visual(cfg).get("lock_phase", "P1") else [""]


def stage_state(cfg: dict, pid: str, stage: str) -> dict:
    """passed / pending / rounds (reviewed: a captured verdict is stored) / started (highest round number) / next
    (the only round `review.py start` accepts) / failed (trailing rounds without a verdict) / cap / capped (reviewed
    rounds >= cap, nothing pending, no pass) for one stage. Only reviewed rounds count against the cap."""
    v = latest_visual(pid, stage)
    rounds = stage_rounds(pid, stage)
    pend = [rid for _, rid, st in rounds if st == "pending"]
    reviewed = sum(1 for _, _, st in rounds if st == "verdict")
    started = rounds[-1][0] if rounds else 0
    cap = review_cap(cfg, pid, stage)
    passed = v.get("verdict") == "pass" and is_captured(v)
    return {"latest": v, "passed": passed, "pending": pend, "rounds": reviewed, "started": started,
            "next": started + 1, "failed": failed_streak(pid, stage), "cap": cap,
            "capped": not passed and not pend and reviewed >= cap}


def verdict_integrity_problems(pid: str) -> list:
    """Stored visual verdicts of phase pid whose sha256 does not match the one the SubagentStop hook logged when it
    stored them (edited, forged or copied in by hand; the log line is missing or different)."""
    logged = logged_verdict_hashes()
    errs = []
    if not os.path.isdir(REVIEWS):
        return errs
    for f in sorted(os.listdir(REVIEWS)):
        m = VISUAL_ID.match(f[:-5]) if f.endswith(".json") else None
        if not m or m.group(1) != pid:
            continue
        rid = f[:-5]
        sha = file_sha256(os.path.join(REVIEWS, f))
        if rid not in logged:
            errs.append("stored verdict %s has no sha256 logged by the SubagentStop hook in hooks.log.jsonl: it was not "
                        "stored by the hook (written or copied by hand?); delete it and run a real review round" % rid)
        elif logged[rid] != sha:
            errs.append("stored verdict %s was changed after the SubagentStop hook stored it (sha256 %s, logged %s): "
                        "delete it and run a real review round" % (rid, sha[:12], logged[rid][:12]))
    return errs


def close_problems(cfg: dict, pid: str, known_issues: bool = False) -> list:
    """Why phase pid may not be marked [x] (empty = it may). A stage at its cap without a pass closes below bar only
    with known_issues (review.py close --known-issues) or when run-state already records the phase done_below_bar,
    and only with at least one real (captured) verdict for that stage. Stored verdicts must match their logged hash."""
    vis = visual(cfg)
    if not vis.get("required"):
        return []
    phases = plan_phases(cfg)
    lock = vis.get("lock_phase", "P1")
    status = {p: s for s, p, _ in phases}
    errs = []
    if pid != lock and lock in status and _num(pid) > _num(lock) and status[lock] == " ":
        errs.append("the style slice %s is still open: close it first (a pass, or --known-issues once its stages are "
                    "at their caps) or mark it [-]" % lock)
    rest = next((r for s, p, r in phases if p == pid), "")
    if not is_visual_phase(cfg, pid, rest):
        return errs
    errs += verdict_integrity_problems(pid)
    below = known_issues or (load_rs().get("phases", {}).get(pid) or {}).get("status") == "done_below_bar"
    for st in phase_stages(cfg, pid):
        s = stage_state(cfg, pid, st)
        if s["passed"]:
            continue
        rid = "%s-visual%s-r<N>" % (pid, st)
        if s["pending"]:
            errs.append("review %s still pending: wait for its verdict" % ", ".join(s["pending"]))
        elif below and not s["rounds"]:
            errs.append("--known-issues refused for the %s of %s: no real visual-reviewer verdict is stored for it "
                        "(%d round(s) started, none captured). A below-bar close needs at least one reviewed round: "
                        "run `python tools/review.py start %s-visual%s-r%d` and a visual-reviewer" % (
                            stage_name(st), pid, s["started"], pid, st, s["next"]))
        elif not s["capped"]:
            errs.append("no stored visual-reviewer pass for %s (latest: %s; reviewed round %d of %d)" % (
                rid, s["latest"].get("verdict", "none"), s["rounds"], s["cap"]))
        elif on_cap(cfg) == "mark_skipped":
            errs.append("%s of %s hit its cap (%d/%d reviewed rounds) without a pass and visual.on_cap is mark_skipped: "
                        "mark the phase [-] with its known issues and continue the run" % (
                            stage_name(st), pid, s["rounds"], s["cap"]))
        elif not below:
            errs.append("%s of %s hit its cap (%d/%d reviewed rounds) without a pass: close it below bar with "
                        "`python tools/review.py close %s --known-issues` (honest scores, the run continues)" % (
                            stage_name(st), pid, s["rounds"], s["cap"], pid))
    perf = vis.get("perf") or {}
    if any(perf.get(k) is not None for k in ("min_avg_fps", "min_low1_fps")):
        try:
            with open(os.path.join(PERF, pid + ".json"), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            rec = {}
        if not rec.get("ok"):
            errs.append("no passing perf record for %s (python tools/perf_gate.py --phase %s <bench log>)" % (pid, pid))
    return errs


def below_bar_summary(cfg: dict, pid: str) -> dict:
    """{stage: {rounds, cap, verdict, last_scores, top_problems}} for each stage of pid closed without a pass."""
    out = {}
    for st in phase_stages(cfg, pid):
        s = stage_state(cfg, pid, st)
        if s["passed"]:
            continue
        v = s["latest"]
        probs = [str(p) for p in v.get("top_problems") or []]
        if not probs:
            probs = [str(f.get("scenario", "")) for f in v.get("findings") or [] if isinstance(f, dict) and f.get("blocking")]
        if not v:
            probs = ["no stored visual-reviewer verdict for any round (invalid or unreviewed)"]
        out["stage_a" if st == "A" else "main"] = {
            "rounds": s["rounds"], "cap": s["cap"], "verdict": v.get("verdict", "none"),
            "last_review": v.get("review_id", ""), "last_scores": v.get("scores", {}),
            "top_problems": probs[:5]}
    return out


def below_bar_headline(rs: dict) -> tuple:
    """(headline, [phase ids]) for every phase run-state.json records done_below_bar; ("", []) when none."""
    phases = rs.get("phases") or {}
    below = [p for p, v in phases.items() if isinstance(v, dict) and v.get("status") == "done_below_bar"]
    if not below:
        return "", []
    parts = []
    for p in below:
        ph = phases[p]
        rounds = ", ".join("%s %s" % (k, r) for k, r in (ph.get("rounds") or {}).items())
        issues = [str(i) for i in ph.get("known_issues") or []]
        # lead with the last stage that ran (main): its open problems supersede stage A's, which r2's headline
        # repeated although the main stage had fixed most of them
        main = [i for i in issues if i.startswith("%s main:" % p)]
        lead = (main or issues)[:3]
        gap = composition_gap(ph, issues)
        if gap:
            lead = [gap] + lead
        parts.append("%s (%s)%s" % (p, rounds or "rounds unknown", ": " + "; ".join(lead) if lead else ""))
    return "BELOW BAR: %d visual phase(s) closed without a reviewer pass: %s" % (len(below), " | ".join(parts)), below


COMPOSITION_WORDS = re.compile(r"\b(composition|framing|density|dressing|under-dressed|bare|coverage|share of the frame)\b", re.I)


def composition_gap(ph: dict, issues: list) -> str:
    """'composition/style gap vs the reference ...' when the last main-stage scores have the calibration item
    (kit.json visual.calibration.cap_item) at or below its cap on a shot, or a known issue names framing or density."""
    c = calibration_cfg(config())
    item, cap = c.get("cap_item"), c.get("cap", 3)
    scores = (ph.get("last_scores") or {}).get("main") or {}
    low = sorted(s for s, row in scores.items() if isinstance(row, dict) and item and
                 isinstance(row.get(item), int) and row[item] <= cap)
    named = [i for i in issues if COMPOSITION_WORDS.search(i)]
    if not low and not named:
        return ""
    return "composition/style gap vs the reference%s" % (" (%s at or below the calibration cap on %s)" % (
        item, ", ".join(low)) if low else "")
