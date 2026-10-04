"""Self-test for the kit: runs every hook and tools/paid.py, review.py, perf_gate.py, art_gate.py and init_project.py in
throwaway copies of the project (a fake paid service, sample reviewer transcripts, throwaway git repos for the art
gate's tags and the heartbeat branch, a fake run for the watcher). Stdlib + git only (bash for the watcher checks);
works on Windows and Linux, in the kit and in an initialised project (it also runs itself in an
`init_project.py --visual` copy).  Usage: python tests/selftest.py -> "SELFTEST OK (n checks)"
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NESTED = os.environ.get("KIT_SELFTEST_NESTED") == "1"
# Root files init_project.py generates (never overwritten by it) and live-run state: a copy of an initialised project
# drops them so the checks start from the template state.
GENERATED = ("PLAN.md", "PROGRESS.md", "CLAUDE.md", "BRIEF.md", "ART-BIBLE.md", os.path.join("docs", "shots", "shots.json"),
             "RUN-REPORT.md", "run-report.json")
IGNORE = shutil.ignore_patterns(".git", "build", ".verify", "__pycache__", "*.pending", ".godot")
checks = 0


def ok(cond: bool, what: str) -> None:
    global checks
    if not cond:
        print("SELFTEST FAIL: " + what)
        sys.exit(1)
    checks += 1


def copy_project(dst: str, template_files: bool = False) -> str:
    """Copy the project to dst with fresh run state (no live reviews, logs, counters, HALT, run-state.json data)."""
    shutil.copytree(KIT, dst, ignore=IGNORE)
    state = os.path.join(dst, ".claude", "run-state")
    shutil.rmtree(state, ignore_errors=True)
    os.makedirs(os.path.join(state, "reviews"))
    open(os.path.join(state, "reviews", ".gitkeep"), "w").close()
    if os.path.exists(os.path.join(dst, ".claude", "HALT")):
        os.remove(os.path.join(dst, ".claude", "HALT"))
    with open(os.path.join(dst, "run-state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"run": "r1", "status": "planning", "phases": {}, "spend": {}, "updated": ""}, f, indent=2)
    if template_files:
        for p in GENERATED:
            if os.path.exists(os.path.join(dst, p)):
                os.remove(os.path.join(dst, p))
    return dst


def hook(root: str, name: str, payload: dict, env: dict = None) -> dict:
    e = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    e.pop("KIT_HEADLESS", None)
    e.update(env or {})
    r = subprocess.run([sys.executable, os.path.join(root, ".claude", "hooks", name)], input=json.dumps(payload),
                       capture_output=True, text=True, env=e)
    ok(r.returncode == 0, "%s exits 0 (stderr: %s)" % (name, r.stderr.strip()))
    return json.loads(r.stdout) if r.stdout.strip() else {}


def hook_raw(root: str, name: str, raw: bytes) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    return subprocess.run([sys.executable, os.path.join(root, ".claude", "hooks", name)], input=raw,
                          capture_output=True, text=False, env=env)


def hook_raw_out(root: str, name: str, raw: bytes) -> dict:
    r = hook_raw(root, name, raw)
    ok(r.returncode == 0 and b"Traceback" not in r.stderr, "%s exits 0 on raw input (stderr: %s)" % (name, r.stderr.strip()))
    out = r.stdout.decode("utf-8", "replace")
    return json.loads(out) if out.strip() else {}


def tool(root: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    return subprocess.run([sys.executable, os.path.join(root, "tools", args[0])] + list(args[1:]),
                          capture_output=True, text=True, env=env, cwd=root)


def denied(out: dict) -> bool:
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def git(cwd: str, *args: str) -> str:
    r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True)
    ok(r.returncode == 0, "git %s (%s)" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def log_lines(root: str) -> list:
    p = os.path.join(root, ".claude", "run-state", "hooks.log.jsonl")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="kit-selftest-")
    root = copy_project(os.path.join(tmp, "proj"))
    try:
        # Fake paid service: balance lives in a file; "fake_job N" spends N.
        bal = os.path.join(root, "fake_balance.txt")
        with open(bal, "w") as f:
            f.write("100")
        py = '"%s"' % sys.executable
        fake = os.path.join(root, "fake_job.py")
        with open(fake, "w") as f:
            f.write("import sys\np=%r\nb=float(open(p).read())\nopen(p,'w').write(str(b-float(sys.argv[1])))\n" % bal)
        cfg_path = os.path.join(root, "kit.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        cfg["paid_services"]["fakesvc"] = {"cap": 25, "binaries": ["fakesvc"],
                                           "balance_cmd": '%s -c "print(open(r\'%s\').read())"' % (py, bal),
                                           "balance_regex": r"(\d+(?:\.\d+)?)"}
        cfg["heartbeat"] = False
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        with open(os.path.join(root, "PLAN.md"), "w", encoding="utf-8") as f:
            f.write("# PLAN\n\n## Run rules\n1. Never wait.\n\n## Phases\n- [x] **P0: Done**\n- [ ] **P1: Open phase**\n")
        with open(os.path.join(root, "PROGRESS.md"), "w", encoding="utf-8") as f:
            f.write("## 2026-01-01 05:00 | P0 Foundation | DONE\n")
        vis_required = bool(cfg.get("visual", {}).get("required"))
        cfg["visual"] = dict(cfg.get("visual", {}), required=False)
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))

        # --- Stop hook ---
        out = hook(root, "stop_guard.py", {"hook_event_name": "Stop"})
        ok(out.get("decision") == "block" and "P1" in out.get("reason", ""), "stop: open phase blocks the stop")
        open(os.path.join(root, ".claude", "HALT"), "w").close()
        ok(hook(root, "stop_guard.py", {}) == {}, "stop: HALT lets it stop")
        os.remove(os.path.join(root, ".claude", "HALT"))
        ok(tool(root, "review.py", "start", "P1-core-r1").returncode == 0, "review.py start")
        ok(hook(root, "stop_guard.py", {}) == {}, "stop: a fresh pending review holds (stop allowed)")
        pend = os.path.join(root, ".claude", "run-state", "reviews", "P1-core-r1.pending")
        old = time.time() - 30 * 60
        os.utime(pend, (old, old))
        out = hook(root, "stop_guard.py", {})
        ok(out.get("decision") == "block" and "timed out" in out.get("reason", ""), "stop: stale review -> relaunch instructions")
        verdict = os.path.join(root, "verdict.txt")
        with open(verdict, "w") as f:
            f.write('Looks fine.\n```json\n{"verdict": "fix_needed", "findings": [{"id": "P1-1", "severity": "high", '
                    '"blocking": true, "scenario": "x", "fix": "y"}]}\n```\n')
        ok(tool(root, "review.py", "done", "P1-core-r1", "--verdict-file", verdict).returncode == 0, "review.py done")
        rs = json.load(open(os.path.join(root, "run-state.json"), encoding="utf-8"))
        ok(rs["reviews"]["P1-core-r1"]["blocking_open"] == ["P1-1"] and not os.path.exists(pend), "review recorded in run-state")
        cfg["max_continues"] = 1
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        ok(hook(root, "stop_guard.py", {}) == {}, "stop: continue budget exhausted lets it stop")
        cfg["max_continues"] = 300
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        with open(os.path.join(root, "PLAN.md"), "w", encoding="utf-8") as f:
            f.write("- [x] **P0: Done**\n- [-] **P1: Skipped**\n")
        ok(hook(root, "stop_guard.py", {}) == {}, "stop: no open phase lets it stop")
        stops = [x for x in log_lines(root) if x["hook"] == "stop_guard"]
        ok(len(stops) >= 6 and {x["outcome"] for x in stops} >= {"blocked", "allowed"} and all(x.get("reason") for x in stops),
           "hooks.log.jsonl: every Stop decision logged with its reason")

        # --- PreToolUse guard ---
        def guard(cmd: str, tool_name: str = "Bash") -> dict:
            return hook(root, "pre_tool_guard.py", {"tool_name": tool_name, "tool_input": {"command": cmd}})
        ok(denied(guard("fakesvc generate --big")), "guard: raw paid binary denied")
        ok(not denied(guard("python tools/paid.py fakesvc --estimate 5 -- fakesvc generate")), "guard: paid.py allowed")
        ok(denied(guard('rm -f "$S"/*.png')), "guard: delete on a variable path denied (the run-2 hang)")
        ok(not denied(guard('rm -f "${S:?}"/x.png')), "guard: ${VAR:?} form accepted")
        ok(denied(guard("rm -rf /etc/somewhere")), "guard: delete outside project denied (POSIX path)")
        ok(denied(guard("rm -rf C:/Windows/Temp/x")), "guard: delete outside project denied (drive-letter path, any OS)")
        ok(denied(guard(r"rm -rf \\server\share\x")), "guard: delete on a UNC path denied (any OS)")
        ok(not denied(guard("rm -rf build/old.zip")), "guard: delete inside project allowed")
        ok(denied(guard("Remove-Item -Recurse -Force C:/Users/x/Documents", "PowerShell")), "guard: PowerShell delete outside denied (drive-letter path)")
        ok(denied(guard(r"Remove-Item -Recurse -Force C:\Users\x\Documents", "PowerShell")), "guard: PowerShell delete outside denied (backslash path)")
        ok(denied(guard("Remove-Item -Recurse -Force /home/x/Documents", "PowerShell")), "guard: PowerShell delete outside denied (Linux path)")
        ok(not denied(guard("Remove-Item -Recurse -Force build/old", "PowerShell")), "guard: PowerShell delete inside project allowed")
        ok(not denied(guard(r"Remove-Item -Recurse -Force build\old", "PowerShell")), "guard: backslash path inside project allowed")
        ok(denied(guard("Remove-Item -Recurse -Force //server/share/x", "PowerShell")), "guard: forward-slash UNC path denied (any OS)")
        ok(denied(guard(r"Remove-Item -Recurse -Force \Windows\Temp", "PowerShell")), "guard: drive-root path (\\x) denied (any OS)")
        ok(denied(guard("ls && rm -rf /etc/x")), "guard: delete after && still checked")
        ok(not denied(guard("cat >> PROGRESS.md <<'EOF'\n- cleaned up: rm -rf /etc/x was NOT run\nEOF")),
           "guard: a delete mentioned in a heredoc body is text, not a command")
        ok(denied(guard("git push --force origin main")), "guard: force push denied")
        ok(denied(guard("gh release delete r1-build")), "guard: release delete denied")
        ok(not denied(guard("gh release delete-asset r1-build old.zip")), "guard: delete-asset allowed")
        ok(not denied(guard("git status && ls")), "guard: harmless command allowed")
        dn = [x for x in log_lines(root) if x["hook"] == "pre_tool_guard"]
        ok(dn and all(x["outcome"] == "denied" and x.get("reason") for x in dn) and
           any("force push" in x["reason"] for x in dn), "hooks.log.jsonl: guard denies logged (allows are not)")

        # --- raw-byte stdin (BOM / UTF-16 / garbage / empty) ---
        def pj(cmd: str) -> str:
            return json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
        bom = b"\xef\xbb\xbf"
        pg = "pre_tool_guard.py"
        ok(denied(hook_raw_out(root, pg, bom + pj("git push --force origin main").encode())), "guard: BOM-prefixed force push denied")
        ok(not denied(hook_raw_out(root, pg, bom + pj("git status").encode())), "guard: BOM-prefixed harmless command allowed")
        ok(denied(hook_raw_out(root, pg, pj("git push --force origin main").encode())), "guard: no-BOM force push denied")
        ok(denied(hook_raw_out(root, pg, b"\xff\xfe\x00not json")), "guard: garbage bytes denied (fail closed)")
        ok(denied(hook_raw_out(root, pg, b"")), "guard: empty input denied (fail closed)")
        ok(denied(hook_raw_out(root, pg, b"[1]")), "guard: non-object JSON denied (fail closed)")
        ok(denied(hook_raw_out(root, pg, b"\xff\xfe" + pj("git push --force origin main").encode("utf-16-le"))),
           "guard: UTF-16-LE BOM force push denied")
        for h in ("stop_guard.py", "session_start.py", "subagent_stop.py", "permission_log.py", "heartbeat.py"):
            hook_raw_out(root, h, bom + json.dumps({"source": "compact"}).encode())
            hook_raw_out(root, h, b"\xff\xfe\x00not json")
            ok(True, "%s survives BOM and garbage input" % h)

        # --- SessionStart hook ---
        with open(os.path.join(root, "PLAN.md"), "w", encoding="utf-8") as f:
            f.write("## Run rules\n1. Never wait.\n\n## Phases\n- [ ] **P2: Next**\n")
        out = hook(root, "session_start.py", {"source": "compact", "session_id": "sess-1"})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        ok("Never wait" in ctx and "P2" in ctx and "P0 Foundation" in ctx and "sess-1" in ctx,
           "session_start: session id, rules, phases and progress re-injected")

        # --- PermissionRequest hook: headless runs deny + log, interactive sessions untouched ---
        preq = {"hook_event_name": "PermissionRequest", "session_id": "sess-1", "tool_name": "Bash",
                "tool_input": {"command": "npm install left-pad"}}
        ok(hook(root, "permission_log.py", preq) == {}, "permission hook: interactive session -> no decision (normal prompt)")
        out = hook(root, "permission_log.py", preq, env={"KIT_HEADLESS": "1"})
        dec = out.get("hookSpecificOutput", {})
        dfile = os.path.join(root, ".claude", "run-state", "denied.jsonl")
        drec = [json.loads(x) for x in open(dfile, encoding="utf-8")] if os.path.exists(dfile) else []
        ok(dec.get("hookEventName") == "PermissionRequest" and dec.get("decision", {}).get("behavior") == "deny" and
           "do not retry" in dec["decision"].get("message", "") and drec and drec[-1]["tool"] == "Bash" and
           "npm install" in drec[-1]["input"], "permission hook: headless -> deny with skip message, denied.jsonl line")
        with open(os.path.join(root, ".claude", "run-state", "session.json"), "w", encoding="utf-8") as f:
            json.dump({"session_id": "sess-1", "mode": "headless"}, f)
        ok(hook(root, "permission_log.py", preq).get("hookSpecificOutput", {}).get("decision", {}).get("behavior") == "deny",
           "permission hook: session.json mode headless (same session) -> deny")
        os.remove(os.path.join(root, ".claude", "run-state", "session.json"))

        # --- paid.py with the fake service ---
        r = tool(root, "paid.py", "fakesvc", "--estimate", "10", "--", sys.executable, fake, "8")
        ok(r.returncode == 0 and "cost 8.0" in r.stdout, "paid: job runs and the real cost (balance drop) is recorded: " + r.stdout)
        r = tool(root, "paid.py", "fakesvc", "--estimate", "10", "--", sys.executable, fake, "9")
        ok(r.returncode == 0, "paid: second job (17 used) runs")
        r = tool(root, "paid.py", "fakesvc", "--estimate", "10", "--", sys.executable, fake, "9")
        ok(r.returncode == 3 and "REFUSED" in r.stdout, "paid: refuses when used + estimate > cap")
        ok(abs(float(open(bal).read()) - 83.0) < 0.01, "paid: the refused job never ran")
        led = json.load(open(os.path.join(root, ".claude", "run-state", "spend.json"), encoding="utf-8"))
        rs = json.load(open(os.path.join(root, "run-state.json"), encoding="utf-8"))
        ok(led["fakesvc"]["used"] == 17 and rs["spend"]["fakesvc"]["used"] == 17, "paid: ledger and run-state agree (17/25)")
        ok(tool(root, "paid.py", "nosuch", "--", "echo").returncode == 2, "paid: unknown service rejected")

        # --- visual pipeline: config, docs, templates ---
        sys.path.insert(0, os.path.join(root, "tools"))
        sys.path.insert(0, os.path.join(root, ".claude", "hooks"))
        import art_gate
        import kitlib
        kitcfg = json.load(open(os.path.join(KIT, "kit.json"), encoding="utf-8"))
        vis0 = kitcfg["visual"]
        if kitcfg.get("project") == "PROJECT_NAME":
            ok(vis0.get("required") is False, "kit.json: visual.required defaults to false (non-visual works out of the box)")
        else:
            ok(vis0.get("required") in (True, False), "kit.json: initialised project (%s): visual.required %s on purpose"
               % (kitcfg.get("project"), vis0.get("required")))
        ok(vis0.get("rubric") and set(vis0.get("stage_a_items", [])) <= set(vis0["rubric"]) and
           "performance" not in vis0["rubric"], "kit.json: rubric and stage-A subset configurable; performance is not a rubric item")
        lock = vis0.get("lock_phase", "P1")
        ok(all(isinstance(kitlib.review_cap(kitcfg, lock, s), int) and kitlib.review_cap(kitcfg, lock, s) >= 1
               for s in ("A", "")) and kitlib.on_cap(kitcfg) in ("proceed_with_known_issues", "mark_skipped"),
           "kit.json: review caps resolve to positive integers per stage; on_cap is valid")
        ok(kitlib.review_cap({}, "P1", "A") == 3 and kitlib.review_cap({}, "P1", "") == 6 and
           kitlib.review_cap({"visual": {"look_fix_max_iterations": 8}}, "P1", "") == 8 and
           kitlib.review_cap({"visual": {"review_caps": {"phases": {"P1": {"A": 2, "": 9}, "P3": 5}}}}, "P1", "A") == 2 and
           kitlib.review_cap({"visual": {"review_caps": {"phases": {"P1": {"A": 2, "": 9}, "P3": 5}}}}, "P1", "") == 9 and
           kitlib.review_cap({"visual": {"review_caps": {"phases": {"P3": 5}}}}, "P3", "") == 5,
           "review caps: defaults 3/6, legacy look_fix_max_iterations fallback, per-phase overrides")
        if kitcfg.get("project") == "PROJECT_NAME":
            ok("look_fix_max_iterations" not in vis0 and vis0.get("review_caps", {}).get("stage_a") == 3 and
               vis0["review_caps"].get("default") == 6 and vis0.get("on_cap") == "proceed_with_known_issues",
               "kit.json template: review_caps 3/6 and on_cap replace look_fix_max_iterations")
        ok(vis0.get("rubric_min_score") in (1, 2, 3, 4, 5), "kit.json visual.rubric_min_score is 1-5")
        ok(not kitlib.calibration_config_problems(kitcfg) and
           (not (vis0.get("calibration") or {}).get("required") or vis0["calibration"].get("cap_item") in vis0["rubric"]),
           "kit.json: visual.calibration.cap_item %r is an item of visual.rubric (else a mismatch caps nothing)"
           % (vis0.get("calibration") or {}).get("cap_item"))
        if kitcfg.get("project") == "PROJECT_NAME":
            ok("style_match" in vis0["rubric"] and "cohesion" in vis0["rubric"] and
               vis0.get("calibration", {}).get("cap_item") == "style_match" and
               vis0["rubric"] == kitlib.DEFAULT_RUBRIC,
               "kit.json template: style_match in the default rubric and the default cap_item (cohesion kept)")
        ok(set(vis0.get("perf") or {}) >= {"min_avg_fps", "min_low1_fps"}, "kit.json visual.perf has the fps thresholds")
        tpl = open(os.path.join(root, "templates", "ART-BIBLE.md"), encoding="utf-8").read()
        ok(all("\n## %s\n" % s in tpl for s in art_gate.SECTIONS), "art bible template has every required section")
        spec = open(os.path.join(root, "templates", "ASSET-SPEC.md"), encoding="utf-8").read()
        ok(all(k in spec for k in ("- Class:", "- Route:", "- Budget:", "- Done when:")), "asset spec template has its fields")
        doc = open(os.path.join(root, "docs", "visual-pipeline.md"), encoding="utf-8").read()
        ok(all("\n## %d. " % i in doc for i in range(1, 8)) and "A screenshot existing is not a pass" in doc,
           "visual-pipeline doc has sections 1-7 and the pass rule")
        ok(all("| `%s` |" % r in doc for r in kitlib.DEFAULT_RUBRIC) and "Performance is an automated gate" in doc,
           "visual-pipeline doc describes every default rubric item; performance is automated")
        ok(all(k in doc for k in ("Style slice", "placeholder", "before|after", "revert", "never passes its own work",
                                  "docs/style_reference/", "--bible ART-BIBLE.md", "docs/shots/_work/", "final/",
                                  "Below bar never halts the run", "--known-issues", "review_caps", "rounds/<id>/",
                                  "stage_a_min_score", "side track", "<run>-start", "<run>-lighting-lock")),
           "visual-pipeline doc: style slice, before/after + revert, review caps, below bar, previous round, side track")
        snip = open(os.path.join(root, "templates", "visual", "snippets.md"), encoding="utf-8").read()
        ok("\n## Style lock\n" in snip and "new work must match these" in snip and "stops the run" not in snip and
           all(k in snip for k in ("photoreal", "skipped cleanup", "Mixing asset styles", "generation prompts",
                                   "Pure black shadows", "Uniform random scatter", "--known-issues")),
           "visual snippets have the style lock, the never-do list and the below-bar rule")
        plan_tpl = open(os.path.join(root, "templates", "PLAN.md"), encoding="utf-8").read()
        ok("Never wrap or re-route a blocked" in plan_tpl and "Style slice" not in plan_tpl,
           "plan template: never-wrap run rule; no visual phase unless --visual")
        tech = open(os.path.join(root, "addons", "godot", "docs", "stylized-techniques.md"), encoding="utf-8").read()
        ok("Techniques, not rules. For stylized projects only." in tech.split("\n## ")[0],
           "godot stylized-techniques doc is marked as techniques, not rules")
        vr = open(os.path.join(root, ".claude", "agents", "visual-reviewer.md"), encoding="utf-8").read()
        vr_tools = vr.split("tools:", 1)[1].split("\n", 1)[0]
        ok("top 3 problems" in vr and "critique.md" in vr and '"review_id"' in vr and '"performance"' not in vr and
           "visual.rubric" in vr and "SubagentHandback" in vr and '"vs_previous"' in vr and "stops the run" not in vr
           and not any(t in vr_tools for t in ("Bash", "Write", "Edit")),
           "visual-reviewer: rubric, review_id, handback + plain text, vs_previous, no performance, read-only tools")
        ok("previous-round.md" in vr and "before you open anything from the previous round" in vr and
           "previous round's scores" not in vr.replace("never see the previous round's scores", ""),
           "visual-reviewer: scores this round first, then reads previous-round.md (top problems, no scores)")
        rp = open(os.path.join(root, ".claude", "skills", "run-protocol", "SKILL.md"), encoding="utf-8").read()
        ok(all(k in rp for k in ("review.py close", "never wrap or re-route", "Below bar never halts the run",
                                 "--known-issues", "SubagentStop", "SubagentHandback", "docs/shots/_work/",
                                 "perf_gate.py", "session id", "side track")) and "stops the run" not in rp,
           "run-protocol: close check, never-wrap, below bar, handback, session id, side track, perf")
        ok(all(k in rp for k in ("next round", "reviewed rounds", "status: blocked", "previous-round.md",
                                 "review.py headline", "resume.sh", "stall_min")),
           "run-protocol: rounds in order, cap on reviewed rounds, blocked after 2 failed rounds, anti-anchoring, "
           "headline, resume.sh, stall_min")
        ok(isinstance(kitcfg.get("stall_min"), dict) and isinstance(kitcfg["stall_min"].get("default"), (int, float)) and
           isinstance(kitcfg["stall_min"].get("phases", {}), dict), "kit.json: stall_min default + per-phase overrides")
        gi = open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
        ok(".claude/run-state/session.json" in gi and ".claude/run-state/resume.log" in gi,
           ".gitignore: session.json and resume.log are runtime files")
        st = json.load(open(os.path.join(root, ".claude", "settings.json"), encoding="utf-8"))
        perms, hooks = st["permissions"], st["hooks"]
        cmds = lambda ev: [h["command"] for e in hooks.get(ev, []) for h in e["hooks"]]  # noqa: E731
        ok(any("subagent_stop.py" in c for c in cmds("SubagentStop")) and
           any(set(e.get("matcher", "").split("|")) >= {"Bash", "PowerShell", "Write", "Edit", "MultiEdit", "NotebookEdit"}
               for e in hooks["PreToolUse"]) and any("heartbeat.py" in c for c in cmds("PostToolUse")) and
           any("permission_log.py" in c for c in cmds("PermissionRequest")),
           "settings: SubagentStop, PreToolUse guard (shell + file tools), PostToolUse heartbeat, PermissionRequest wired")
        ok("Edit(.claude/run-state/**)" in perms["deny"] and "Write(.claude/run-state/**)" not in perms["deny"],
           "settings: Edit deny on .claude/run-state (covers the file tools); the dead Write rule is gone")
        ok(all("%s(%s *)" % (s, b) in perms["allow"] for s in ("Bash", "PowerShell")
               for b in ("godot", "godot_console", "blender", "ffmpeg")) and
           all(a in perms["allow"] for a in ("Bash(python3 tools/*)", "Bash(xvfb-run *)", "Bash(gh run *)", "Bash(gh pr view *)")),
           "settings: godot, godot_console, blender, ffmpeg, python3 tools, xvfb-run, gh run / pr view allowed")
        ok("bypassPermissions" not in json.dumps(st) and "dangerously" not in json.dumps(st), "settings: no bypassPermissions")
        ok("docs/shots/_work/" in open(os.path.join(root, ".gitignore"), encoding="utf-8").read(),
           ".gitignore keeps per-iteration renders out of git")
        rs_gd = open(os.path.join(root, "addons", "godot", "tools", "render_shots.gd"), encoding="utf-8").read()
        ok(all(k in rs_gd for k in ("seed(", "Engine.time_scale = 0.0", "paused = true", "get_size() != want",
                                    "BENCH avg_fps=")), "render_shots.gd: seeded, time frozen, PNG size asserted, bench line")
        import py_compile
        py_compile.compile(os.path.join(root, "tools", "blender", "cleanup_asset.py"), doraise=True)
        ok(True, "blender cleanup script compiles (run separately in Blender: see the PR / docs)")
        hl = open(os.path.join(root, "docs", "headless.md"), encoding="utf-8").read()
        ok(all(k in hl for k in ("--permission-mode acceptEdits", "--session-id", "stream-json", "--resume",
                                 "hasTrustDialogAccepted", "CLAUDE_CODE_OAUTH_TOKEN", "denied.jsonl", "heartbeat",
                                 "STALL_MIN", "run_watch.sh", "Never use `--permission-mode bypassPermissions`")),
           "docs/headless.md: launch flags, resume, pre-launch checklist, denied log, heartbeat, watcher")

        # --- visual reviews: captured by the SubagentStop hook, validated, never self-supplied ---
        cfg["visual"] = dict(vis0, required=True)
        cfg["visual"].pop("stage_a_min_score", None)
        if all((vis0.get("perf") or {}).get(k) is None for k in ("min_avg_fps", "min_low1_fps")):
            # a project that defers the perf gate (null thresholds) still exercises it with the template thresholds
            cfg["visual"]["perf"] = {"min_avg_fps": 60, "min_low1_fps": 30}
        # calibration against the reference: required, capping the project's style item (else the template's)
        cal_item = next((i for i in ((vis0.get("calibration") or {}).get("cap_item"), "stylization", "cohesion")
                         if i in vis0["rubric"]), vis0["rubric"][-1])
        cfg["visual"]["calibration"] = {"required": True, "cap_item": cal_item, "cap": 3}
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        os.makedirs(os.path.join(root, "docs", "shots"), exist_ok=True)
        shutil.copy(os.path.join(root, "templates", "shots.json"), os.path.join(root, "docs", "shots", "shots.json"))
        shots = json.load(open(os.path.join(root, "templates", "shots.json"), encoding="utf-8"))
        ok(isinstance(shots.get("version"), int) and isinstance(shots.get("seed"), int) and
           all(s.get("name") and s.get("refs") for s in shots["shots"]),
           "shot set template: integer version, seed, every shot named with refs")
        names = [s["name"] for s in shots["shots"]]
        items, stage_a = vis0["rubric"], vis0["stage_a_items"]
        revdir = os.path.join(root, ".claude", "run-state", "reviews")
        run_id = cfg.get("run", "r1")
        final = os.path.join(root, "docs", "shots", run_id, "P1", "final")
        os.makedirs(final, exist_ok=True)
        for n in names:
            with open(os.path.join(final, n + ".png"), "wb") as f:
                f.write(b"\x89PNG fake " + n.encode())

        def full(verdict="pass", score=4, rid="P1-visual-r1", **extra) -> dict:
            v = {"review_id": rid, "verdict": verdict, "findings": [], "shot_set_version": shots["version"],
                 "scores": {n: {i: score for i in items} for n in names},
                 "calibration": {"reference": {i: 5 for i in items}, "shots": {n: "match: same density" for n in names}}}
            v.update(extra)
            return v

        def stage_a_full(verdict="pass", score=4, rid="P1-visualA-r1", **extra) -> dict:
            v = full(verdict, score, rid, **extra)
            for n in names:
                for i in items:
                    if i not in stage_a:
                        v["scores"][n][i] = "n/a"
            return v

        def forget(rid: str) -> None:
            """Drop every trace of a review id, so the next `start` of it is a first start (rounds start in order)."""
            for ext in (".json", ".pending"):
                if os.path.exists(os.path.join(revdir, rid + ext)):
                    os.remove(os.path.join(revdir, rid + ext))
            rs0 = json.load(open(os.path.join(root, "run-state.json"), encoding="utf-8"))
            rs0.get("reviews", {}).pop(rid, None)
            json.dump(rs0, open(os.path.join(root, "run-state.json"), "w", encoding="utf-8"))

        def capture(v: dict, reads=None, active=False, agent="visual-reviewer", start=True, keep=False, mode="text",
                    extra_reads=(), folder=None, rid=None, blind=None):
            rid = rid or v.get("review_id", "none")
            if start:
                forget(rid)
                tool(root, "review.py", "start", rid)
            tr = os.path.join(tmp, "agent.jsonl")
            report = "Scores below.\n```json\n%s\n```\n" % json.dumps(v) if v is not None else "Shots look muddy."
            with open(tr, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"role": "user", "content":
                                    "Review id %s. Shots: docs/shots/r1/P1/rounds/%s/" % (rid, rid)}}) + "\n")
                cur = [os.path.join(folder or final, n + ".png") for n in (names if reads is None else reads)]
                for p in cur + ["BLIND"] + list(extra_reads):
                    if p == "BLIND":   # blind scores, written before the first look at the previous round
                        if blind is not None:
                            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                                {"type": "text", "text": "Blind scores.\n```json\n%s\n```\n" % json.dumps(
                                    {"blind_scores": blind})}]}}) + "\n")
                        continue
                    f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                        {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": p}}]}}) + "\n")
                if mode == "text":
                    content = [{"type": "text", "text": report}]
                elif mode == "nested":
                    content = [{"type": "tool_use", "id": "h1", "name": "SubagentHandback",
                                "input": {"message": {"content": [{"type": "text", "text": report}]}}}]
                else:   # handback: the verdict only inside the SubagentHandback input (the r2..r7 case)
                    content = [{"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": report}}]
                f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": content}}) + "\n")
                if mode != "text":
                    f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
                        {"tool_use_id": "h1", "type": "tool_result", "content": [{"type": "text", "text": "{\"success\":true}"}]}]}}) + "\n")
            out = hook(root, "subagent_stop.py", {"hook_event_name": "SubagentStop", "agent_type": agent,
                                                  "agent_id": "a1", "agent_transcript_path": tr,
                                                  "stop_hook_active": active, "last_assistant_message": ""})
            p = os.path.join(revdir, rid + ".json")
            stored = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
            if stored is not None and not keep:
                os.remove(p)
            pend = os.path.join(revdir, rid + ".pending")
            if os.path.exists(pend):
                os.remove(pend)
            return out, stored

        def rejected(res) -> bool:
            return res[0].get("decision") == "block" and res[1] is None

        def rs_review(rid: str) -> dict:
            return json.load(open(os.path.join(root, "run-state.json"), encoding="utf-8"))["reviews"].get(rid, {})

        selfv = os.path.join(root, "self_verdict.txt")
        with open(selfv, "w") as f:
            f.write('```json\n%s\n```\n' % json.dumps(full()))
        tool(root, "review.py", "start", "P1-visual-r1")
        r = tool(root, "review.py", "done", "P1-visual-r1", "--verdict-file", selfv)
        ok(r.returncode != 0 and not os.path.exists(os.path.join(revdir, "P1-visual-r1.json")),
           "review.py done: a builder-supplied visual verdict is refused (even a complete pass)")
        os.remove(os.path.join(revdir, "P1-visual-r1.pending"))
        ok(rejected(capture({"review_id": "P1-visual-r1", "verdict": "pass", "findings": []})),
           "capture: self-style pass without scores rejected, reviewer told why")
        v = full()
        del v["scores"][names[-1]]
        ok(rejected(capture(v)), "capture: scores missing a shot rejected")
        v = full()
        del v["scores"][names[0]][items[-1]]
        ok(rejected(capture(v)), "capture: scores missing a rubric item rejected (partial scores)")
        v = full()
        v["scores"][names[0]]["performance"] = 5
        ok(rejected(capture(v)), "capture: unknown rubric item (performance) rejected")
        v = full()
        v["scores"][names[0]][items[-1]] = "n/a"
        ok(rejected(capture(v)), "capture: n/a outside stage A rejected")
        v = stage_a_full()
        ok(capture(v)[1] is not None, "capture: stage A pass with n/a outside the stage-A items stored")
        v["scores"][names[0]][stage_a[0]] = "n/a"
        ok(rejected(capture(v)), "capture: n/a on a stage-A item rejected")
        ok(rejected(capture(full(shot_set_version=shots["version"] + 1))), "capture: wrong shot_set_version rejected")
        ok(rejected(capture(full(score=3))), "capture: pass with a score below the minimum rejected")
        ok(rejected(capture(full(incomplete=True))), "capture: incomplete pass rejected")
        ok(capture(full("fix_needed", 3))[1] is not None, "capture: fix_needed with low scores stored")
        v = full()
        del v["calibration"]
        ok(rejected(capture(v)), "calibration: a verdict without the reference calibration is rejected (required)")
        v = full("fix_needed", 4)
        v["calibration"]["shots"][names[0]] = "mismatch: bare lawn vs the dense ref"
        ok(rejected(capture(v)), "calibration: a style/density mismatch caps %s at 3 (4 rejected)" % cal_item)
        v["scores"][names[0]][cal_item] = 3
        ok(capture(v)[1] is not None, "calibration: mismatch with %s at the cap is stored" % cal_item)
        v = full()
        del v["calibration"]["shots"][names[-1]]
        ok(rejected(capture(v)), "calibration: every shot needs a style/density judgement vs the reference")
        # cap_item outside the rubric: fail loudly (review.py start refuses, the verdict check reports it), never a no-op
        bad_cfg = json.loads(json.dumps(cfg))
        bad_cfg["visual"]["calibration"]["cap_item"] = "no_such_item"
        ok(any("not an item of visual.rubric" in e for e in kitlib.calibration_problems(full(), bad_cfg, names)) and
           any("not an item of visual.rubric" in e for e in kitlib.validate_verdict(full(), "P1-visual-r1", bad_cfg)),
           "calibration: a cap_item that is not a rubric item is an error in the verdict check, not a silent skip")
        forget("P1-visual-r1")
        json.dump(bad_cfg, open(cfg_path, "w", encoding="utf-8"))
        r = tool(root, "review.py", "start", "P1-visual-r1")
        ok(r.returncode == 2 and "START REFUSED" in r.stdout and "no_such_item" in r.stdout and
           "not an item of visual.rubric" in r.stdout and not os.path.exists(os.path.join(revdir, "P1-visual-r1.pending")),
           "review.py start: refused while visual.calibration.cap_item is not a rubric item: " + r.stdout)
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        r = tool(root, "review.py", "start", "P1-visual-r1")
        ok(r.returncode == 0 and os.path.exists(os.path.join(revdir, "P1-visual-r1.pending")),
           "review.py start: starts with a cap_item that is a rubric item (%s)" % cal_item)
        forget("P1-visual-r1")
        ok(rejected(capture(full(), reads=names[:-1])), "capture: reviewer that did not open every shot PNG rejected")
        ok(rejected(capture(full(), start=False)), "capture: review not started with review.py start rejected")
        ok(rejected(capture(full(rid="P1-ux-r1"))), "capture: non-visual review id rejected")
        out, sv = capture(full(score=3), active=True)
        ok(out == {} and sv is None and rs_review("P1-visual-r1")["status"] == "invalid",
           "capture: second invalid stop lets the reviewer stop, recorded invalid, nothing stored")
        ok(capture(full(), agent="adversarial-reviewer") == ({}, None), "capture: other agents ignored")
        out, sv = capture(full())
        ok(out == {} and sv and sv.get("captured_by") == "subagent_stop" and sv.get("shots_folder") and
           sv.get("captured_from") == "transcript_text", "capture: complete reviewer pass stored with captured_by and the shots folder")
        # SubagentHandback (background subagents): the verdict only in the handback tool input (the r1 run's r2..r7).
        out, sv = capture(full("fix_needed", 3, top_problems=["a", "b", "c"]), mode="handback")
        ok(out == {} and sv and sv.get("captured_from") == "handback" and sv["verdict"] == "fix_needed",
           "capture: verdict only in the SubagentHandback input is stored (the r2..r7 miss)")
        out, sv = capture(full(), mode="nested")
        ok(out == {} and sv and sv.get("captured_from") == "handback", "capture: nested handback input is read")
        out, sv = capture(full(score=3), mode="handback")
        ok(out == {} and sv is None and rs_review("P1-visual-r1")["status"] == "invalid" and
           any("below" in p for p in rs_review("P1-visual-r1").get("problems", [])),
           "capture: invalid verdict after a handback -> no block (cannot be acted on), recorded invalid at once")
        forget("P1-visual-r1")
        tool(root, "review.py", "start", "P1-visual-r1")
        out, sv = capture(None, mode="handback", start=False, rid="P1-visual-r1")
        ok(out == {} and sv is None and not os.path.exists(os.path.join(revdir, "P1-visual-r1.pending")) and
           rs_review("P1-visual-r1")["status"] == "invalid" and
           any("no JSON verdict" in p for p in rs_review("P1-visual-r1").get("problems", [])),
           "capture: handback without a verdict -> invalid at once, .pending removed (id from the builder's prompt)")
        before = len(log_lines(root))
        hook_raw_out(root, "subagent_stop.py", b"")
        hook(root, "subagent_stop.py", {"agent_type": "plan-critic"})
        capture(full())
        logs = [x for x in log_lines(root)[before:] if x["hook"] == "subagent_stop"]
        ok([x["outcome"] for x in logs] == ["error", "ignored", "stored"] and logs[-1].get("source") == "transcript_text"
           and logs[-1].get("review_id") == "P1-visual-r1" and logs[1].get("agent_type") == "plan-critic",
           "hooks.log.jsonl: every SubagentStop call logged (bad input, ignored agent, stored + source)")
        sl = [x for x in log_lines(root) if x["hook"] == "subagent_stop"]
        ok({"blocked", "invalid"} <= {x["outcome"] for x in sl} and
           all(x.get("problems") for x in sl if x["outcome"] in ("blocked", "invalid")),
           "hooks.log.jsonl: blocked and invalid outcomes carry their problems")
        verdict_v = os.path.join(root, "verdict_v.txt")

        def plain_verdict(verdict: str, depth) -> int:
            with open(verdict_v, "w") as f:
                f.write('```json\n%s\n```\n' % json.dumps({"verdict": verdict, "findings": [], "scores": {
                    "shot-01-wide": {"silhouette": 4, "depth": depth, "life": "n/a"}}}))
            tool(root, "review.py", "start", "P1-slice-r1")
            return tool(root, "review.py", "done", "P1-slice-r1", "--verdict-file", verdict_v).returncode
        ok(plain_verdict("pass", 3) != 0, "review.py (non-visual id): pass with a score below the minimum rejected")
        ok(plain_verdict("fix_needed", 3) == 0 and plain_verdict("pass", 4) == 0,
           "review.py (non-visual id): fix_needed and a pass at the minimum accepted")

        # --- reviewer sees the previous round: snapshot + brief ---
        def reset_reviews() -> None:
            for f in os.listdir(revdir):
                if f.endswith((".json", ".pending")):
                    os.remove(os.path.join(revdir, f))
            rs0 = json.load(open(os.path.join(root, "run-state.json"), encoding="utf-8"))
            rs0["reviews"], rs0["phases"], rs0["status"] = {}, {}, "in_progress"
            rs0.pop("blocked_reason", None)
            json.dump(rs0, open(os.path.join(root, "run-state.json"), "w", encoding="utf-8"))
        reset_reviews()
        rounds = os.path.join(root, "docs", "shots", run_id, "P1", "rounds")
        r = tool(root, "review.py", "start", "P1-visual-r1")
        ok(r.returncode == 0 and all(os.path.exists(os.path.join(rounds, "P1-visual-r1", n + ".png")) for n in names) and
           "rounds/P1-visual-r1/" in r.stdout and "Previous round: none" in r.stdout,
           "review.py start: snapshots final/ into rounds/<id>/ and prints the brief (first round)")
        # score mentions use this project's rubric item names (the scrubber reads kit.json visual.rubric), in both the
        # spaced and the key spelling, so the check also holds in a project with its own rubric
        i0, i1 = items[0].replace("_", " "), items[1]
        capture(full("fix_needed", 3, findings=[{"id": "V-1", "severity": "high", "blocking": True,
                                                  "scenario": "fog too dense, %s 2" % i0, "fix": "density 0.02"}],
                     top_problems=["shot-01: fog too dense (%s 3, %s=2, 2/5)" % (i0, i1)]), start=False, keep=True)
        r = tool(root, "review.py", "start", "P1-visual-r2")
        brief = os.path.join(rounds, "P1-visual-r2", "review-brief.md")
        notes_p = os.path.join(rounds, "P1-visual-r2", "previous-round.md")
        notes = open(notes_p, encoding="utf-8").read() if os.path.exists(notes_p) else ""
        ok(r.returncode == 0 and "rounds/P1-visual-r1/" in r.stdout and "previous-round.md" in r.stdout and
           "vs_previous" in r.stdout and os.path.exists(brief) and "fog too dense" not in r.stdout and
           "Only then" in r.stdout, "review.py start: brief names the previous round's folder; its problems only in "
           "previous-round.md, opened after scoring: " + r.stdout)
        ok("fog too dense" in notes and "V-1" in notes and "vs_previous" in notes and
           not any(x in notes for x in ('"%s": 3' % items[0], "%s 3" % i0, "%s 2" % i0, "%s=2" % i1, "2/5",
                                        '"scores"')) and
           not any(x in r.stdout for x in ('"%s": 3' % items[0], "Previous scores", '"scores"')),
           "anti-anchoring: previous-round.md has the top problems and findings, never the scores: " + notes)
        prev_reads = [os.path.join(rounds, "P1-visual-r1", n + ".png") for n in names]
        pend2 = os.path.join(revdir, "P1-visual-r2.pending")
        out, sv = capture(full("fix_needed", 3, rid="P1-visual-r2"), start=False, extra_reads=[notes_p] + prev_reads)
        ok(rejected((out, sv)) and "blind scores" in out.get("reason", ""),
           "blind vs_previous: opening previous-round.md before writing blind scores is rejected")
        open(pend2, "w").close()
        out, sv = capture(full("fix_needed", 3, rid="P1-visual-r2"), start=False, extra_reads=prev_reads,
                          blind=full("fix_needed", 2)["scores"])
        ok(rejected((out, sv)) and "never raise" in out.get("reason", ""),
           "blind vs_previous: a final score above the blind score is rejected (comparison never raises a score)")
        open(pend2, "w").close()
        part = full("fix_needed", 3)["scores"]
        del part[names[-1]][items[-1]]
        out, sv = capture(full("fix_needed", 3, rid="P1-visual-r2"), start=False, extra_reads=prev_reads, blind=part)
        ok(rejected((out, sv)) and "every shot x item" in out.get("reason", "") and
           "%s %s" % (names[-1], items[-1]) in out.get("reason", ""),
           "blind vs_previous: a blind block missing a cell is rejected (no cell escapes the never-raise check)")
        open(pend2, "w").close()
        part = full("fix_needed", 3)["scores"]
        del part[names[0]]
        out, sv = capture(full("fix_needed", 3, rid="P1-visual-r2"), start=False, extra_reads=prev_reads, blind=part)
        ok(rejected((out, sv)) and "every shot x item" in out.get("reason", ""),
           "blind vs_previous: a blind block missing a whole shot is rejected")
        open(pend2, "w").close()
        out, sv = capture(full("fix_needed", 3, rid="P1-visual-r2", vs_previous={names[0]: "better: fog lifted"}),
                          start=False, keep=True, extra_reads=[notes_p] + prev_reads, blind=full("fix_needed", 3)["scores"])
        ok(sv and sv["shots_folder"].endswith("/final") and sv.get("vs_previous"),
           "capture: reviewer that also opened the previous round's PNGs is stored (current folder, vs_previous kept)")
        tool(root, "review.py", "start", "P1-visual-r3")
        out, sv = capture(full("fix_needed", 3, rid="P1-visual-r3"), start=False, reads=names[:-1], extra_reads=prev_reads)
        ok(rejected((out, sv)), "capture: a full set only from the previous round's snapshot does not count")
        r = tool(root, "review.py", "start", "P1-visual-r3")
        ok(r.returncode == 2 and "next round is P1-visual-r4" in r.stdout and
           not os.path.exists(os.path.join(revdir, "P1-visual-r3.pending")),
           "review.py start: a round number is never reused (r3 again refused, r4 is next)")
        tool(root, "review.py", "start", "P1-visual-r4")
        out, sv = capture(full("fix_needed", 3, rid="P1-visual-r4"), start=False, keep=True,
                          folder=os.path.join(rounds, "P1-visual-r4"), extra_reads=prev_reads,
                          blind=full("fix_needed", 3)["scores"])
        ok(sv and sv["shots_folder"].endswith("rounds/p1-visual-r4"), "capture: this round's snapshot folder counts")
        r = tool(root, "review.py", "start", "P1-visual-r5")
        ok(r.returncode == 0 and "rounds/P1-visual-r4/" in r.stdout and "none stored" not in open(os.path.join(
            rounds, "P1-visual-r5", "previous-round.md"), encoding="utf-8").read(),
           "review.py start: previous = the latest earlier round: " + r.stdout + r.stderr)
        r = tool(root, "review.py", "start", "P1-visual-r6")
        ok(r.returncode == 2 and "still pending" in r.stdout, "review.py start: no new round while one is pending")
        os.remove(os.path.join(revdir, "P1-visual-r5.pending"))

        # --- phase close: stored pass, perf record, review caps, below bar never halts the run ---
        reset_reviews()
        plan_p = os.path.join(root, "PLAN.md")

        def plan(p1: str, p2: str = " ", p3: str = " ") -> None:
            with open(plan_p, "w", encoding="utf-8") as f:
                f.write("## Run rules\n1. Never wait.\n\n## Phases\n- [x] **P0: Foundation**\n"
                        "- [%s] **P1: Style slice** [visual]\n- [%s] **P2: Content** [visual]\n- [%s] **P3: Docs**\n"
                        % (p1, p2, p3))
        plan(" ")
        r = tool(root, "review.py", "close", "P3")
        ok(r.returncode == 1 and "style slice P1 is still open" in r.stdout, "close: no phase after a still-open style slice")
        r = tool(root, "review.py", "close", "P1")
        ok(r.returncode == 1 and "no stored visual-reviewer pass" in r.stdout, "close: visual phase refused without a stored pass")
        capture(stage_a_full(), keep=True)
        r = tool(root, "review.py", "close", "P1")
        ok(r.returncode == 1 and "P1-visual-r<N>" in r.stdout, "close: style slice needs the main-stage pass too, not only stage A")
        capture(full(), keep=True)
        r = tool(root, "review.py", "close", "P1")
        ok(r.returncode == 1 and "perf record" in r.stdout, "close: visual phase refused without a perf record")
        bench = os.path.join(root, "bench.log")
        with open(bench, "w") as f:
            f.write("noise\nBENCH avg_fps=40.0 low1_fps=20.0 frames=600 shot=x\n")
        r = tool(root, "perf_gate.py", "--phase", "P1", bench)
        ok(r.returncode == 1 and "PERF FAIL" in r.stdout and tool(root, "review.py", "close", "P1").returncode == 1,
           "perf_gate: below the kit.json thresholds fails and the phase stays open")
        with open(bench, "w") as f:
            f.write("BENCH avg_fps=75.0 low1_fps=50.0 frames=600 shot=x\n")
        r = tool(root, "perf_gate.py", "--phase", "P1", bench)
        ok(r.returncode == 0 and "PERF OK" in r.stdout, "perf_gate: above the thresholds passes")
        capture(full("fix_needed", 3, rid="P1-visual-r2"), keep=True)
        ok(tool(root, "review.py", "close", "P1").returncode == 1, "close: the latest round counts (r2 fix_needed after r1 pass)")
        os.remove(os.path.join(revdir, "P1-visual-r2.json"))
        r = tool(root, "review.py", "close", "P1")
        ok(r.returncode == 0 and "- [x] **P1: Style slice** [visual]\n" in open(plan_p, encoding="utf-8").read(),
           "close: stored stage A + main passes and perf record close the style slice ([x], not below bar)")
        ok(tool(root, "review.py", "close", "P2").returncode == 1 and tool(root, "review.py", "close", "P3").returncode == 0,
           "close: a later visual phase still needs its own pass; a non-visual phase closes")
        os.remove(os.path.join(revdir, "P1-visual-r1.json"))
        plan("x")
        out = hook(root, "stop_guard.py", {})
        ok(out.get("decision") == "block" and "close check" in out.get("reason", "") and "P1" in out.get("reason", ""),
           "stop: a visual phase marked [x] by hand without a stored pass blocks the stop")
        plan("-")
        out = hook(root, "stop_guard.py", {})
        ok(out.get("decision") == "block" and "Open phase: P2" in out.get("reason", "") and "stops here" not in out["reason"],
           "stop: a style slice marked [-] does not halt the run (generic continue on the next phase)")
        r = tool(root, "review.py", "close", "P3")
        ok(r.returncode == 0, "close: phases after a [-] style slice may close")

        # caps: stage A 2 rounds, main stage 2, P2 main stage 1 (per-phase override)
        reset_reviews()
        plan(" ")
        cfg["visual"]["review_caps"] = {"stage_a": 2, "default": 2, "phases": {"P2": 1}}
        cfg["visual"]["on_cap"] = "proceed_with_known_issues"
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        capture(stage_a_full("fix_needed", 3, rid="P1-visualA-r1", top_problems=["shot-01: flat light"]), keep=True)
        capture(stage_a_full("fix_needed", 3, rid="P1-visualA-r2", top_problems=["shot-02: murky bank"]), keep=True)
        r = tool(root, "review.py", "start", "P1-visualA-r3")
        ok(r.returncode == 3 and "START REFUSED" in r.stdout and "main stage" in r.stdout and
           not os.path.exists(os.path.join(revdir, "P1-visualA-r3.pending")),
           "review caps: stage A round past its cap refused; told to go on with the main stage")
        out = hook(root, "stop_guard.py", {})
        ok(out.get("decision") == "block" and "stage A of P1 is at its review cap" in out.get("reason", "") and
           "main stage" in out["reason"], "stop: stage A at its cap -> continue with the main stage (no halt)")
        capture(full("fix_needed", 3, rid="P1-visual-r1"), keep=True)
        r = tool(root, "review.py", "close", "P1")
        ok(r.returncode == 1 and "no stored visual-reviewer pass for P1-visual-r<N>" in r.stdout and "round 1 of 2" in r.stdout,
           "close: main stage below its cap still needs a pass (its own budget, regardless of stage A)")
        capture(full("fix_needed", 3, rid="P1-visual-r2", top_problems=["shot-03: grey clouds"]), keep=True)
        r = tool(root, "review.py", "start", "P1-visual-r3")
        ok(r.returncode == 3 and "--known-issues" in r.stdout, "review caps: main stage past its cap refused -> close with known issues")
        out = hook(root, "stop_guard.py", {})
        ok(out.get("decision") == "block" and "--known-issues" in out.get("reason", ""),
           "stop: both stages at their caps -> close below bar and continue (never ends the run)")
        r = tool(root, "review.py", "close", "P1")
        ok(r.returncode == 1 and "hit its cap" in r.stdout and "--known-issues" in r.stdout,
           "close: a capped stage is not closed silently; --known-issues is required")
        r = tool(root, "review.py", "close", "P1", "--known-issues")
        rs = json.load(open(os.path.join(root, "run-state.json"), encoding="utf-8"))
        p1 = rs["phases"].get("P1", {})
        ok(r.returncode == 0 and "below bar" in r.stdout and
           "- [x] **P1: Style slice** [visual] (below bar)" in open(plan_p, encoding="utf-8").read() and
           p1.get("status") == "done_below_bar" and any("grey clouds" in k for k in p1.get("known_issues", [])) and
           any("flat light" not in k and "murky bank" in k for k in p1["known_issues"]) and
           p1.get("last_scores", {}).get("main") and p1.get("rounds") == {"stage_a": "2/2", "main": "2/2"},
           "close --known-issues: [x] (below bar), run-state done_below_bar with known issues, last scores, rounds")
        ok(json.load(open(os.path.join(revdir, "P1-visual-r2.json"), encoding="utf-8"))["verdict"] == "fix_needed",
           "close --known-issues: honest scores, the stored verdict is never turned into a pass")
        h = tool(root, "review.py", "headline").stdout
        ok(h.startswith("BELOW BAR") and "grey clouds" in h and "murky bank" not in h and "flat light" not in h and
           "composition/style gap vs the reference" in h and cal_item in h,
           "headline: leads with the main stage's open problems and the composition gap, never stale stage-A ones: " + h)
        out = hook(root, "stop_guard.py", {})
        ok(out.get("decision") == "block" and "Open phase: P2" in out.get("reason", "") and "close check" not in out["reason"],
           "stop: a below-bar style slice passes the close check; the run continues with P2")
        ok(tool(root, "review.py", "close", "P3").returncode == 0, "close: a later phase closes after a below-bar style slice")
        final2 = os.path.join(root, "docs", "shots", run_id, "P2", "final")
        os.makedirs(final2, exist_ok=True)
        tool(root, "review.py", "start", "P2-visual-r1")
        capture(full("fix_needed", 3, rid="P2-visual-r1"), start=False, keep=True)
        r = tool(root, "review.py", "start", "P2-visual-r2")
        ok(r.returncode == 3, "review caps: per-phase override (P2 main stage 1 round)")
        with open(bench, "w") as f:
            f.write("BENCH avg_fps=75.0 low1_fps=50.0 frames=600 shot=x\n")
        tool(root, "perf_gate.py", "--phase", "P2", bench)
        r = tool(root, "review.py", "close", "P2", "--known-issues")
        ok(r.returncode == 0 and json.load(open(os.path.join(root, "run-state.json"), encoding="utf-8"))["phases"]["P2"]["status"]
           == "done_below_bar", "close --known-issues: a later visual phase at its cap closes below bar too")
        ok(hook(root, "stop_guard.py", {}) == {}, "stop: every phase closed (below bar included) -> the run may end")
        reset_reviews()
        plan(" ")
        cfg["visual"]["stage_a_min_score"] = 3
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        ok(capture(stage_a_full("pass", 3))[1] is not None and rejected(capture(full("pass", 3))),
           "visual.stage_a_min_score: stage A passes at its own floor; the main stage keeps rubric_min_score")
        cfg["visual"].pop("stage_a_min_score")
        cfg["visual"].pop("review_caps")
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))

        # --- the cap counts only real reviews: no skipping ahead, no below-bar close without a captured verdict ---
        def rs_now() -> dict:
            return json.load(open(os.path.join(root, "run-state.json"), encoding="utf-8"))
        reset_reviews()
        plan(" ")
        r = tool(root, "review.py", "start", "P1-visual-r6")
        ok(r.returncode == 2 and "START REFUSED" in r.stdout and "next round is P1-visual-r1" in r.stdout and
           not os.path.exists(os.path.join(revdir, "P1-visual-r6.pending")) and "P1-visual-r6" not in rs_now().get("reviews", {}),
           "exploit: start r6 on a fresh stage refused (only the next round, r1, may start)")
        ok(tool(root, "review.py", "start", "P1-visual-r1").returncode == 0 and
           tool(root, "review.py", "unreviewed", "P1-visual-r1").returncode == 0, "start r1 -> unreviewed")
        r = tool(root, "review.py", "close", "P1", "--known-issues")
        ok(r.returncode == 1 and "--known-issues refused" in r.stdout and "no real visual-reviewer verdict" in r.stdout and
           "- [ ] **P1" in open(plan_p, encoding="utf-8").read() and rs_now()["phases"].get("P1") is None,
           "exploit: start r1 -> unreviewed -> close --known-issues refused (no captured verdict)")
        st = kitlib.stage_state(cfg, "P1", "")
        ok(st["rounds"] == 0 and st["started"] == 1 and st["next"] == 2 and not st["capped"],
           "stage state: an unreviewed round is started but not counted")
        # two rounds in a row without a captured verdict -> run blocked (watcher exit 3), never a silent dead end
        ok(tool(root, "review.py", "start", "P1-visual-r2").returncode == 0, "start r2 after one unreviewed round")
        r = tool(root, "review.py", "unreviewed", "P1-visual-r2")
        rs = rs_now()
        ok(r.returncode == 3 and "RUN BLOCKED" in r.stdout and rs.get("status") == "blocked" and
           "2 consecutive rounds" in rs.get("blocked_reason", "") and "P1-visual-r1" in rs["blocked_reason"] and
           "P1-visual-r2" in rs["blocked_reason"] and rs.get("blocked_at"),
           "two unreviewed rounds in a row -> run-state status blocked with the reason: " + rs.get("blocked_reason", ""))
        r = tool(root, "review.py", "start", "P1-visual-r3")
        ok(r.returncode == 3 and "run is blocked" in r.stdout and not os.path.exists(os.path.join(revdir, "P1-visual-r3.pending")),
           "blocked: no further round starts")
        ok(hook(root, "stop_guard.py", {}) == {} and any(x["outcome"] == "allowed" and "blocked" in x.get("reason", "")
                                                         for x in log_lines(root) if x["hook"] == "stop_guard"),
           "stop: a blocked run may end (the watcher reports blocked, exit 3)")
        # the same through the hook: two invalid captures in a row
        reset_reviews()
        capture(full(score=3), mode="handback", rid="P1-visual-r1")
        ok(rs_now().get("status") != "blocked", "one invalid round does not block the run")
        capture(full(score=3, rid="P1-visual-r2"), mode="handback")
        rs = rs_now()
        ok(rs.get("status") == "blocked" and "P1-visual-r1 (invalid)" in rs.get("blocked_reason", "") and
           any(x["outcome"] == "run_blocked" for x in log_lines(root)),
           "two invalid captures in a row -> blocked by the SubagentStop hook, logged")
        # only verdicted rounds count against the cap (main stage of P2, cap 2)
        reset_reviews()
        plan("-")
        cfg["visual"]["review_caps"] = {"stage_a": 3, "default": 2, "phases": {}}
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        capture(full("fix_needed", 3, rid="P2-visual-r1", top_problems=["shot-02: flat water"]), keep=True)
        ok(tool(root, "review.py", "start", "P2-visual-r2").returncode == 0 and
           tool(root, "review.py", "unreviewed", "P2-visual-r2").returncode == 0, "P2: r1 reviewed, r2 unreviewed")
        r = tool(root, "review.py", "start", "P2-visual-r3")
        ok(r.returncode == 0, "cap: an unreviewed round does not use the cap (r3 starts with cap 2): " + r.stdout)
        capture(full("fix_needed", 3, rid="P2-visual-r3", top_problems=["shot-02: water still flat"]), start=False, keep=True)
        st = kitlib.stage_state(cfg, "P2", "")
        r = tool(root, "review.py", "start", "P2-visual-r4")
        ok(st["rounds"] == 2 and st["started"] == 3 and st["capped"] and r.returncode == 3 and "2 reviewed rounds" in r.stdout,
           "cap counts only verdicted rounds: 2 reviewed of 3 started -> capped, r4 refused")
        with open(bench, "w") as f:
            f.write("BENCH avg_fps=75.0 low1_fps=50.0 frames=600 shot=x\n")
        tool(root, "perf_gate.py", "--phase", "P2", bench)
        rp_path = os.path.join(root, "run-report.json")
        with open(rp_path, "w", encoding="utf-8") as f:
            json.dump({"run": "r1", "result": "done", "known_issues": ["older issue"]}, f)
        r = tool(root, "review.py", "close", "P2", "--known-issues")
        rep = json.load(open(rp_path, encoding="utf-8"))
        ok(r.returncode == 0 and rs_now()["phases"]["P2"]["rounds"] == {"main": "2/2"} and
           list(rep)[:2] == ["headline", "below_bar"] and rep["headline"].startswith("BELOW BAR") and
           "P2" in rep["headline"] and rep["below_bar"] == ["P2"] and "older issue" in rep["known_issues"] and
           any("water still flat" in k for k in rep["known_issues"]),
           "below bar: close --known-issues puts headline + below_bar first in run-report.json: %s" % list(rep)[:3])
        with open(rp_path, "w", encoding="utf-8") as f:
            json.dump({"run": "r1", "result": "done"}, f)
        r = tool(root, "review.py", "headline")
        rep = json.load(open(rp_path, encoding="utf-8"))
        ok(r.returncode == 0 and r.stdout.startswith("BELOW BAR") and list(rep)[0] == "headline" and rep["below_bar"] == ["P2"],
           "review.py headline: a report written later gets the below-bar headline first")
        os.remove(rp_path)
        cfg["visual"].pop("review_caps")
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))

        # --- stored verdicts: sha256 logged by the hook, checked by close (tamper / forge) ---
        reset_reviews()
        plan("-")
        capture(full(rid="P2-visual-r1"), keep=True)
        vpath = os.path.join(revdir, "P2-visual-r1.json")
        logged = [x for x in log_lines(root) if x["hook"] == "subagent_stop" and x["outcome"] == "stored"]
        ok(logged and logged[-1].get("review_id") == "P2-visual-r1" and logged[-1].get("sha256") == kitlib.file_sha256(vpath),
           "hooks.log.jsonl: the stored verdict's sha256 is logged")
        original = open(vpath, "rb").read()
        tampered = json.loads(original)
        tampered["scores"][names[0]][items[0]] = 5
        with open(vpath, "w", encoding="utf-8") as f:
            json.dump(tampered, f, indent=2)
        r = tool(root, "review.py", "close", "P2")
        ok(r.returncode == 1 and "changed after the SubagentStop hook stored it" in r.stdout and
           "- [ ] **P2" in open(plan_p, encoding="utf-8").read(), "close: a verdict edited after storing is refused (tamper)")
        with open(vpath, "wb") as f:
            f.write(original)
        with open(os.path.join(revdir, "P2-visual-r2.json"), "w", encoding="utf-8") as f:
            json.dump(dict(json.loads(original), review_id="P2-visual-r2"), f)
        r = tool(root, "review.py", "close", "P2")
        ok(r.returncode == 1 and "P2-visual-r2 has no sha256 logged" in r.stdout,
           "close: a verdict file the hook never stored (forged/copied) is refused")
        os.remove(os.path.join(revdir, "P2-visual-r2.json"))
        r = tool(root, "review.py", "close", "P2")
        ok(r.returncode == 0 and "- [x] **P2" in open(plan_p, encoding="utf-8").read(),
           "close: stored verdict matching its logged sha256 closes the phase")
        reset_reviews()

        # --- guard: run-state is written only by hooks and tools; text mentions are not writes; tags are not moved ---
        def fguard(tool_name: str, path: str, key: str = "file_path") -> dict:
            return hook(root, "pre_tool_guard.py", {"tool_name": tool_name, "tool_input": {key: path, "content": "{}"}})
        ok(denied(fguard("Write", ".claude/run-state/reviews/P1-visual-r1.json")), "guard: Write into run-state denied")
        ok(denied(fguard("Edit", os.path.join(root, ".claude", "run-state", "reviews", "P1-visual-r1.json"))),
           "guard: Edit of a stored verdict (absolute path) denied")
        ok(denied(fguard("MultiEdit", ".claude/run-state/spend.json")), "guard: MultiEdit of the spend ledger denied")
        ok(denied(fguard("NotebookEdit", ".claude/run-state/x.ipynb", "notebook_path")), "guard: NotebookEdit into run-state denied")
        ok(not denied(fguard("Write", "src/main.py")) and not denied(fguard("Edit", "run-state.json")),
           "guard: ordinary file writes (and the bots' run-state.json) allowed")
        for cmd in ('echo {} > .claude/run-state/reviews/P1-visual-r1.json', "echo x > .claude/run-state/reviews/a.json",
                    "cp v.json .claude/run-state/reviews/", "tee .claude/run-state/x", "sed -i s/a/b/ .claude/run-state/x",
                    "echo x | tee -a .claude/run-state/spend.json", "printf x >> .claude/run-state/x 2>&1",
                    "cd .claude/run-state && echo x > a.json", "cd .claude && rm -f run-state/reviews/a.pending",
                    "mv .claude/run-state/reviews/P1-visual-r1.pending /tmp/x", "touch .claude/run-state/reviews/P1-visual-r9.pending",
                    "dd if=/dev/zero of=.claude/run-state/x bs=1 count=1", "bash -c 'echo x > .claude/run-state/x'",
                    "find .claude/run-state -name '*.pending' -delete", "truncate -s 0 .claude/run-state/spend.json",
                    "ln -sf /tmp/x .claude/run-state/x", "install -m 644 v.json .claude/run-state/reviews/a.json"):
            ok(denied(guard(cmd)), "guard: shell write into run-state denied: " + cmd)
        for cmd, sh in ((r"Copy-Item v.json .claude\run-state\reviews\P1-visual-r1.json", "PowerShell"),
                        ("Copy-Item -Path v.json -Destination .claude/run-state/reviews/", "PowerShell"),
                        ("Set-Content -Path .claude/run-state/x.json -Value '{}'", "PowerShell"),
                        ("'{}' | Out-File .claude/run-state/x.json", "PowerShell"),
                        ("Remove-Item .claude/run-state/reviews/P1-visual-r1.pending", "PowerShell"),
                        ("echo x *> .claude/run-state/x.txt", "PowerShell")):
            ok(denied(guard(cmd, sh)), "guard: PowerShell write into run-state denied: " + cmd)
        for cmd in ("cat > .verify/P0-foundation-r1.json <<'EOF'\n{\"note\": \"stored in .claude/run-state/reviews/P0-foundation-r1.json\"}\nEOF",
                    "cat >> PROGRESS.md <<EOF\n- verdict captured into .claude/run-state/reviews/ (cp by the hook)\nEOF",
                    "grep -r foo .claude/run-state", "cat .claude/run-state/spend.json", "ls -la .claude/run-state/reviews",
                    'git commit -m "docs: never write .claude/run-state > by hand; cp is denied"',
                    "echo 'see .claude/run-state/reviews' > notes.txt", "printf '%s\\n' .claude/run-state >> PROGRESS.md",
                    "python tools/review.py start P1-visual-r1", "python3 tools/review.py list > .verify/list.json",
                    "cp .claude/run-state/reviews/P0-plan-r1.json .verify/", "wc -l .claude/run-state/hooks.log.jsonl 2>/dev/null"):
            ok(not denied(guard(cmd)), "guard: no write target in run-state, allowed: " + cmd.split("\n")[0])
        ok(not denied(guard("Get-Content .claude/run-state/spend.json | Out-File .verify/spend.txt", "PowerShell")),
           "guard: PowerShell read from run-state into another file allowed")
        ok(denied(guard("git tag -f r1-start")) and denied(guard("git tag -d r1-lighting-lock")),
           "guard: moving or deleting a tag denied")
        ok(not denied(guard("git tag r1-p1")), "guard: creating a tag allowed")
        ok(not denied(guard("git commit -F - <<'EOF'\nnever git push --force here\nEOF")),
           "guard: a force push mentioned in a commit message heredoc is text")

        # --- art gate: content, then frozen against the run tags (throwaway git repo) ---
        bible = os.path.join(root, "ART-BIBLE.md")
        shutil.copy(os.path.join(root, "templates", "ART-BIBLE.md"), bible)
        r = tool(root, "art_gate.py", "--draft")
        ok(r.returncode == 1 and "not approved" in r.stdout and "placeholder" in r.stdout, "art gate: unfilled template fails")
        filled = "".join("## %s\nFilled in.\n\n" % s for s in art_gate.SECTIONS if s not in ("Reference images", "Approval"))
        filled = ("# Art bible\n\n## Reference images\n| `docs/refs/hero.png` | hero character |\n\n" + filled +
                  "## Approval\n<!-- Approved: <name>, <YYYY-MM-DD> -->\nApproved: Owner Name, 2026-01-02\n")
        with open(bible, "w", encoding="utf-8") as f:
            f.write(filled)
        refs = os.path.join(root, "docs", "refs")
        if os.path.isdir(refs):
            shutil.rmtree(refs)
        r = tool(root, "art_gate.py", "--draft")
        ok(r.returncode == 1 and "reference image not found: docs/refs/hero.png" in r.stdout, "art gate: missing ref image fails")
        os.makedirs(refs, exist_ok=True)
        open(os.path.join(refs, "hero.png"), "wb").close()
        r = tool(root, "art_gate.py", "--draft")
        ok(r.returncode == 0 and "ART GATE DRAFT OK" in r.stdout and "ART GATE OK" not in r.stdout,
           "art gate --draft: filled, approved bible passes the content check but never prints OK")
        r = tool(root, "art_gate.py")
        ok(r.returncode == 1 and "-start" in r.stdout, "art gate: no git repo / start tag -> FAIL, not OK")
        with open(bible, "w", encoding="utf-8") as f:
            f.write(filled.replace("Approved: Owner Name, 2026-01-02", "Approved: <name>, <YYYY-MM-DD>"))
        ok(tool(root, "art_gate.py", "--draft").returncode == 1, "art gate: placeholder approval line fails")
        with open(bible, "w", encoding="utf-8") as f:
            f.write(filled.replace("## Palette\nFilled in.\n", ""))
        r = tool(root, "art_gate.py", "--draft")
        ok(r.returncode == 1 and "section missing: ## Palette" in r.stdout, "art gate: missing section fails")
        with open(bible, "w", encoding="utf-8") as f:
            f.write(filled)
        r = tool(root, "art_gate.py", "--draft", "--shots")
        ok(r.returncode == 1 and "ref not found" in r.stdout, "art gate --shots: missing shot refs fail")
        for s in shots["shots"]:
            for ref in s["refs"]:
                open(os.path.join(root, ref), "wb").close()
        r = tool(root, "art_gate.py", "--draft", "--shots")
        ok(r.returncode == 0 and "DRAFT OK" in r.stdout, "art gate --shots: complete shot set passes: " + r.stdout)

        g = os.path.join(tmp, "gate")
        for d in ("tools", os.path.join("docs", "refs"), os.path.join("docs", "shots")):
            os.makedirs(os.path.join(g, d))
        shutil.copy(os.path.join(root, "tools", "art_gate.py"), os.path.join(g, "tools"))
        shutil.copytree(os.path.join(root, "docs", "refs"), os.path.join(g, "docs", "refs"), dirs_exist_ok=True)
        shutil.copy(os.path.join(root, "docs", "shots", "shots.json"), os.path.join(g, "docs", "shots"))
        gkit = dict(kitcfg, run="r1", visual=dict(vis0, required=True))

        def gwrite(rel: str, text: str) -> None:
            with open(os.path.join(g, rel), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)

        def gkit_write(**vis) -> None:
            gwrite("kit.json", json.dumps(dict(gkit, visual=dict(gkit["visual"], **vis)), indent=1))

        def gate(*a) -> subprocess.CompletedProcess:
            return tool(g, "art_gate.py", *a)
        gkit_write()
        gwrite("ART-BIBLE.md", filled.replace("Approved: Owner Name, 2026-01-02", "Approved: <name>, <YYYY-MM-DD>"))
        git(g, "init", "-q")
        git(g, "config", "user.email", "t@example.com")
        git(g, "config", "user.name", "t")
        git(g, "config", "core.autocrlf", "false")
        git(g, "add", "-A")
        git(g, "commit", "-qm", "owner: bible draft")
        git(g, "tag", "r1-start")
        gwrite("ART-BIBLE.md", filled)
        git(g, "commit", "-qam", "approve during the run")
        r = gate()
        ok(r.returncode == 1 and "Approved line was not present" in r.stdout,
           "art gate: Approved line added after the start tag fails: " + r.stdout)
        gkit = dict(gkit, run="r2")
        gkit_write()
        git(g, "commit", "-qam", "owner: next run")
        git(g, "tag", "r2-start")
        r = gate("--shots")
        ok(r.returncode == 0 and "ART GATE OK" in r.stdout, "art gate: approved at the start tag, nothing changed -> OK: " + r.stdout)
        gkit = dict(gkit, run="r3")
        gkit_write()
        r = gate()
        ok(r.returncode == 1 and "tag r3-start missing" in r.stdout, "art gate: missing start tag fails")
        gkit = dict(gkit, run="r2")
        gkit_write()
        with open(os.path.join(g, "ART-BIBLE.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write("\nA new rule.\n")
        r = gate()
        ok(r.returncode == 1 and "changed since r2-start: ART-BIBLE.md" in r.stdout, "art gate: bible changed since the start tag fails")
        git(g, "checkout", "--", "ART-BIBLE.md")
        open(os.path.join(g, "docs", "refs", "extra.png"), "wb").close()
        r = gate()
        ok(r.returncode == 1 and "docs/refs/extra.png" in r.stdout, "art gate: new (untracked) ref since the start tag fails")
        os.remove(os.path.join(g, "docs", "refs", "extra.png"))
        with open(os.path.join(g, "docs", "refs", "hero.png"), "wb") as f:
            f.write(b"changed")
        r = gate()
        ok(r.returncode == 1 and "docs/refs/hero.png" in r.stdout, "art gate: changed ref since the start tag fails")
        git(g, "checkout", "--", "docs/refs/hero.png")
        gkit_write(required=False)
        r = gate()
        ok(r.returncode == 1 and "SKIPPED" not in r.stdout and "visual\" block changed" in r.stdout,
           "art gate: switching visual.required off mid-run fails (not SKIPPED)")
        gkit_write(rubric_min_score=2)
        ok(gate().returncode == 1, "art gate: lowering the rubric floor mid-run fails")
        gkit_write()
        ok(gate().returncode == 0, "art gate: restored inputs pass again")
        sj = os.path.join(g, "docs", "shots", "shots.json")
        s2 = json.load(open(sj, encoding="utf-8"))
        s2["shots"][0]["pos"] = [1, 2, 3]
        gwrite(os.path.join("docs", "shots", "shots.json"), json.dumps(s2))
        ok(gate("--shots").returncode == 0, "art gate: shot set may change before the lighting lock (P0)")
        git(g, "commit", "-qam", "P0 shot set")
        git(g, "tag", "r2-lighting-lock")
        s2["shots"][0]["pos"] = [9, 9, 9]
        gwrite(os.path.join("docs", "shots", "shots.json"), json.dumps(s2))
        r = gate()
        ok(r.returncode == 1 and "shot set changed since r2-lighting-lock" in r.stdout,
           "art gate: shot set changed after the lighting lock fails")
        git(g, "checkout", "--", "docs/shots/shots.json")
        ok(gate().returncode == 0, "art gate: frozen shot set passes")

        # --- heartbeat: one-file commits to <branch>-heartbeat via plumbing; working tree, index, run branch untouched ---
        hb = os.path.join(tmp, "hb")
        bare = os.path.join(tmp, "hb-origin.git")
        git(tmp, "init", "-q", "--bare", bare)
        os.makedirs(os.path.join(hb, ".claude", "hooks"))
        for f in ("kitlib.py", "heartbeat.py"):
            shutil.copy(os.path.join(root, ".claude", "hooks", f), os.path.join(hb, ".claude", "hooks"))
        with open(os.path.join(hb, "kit.json"), "w", encoding="utf-8") as f:
            json.dump({"run": "r9", "heartbeat_min": 10}, f)
        with open(os.path.join(hb, "run-state.json"), "w", encoding="utf-8") as f:
            json.dump({"run": "r9", "status": "in_progress"}, f)
        with open(os.path.join(hb, ".gitignore"), "w", encoding="utf-8") as f:
            f.write(".claude/run-state/\n__pycache__/\n")
        git(hb, "init", "-q")
        git(hb, "config", "user.email", "t@example.com")
        git(hb, "config", "user.name", "t")
        git(hb, "checkout", "-q", "-b", "r9-run")
        git(hb, "add", "-A")
        git(hb, "commit", "-qm", "run")
        git(hb, "remote", "add", "origin", bare)
        head0 = git(hb, "rev-parse", "HEAD")

        def hb_ref() -> str:
            r = subprocess.run(["git", "--git-dir", bare, "rev-parse", "--verify", "--quiet", "refs/heads/r9-run-heartbeat"],
                               capture_output=True, text=True)
            return r.stdout.strip()

        def wait_ref(other: str = "") -> str:
            for _ in range(100):
                sha = hb_ref()
                if sha and sha != other and not os.path.exists(os.path.join(hb, ".claude", "run-state", "heartbeat.lock")):
                    return sha
                time.sleep(0.25)
            return ""
        t0 = time.time()
        out = hook(hb, "heartbeat.py", {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s-hb"})
        ok(out == {} and time.time() - t0 < 5, "heartbeat: the hook returns at once with no output")
        first = wait_ref()
        beat = json.load(open(os.path.join(hb, ".claude", "run-state", "heartbeat.json"), encoding="utf-8"))
        ok(first and beat.get("session_id") == "s-hb" and beat.get("branch") == "r9-run" and beat.get("head_sha") == head0
           and beat.get("last_tool") == "Bash" and beat.get("run_status") == "in_progress" and beat.get("ts_utc"),
           "heartbeat: heartbeat.json written and pushed to r9-run-heartbeat")
        shown = subprocess.run(["git", "--git-dir", bare, "show", "r9-run-heartbeat:heartbeat.json"], capture_output=True, text=True)
        ok(json.loads(shown.stdout).get("session_id") == "s-hb", "heartbeat: the branch holds heartbeat.json only")
        ok(git(hb, "rev-parse", "HEAD") == head0 and git(hb, "rev-parse", "--abbrev-ref", "HEAD") == "r9-run" and
           git(hb, "status", "--porcelain") == "", "heartbeat: run branch, index and working tree untouched")
        m0 = os.path.getmtime(os.path.join(hb, ".claude", "run-state", "heartbeat.json"))
        hook(hb, "heartbeat.py", {"tool_name": "Read"})
        ok(os.path.getmtime(os.path.join(hb, ".claude", "run-state", "heartbeat.json")) == m0,
           "heartbeat: at most every heartbeat_min minutes")
        old = time.time() - 11 * 60
        os.utime(os.path.join(hb, ".claude", "run-state", "heartbeat.json"), (old, old))
        hook(hb, "heartbeat.py", {"tool_name": "Edit"})
        second = wait_ref(first)
        parent = subprocess.run(["git", "--git-dir", bare, "rev-parse", second + "^"], capture_output=True, text=True).stdout.strip()
        ok(second and parent == first, "heartbeat: the next beat is a fast-forward commit on the previous one (no force)")
        with open(os.path.join(hb, "kit.json"), "w", encoding="utf-8") as f:
            json.dump({"run": "r9", "heartbeat": False}, f)
        os.utime(os.path.join(hb, ".claude", "run-state", "heartbeat.json"), (old, old))
        hook(hb, "heartbeat.py", {"tool_name": "Bash"})
        ok(abs(os.path.getmtime(os.path.join(hb, ".claude", "run-state", "heartbeat.json")) - old) < 2,
           'heartbeat: "heartbeat": false disables it')

        # --- watcher and launchers (bash) ---
        bash = shutil.which("bash")
        if bash and os.name != "nt":
            for s in (("tools", "watch", "run_watch.sh"), ("tools", "headless", "launch.sh"), ("tools", "headless", "resume.sh")):
                r = subprocess.run([bash, "-n", os.path.join(root, *s)], capture_output=True, text=True)
                ok(r.returncode == 0, "bash -n %s (%s)" % ("/".join(s), r.stderr.strip()))
            home = os.path.join(tmp, "home")
            fake = os.path.join(tmp, "fake-run")
            os.makedirs(os.path.join(fake, ".claude", "run-state"))
            slug = "".join(c if c.isalnum() else "-" for c in os.path.realpath(fake))
            logdir = os.path.join(home, ".claude", "projects", slug)
            os.makedirs(os.path.join(logdir, "s1", "subagents"))

            def watch(status: str, age_min: float, *extra: str, rs_extra=None):
                with open(os.path.join(fake, "run-state.json"), "w", encoding="utf-8") as f:
                    json.dump(dict({"run": "r1", "status": status}, **(rs_extra or {})), f)
                for p in (os.path.join(logdir, "s1.jsonl"), os.path.join(logdir, "s1", "subagents", "a.jsonl")):
                    open(p, "a").close()
                    t = time.time() - age_min * 60
                    os.utime(p, (t, t))
                r = subprocess.run([bash, os.path.join(root, "tools", "watch", "run_watch.sh"), "--repo", "o/fake",
                                    "--branch", "r1-run", "--mode", "box", "--project-dir", fake, "--session-id", "s1",
                                    "--once", "--offline"] + list(extra), capture_output=True, text=True,
                                   env=dict(os.environ, HOME=home), timeout=60)
                lines = [x for x in r.stdout.splitlines() if x.strip()]
                return r.returncode, (json.loads(lines[-1]) if len(lines) == 1 else {"_stdout": r.stdout}), r.stderr
            rc, j, err = watch("done", 1)
            ok(rc == 0 and j.get("reason") == "done" and j.get("repo") == "o/fake" and j.get("session_id") == "s1" and
               j.get("last_log_write"), "watcher --once: run-state done -> exit 0, one JSON line (%s)" % err.strip()[-300:])
            rc, j, _ = watch("blocked", 1)
            ok(rc == 3 and j.get("reason") == "blocked", "watcher --once: blocked -> exit 3")
            rc, j, _ = watch("in_progress", 45)
            ok(rc == 2 and j.get("reason") == "stall", "watcher --once: no session-log write for 45 min -> stall, exit 2")
            rc, j, _ = watch("in_progress", 2)
            ok(rc == 1 and j.get("reason") == "running", "watcher --once: fresh log -> still running (exit 1)")
            open(os.path.join(fake, ".claude", "HALT"), "w").close()
            rc, j, _ = watch("in_progress", 2)
            ok(rc == 3 and j.get("reason") == "halted", "watcher --once: .claude/HALT -> halted, exit 3")
            os.remove(os.path.join(fake, ".claude", "HALT"))
            rc, j, _ = watch("in_progress", 2, "--interval-sec", "abc")
            ok(rc == 4 and j.get("reason") == "error", "watcher: invalid config -> error, exit 4")
            rc, j, _ = watch("in_progress", 2)
            ok(j.get("stall_min") == 30 and j.get("stall_min_source") == "--stall-min" and j.get("pid") is None and
               j.get("pid_alive") is None and j.get("below_bar") == [] and j.get("headline") is None,
               "watcher JSON: stall limit used (fallback --stall-min), pid/pid_alive null without session.json, no below bar: %s" % j)
            with open(os.path.join(fake, "kit.json"), "w", encoding="utf-8") as f:
                json.dump({"stall_min": {"default": 20, "phases": {"P3": 90}}}, f)
            rc, j, _ = watch("in_progress", 45, rs_extra={"current_phase": "P3: Bake lightmaps"})
            ok(rc == 1 and j.get("stall_min") == 90 and j.get("phase") == "P3" and "phases.P3" in j.get("stall_min_source", ""),
               "watcher: per-phase stall limit from kit.json (P3 90 min: 45 min quiet is still running): %s" % j)
            rc, j, _ = watch("in_progress", 25, rs_extra={"current_phase": "P2"})
            ok(rc == 2 and j.get("stall_min") == 20 and "default" in j.get("stall_min_source", ""),
               "watcher: kit.json stall_min.default for other phases (25 min > 20 -> stall)")
            rc, j, _ = watch("in_progress", 25, rs_extra={"current_phase": "P2", "stall_min": 60})
            ok(rc == 1 and j.get("stall_min") == 60 and j.get("stall_min_source") == "run-state.json stall_min",
               "watcher: run-state.json stall_min overrides kit.json")
            sj = os.path.join(fake, ".claude", "run-state", "session.json")
            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            with open(sj, "w", encoding="utf-8") as f:
                json.dump({"session_id": "s1", "pid": dead.pid}, f)
            rc, j, _ = watch("in_progress", 2)
            ok(rc == 2 and j.get("reason") == "stall" and j.get("pid") == dead.pid and j.get("pid_alive") is False and
               "not running" in j.get("detail", ""), "watcher: dead claude pid in session.json -> stall at once, pid_alive false")
            with open(sj, "w", encoding="utf-8") as f:
                json.dump({"session_id": "s1", "pid": os.getpid()}, f)
            rc, j, _ = watch("in_progress", 2)
            ok(rc == 1 and j.get("pid_alive") is True, "watcher: live pid -> pid_alive true, still running")
            os.remove(sj)
            rc, j, _ = watch("done", 1, rs_extra={"phases": {"P1": {"status": "done_below_bar"}, "P2": {"status": "done"}}})
            ok(rc == 0 and j.get("below_bar") == ["P1"] and str(j.get("headline", "")).startswith("BELOW BAR"),
               "watcher JSON: below_bar and headline from run-state.json")
            with open(os.path.join(fake, "run-report.json"), "w", encoding="utf-8") as f:
                json.dump({"headline": "BELOW BAR: P1 (main 6/6): murky water", "below_bar": ["P1"], "run": "r1"}, f)
            rc, j, _ = watch("done", 1)
            ok(rc == 0 and j.get("headline") == "BELOW BAR: P1 (main 6/6): murky water" and j.get("below_bar") == ["P1"],
               "watcher JSON: the run report's headline is passed through")
            os.remove(os.path.join(fake, "run-report.json"))

            # --- session.py + resume.sh: never two live sessions ---
            def sess(*a: str) -> subprocess.CompletedProcess:
                return subprocess.run([sys.executable, os.path.join(root, "tools", "headless", "session.py")] + list(a),
                                      capture_output=True, text=True, cwd=root)
            sid = "11111111-2222-3333-4444-555555555555"
            ok(sess("set", "session_id=" + sid, "pid=%d" % dead.pid, "branch=r1-run").returncode == 0 and
               sess("get", "branch").stdout.strip() == "r1-run" and sess("alive").returncode == 1,
               "session.py: set/get; a dead pid is not alive")
            sess("set", "pid=%d" % os.getpid())
            ok(sess("alive").returncode == 2, "session.py: a live pid of another process (reused pid) is not this session")
            sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", sid])
            sess("set", "pid=%d" % sleeper.pid)
            ok(sess("alive").returncode == 0, "session.py: the live claude process of this session is alive")
            fakebin = os.path.join(tmp, "fakebin")
            os.makedirs(fakebin, exist_ok=True)
            args_out = os.path.join(tmp, "claude-args.txt")
            with open(os.path.join(fakebin, "claude"), "w", newline="\n") as f:
                f.write("#!/bin/sh\nprintf '%%s\\n' \"$@\" > '%s'\necho '{\"type\":\"result\",\"permission_denials\":"
                        "[{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"resume-denied-cmd\"}}]}'\n" % args_out)
            os.chmod(os.path.join(fakebin, "claude"), 0o755)
            r = subprocess.run([bash, os.path.join(root, "tools", "headless", "resume.sh"), "--grace", "3",
                                "--python", sys.executable, "--prompt", "stalled; continue"], capture_output=True, text=True,
                               cwd=root, env=dict(os.environ, PATH=fakebin + os.pathsep + os.environ.get("PATH", "")),
                               timeout=120)
            try:
                sleeper.wait(timeout=10)
            except subprocess.TimeoutExpired:
                sleeper.kill()
            cargs = open(args_out).read().split("\n") if os.path.exists(args_out) else []
            sj2 = json.load(open(os.path.join(root, ".claude", "run-state", "session.json"), encoding="utf-8"))
            rlog = open(os.path.join(root, ".claude", "run-state", "resume.log"), encoding="utf-8").read()
            ok(r.returncode == 0 and sleeper.returncode is not None and "killing" in rlog and "killing" in r.stderr and
               cargs[:3] == ["-p", "--resume", sid] and "stalled; continue" in cargs and "acceptEdits" in cargs and
               not any("bypass" in a or "dangerously" in a for a in cargs) and sj2.get("resumes") == 1 and
               sj2.get("pid") not in (None, sleeper.pid) and sj2.get("session_id") == sid,
               "resume.sh: kills the live session (logged), resumes with --resume <id> acceptEdits, records the new pid: "
               + r.stderr.strip()[-400:])
            denied_rows = open(os.path.join(root, ".claude", "run-state", "denied.jsonl"), encoding="utf-8").read()
            ok("resume-denied-cmd" in denied_rows,"resume.sh: the result's permission denials are logged to denied.jsonl")
            r = subprocess.run([bash, os.path.join(root, "tools", "headless", "resume.sh"), "--python", sys.executable,
                                "--dry-run"], capture_output=True, text=True, cwd=root, timeout=60)
            ok(r.returncode == 0 and "not running" in r.stderr and "killing" not in r.stderr and "--resume" in r.stdout,
               "resume.sh: a dead session is resumed without killing anything")
            rs_l = open(os.path.join(root, "tools", "headless", "launch.sh"), encoding="utf-8").read()
            ok("pid=$CPID" in rs_l and "resume.sh" in rs_l and "--permission-mode bypassPermissions" not in rs_l and
               "Start-Process" in open(os.path.join(root, "tools", "headless", "launch.ps1"), encoding="utf-8").read(),
               "launchers record the claude pid in session.json and point to resume.sh")

            # --- scripts/run-loop.sh: launch/resume/watch decision over the kit's own tools ---
            loop = os.path.join(root, "scripts", "run-loop.sh")
            r = subprocess.run([bash, "-n", loop], capture_output=True, text=True)
            ok(r.returncode == 0, "bash -n scripts/run-loop.sh (%s)" % r.stderr.strip())
            lsrc = open(loop, encoding="utf-8").read()
            ok(all(s in lsrc for s in ("tools/headless/launch.sh", "tools/headless/resume.sh", "tools/watch/run_watch.sh"))
               and "--permission-mode" not in lsrc and "claude -p" not in lsrc,
               "run-loop.sh drives launch/resume/watch and never calls claude itself (no bypass possible)")
            rloop = lambda *a: subprocess.run([bash, loop, "--repo", "o/fake", "--branch", "r1-run", "--python", sys.executable] + list(a),
                                              capture_output=True, text=True, cwd=root, timeout=60)
            r = rloop("--dry-run")
            ok(r.returncode == 0 and "start=resume" in r.stdout,
               "run-loop: a dead recorded session of an unfinished run is resumed, not relaunched: " + r.stdout + r.stderr)
            rsp = os.path.join(root, "run-state.json")
            rs_keep = open(rsp, encoding="utf-8").read()
            with open(rsp, "w", encoding="utf-8") as f:
                json.dump({"run": "r1", "status": "done"}, f)
            r = rloop()
            ok(r.returncode == 2 and "--new-run" in r.stderr,
               "run-loop: refuses to launch over a finished run-state.json without --new-run: " + r.stderr)
            with open(rsp, "w", encoding="utf-8") as f:
                f.write(rs_keep)
            os.remove(os.path.join(root, ".claude", "run-state", "session.json"))
            lr = os.path.join(tmp, "launch-repo")
            os.makedirs(os.path.join(lr, "tools", "headless"))
            os.makedirs(os.path.join(lr, ".claude"))
            shutil.copy(os.path.join(root, "tools", "headless", "launch.sh"), os.path.join(lr, "tools", "headless"))
            shutil.copy(os.path.join(root, ".claude", "settings.json"), os.path.join(lr, ".claude"))
            git(lr, "init", "-q", "-b", "r1-run")
            git(lr, "add", "-A")
            git(lr, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")

            def launch(*a: str) -> subprocess.CompletedProcess:
                return subprocess.run([bash, os.path.join(lr, "tools", "headless", "launch.sh"), "--python", sys.executable,
                                       "--skip-selftest", "--dry-run"] + list(a), capture_output=True, text=True, cwd=lr,
                                      env=dict(os.environ, HOME=home), timeout=60)
            pre = "0f1e2d3c-4b5a-4968-8776-655443322110"
            r = launch("--session-id", pre.upper())
            ok(r.returncode == 0 and "session %s on r1-run" % pre in r.stderr and "%s.jsonl" % pre in r.stderr and
               "build/headless/%s.stream.jsonl" % pre in r.stderr and "--session-id %s" % pre in r.stdout,
               "launch.sh --session-id: the pre-assigned id (normalised) names the session, log, stream and claude "
               "--session-id: " + r.stderr + r.stdout)
            r = launch("--session-id", "not-a-uuid")
            ok(r.returncode == 2 and "must be a UUID" in r.stderr and "would run" not in r.stdout,
               "launch.sh --session-id: an invalid id is refused before launch")
            r = launch()
            ok(r.returncode == 0 and pre not in r.stderr and
               len(r.stderr.split("session ", 1)[-1].split(" ", 1)[0]) == 36,
               "launch.sh without --session-id: a fresh uuid4")
            ok("-SessionId" in open(os.path.join(root, "tools", "headless", "launch.ps1"), encoding="utf-8").read(),
               "launch.ps1 takes -SessionId")
        else:
            ok(True, "watcher/launcher bash checks skipped (no bash on this OS)")

        # --- init: non-visual by default, visual with --visual or a visual addon ---
        def init(name: str, *args: str):
            d = copy_project(os.path.join(tmp, name), template_files=True)
            r = subprocess.run([sys.executable, os.path.join(d, "tools", "init_project.py"), "--name", "Demo"] + list(args),
                               capture_output=True, text=True, cwd=d,
                               env=dict(os.environ, KIT_INIT_NO_SELFTEST="1", CLAUDE_PROJECT_DIR=d))
            rd = lambda p: open(os.path.join(d, p), encoding="utf-8").read() if os.path.exists(os.path.join(d, p)) else ""  # noqa: E731
            return d, r, json.load(open(os.path.join(d, "kit.json"), encoding="utf-8")), rd
        d, r, k, rd = init("init-plain")
        ok(r.returncode == 0 and k["visual"]["required"] is False and not os.path.exists(os.path.join(d, "ART-BIBLE.md"))
           and not os.path.exists(os.path.join(d, "docs", "shots", "shots.json")), "init (no --visual): nothing visual copied, required false")
        ok("Style slice" not in rd("PLAN.md") and "kit:visual" not in rd("PLAN.md") + rd("CLAUDE.md") and
           "**P1: ...**" in rd("PLAN.md") and "Style lock" not in rd("CLAUDE.md") and "render of the shot set" not in rd("PLAN.md"),
           "init (no --visual): PLAN and CLAUDE.md have no visual phases or sections")
        r = tool(d, "art_gate.py")
        ok(r.returncode == 0 and "SKIPPED" in r.stdout, "init (no --visual): art gate SKIPPED")
        ok(tool(d, "review.py", "close", "P1").returncode == 0, "init (no --visual): phases close without visual checks")
        st_cmds = [h["command"] for e in json.load(open(os.path.join(d, ".claude", "settings.json"), encoding="utf-8"))["hooks"].values()
                   for x in e for h in x["hooks"]]
        kit_cmds = [h["command"] for e in json.load(open(os.path.join(KIT, ".claude", "settings.json"), encoding="utf-8"))["hooks"].values()
                    for x in e for h in x["hooks"]]
        ok(st_cmds == kit_cmds and all(c.startswith(("python \"", "python3 \"")) for c in st_cmds),
           "init (no --python): hook commands unchanged")
        d, r, k, rd = init("init-visual", "--visual", "--python", "python3")
        plan_v = rd("PLAN.md")
        ok(r.returncode == 0 and k["visual"]["required"] is True and os.path.exists(os.path.join(d, "ART-BIBLE.md")) and
           os.path.exists(os.path.join(d, "docs", "shots", "shots.json")), "init --visual: required true, bible and shot set copied")
        ok("render of the shot set" in plan_v and "**P1: Style slice** [visual]" in plan_v and "**P2: ...**" in plan_v and
           plan_v.index("**P1: Style slice**") < plan_v.index("**P2: ...**") and "kit:visual" not in plan_v and
           "Demo-" not in plan_v and "r1-lighting-lock" in plan_v and "\n10. Visual" in plan_v and
           "--known-issues" in plan_v and "side track" in plan_v,
           "init --visual: P0 shot line, P1 style slice (side track, below bar rule), later phases renumbered, run rule 10")
        ok("\n## Style lock\n" in rd("CLAUDE.md") and "kit:visual" not in rd("CLAUDE.md"), "init --visual: CLAUDE.md style lock")
        st_cmds = [h["command"] for e in json.load(open(os.path.join(d, ".claude", "settings.json"), encoding="utf-8"))["hooks"].values()
                   for x in e for h in x["hooks"]]
        ok(st_cmds and all(c.startswith("python3 \"") for c in st_cmds), "init --python python3: every hook command uses python3")
        if not NESTED:
            r = subprocess.run([sys.executable, os.path.join(d, "tests", "selftest.py")], capture_output=True, text=True,
                               cwd=d, env=dict(os.environ, KIT_SELFTEST_NESTED="1"), timeout=900)
            ok(r.returncode == 0 and "SELFTEST OK" in r.stdout,
               "selftest passes inside an init --visual project: " + (r.stdout + r.stderr).strip()[-800:])
        d, r, k, rd = init("init-godot", "--addon", "godot")
        ok(r.returncode == 0 and k["visual"]["required"] is True and "Style slice" in rd("PLAN.md") and
           os.path.exists(os.path.join(d, "tools", "render_shots.gd")), "init --addon godot: visual automatically")

        # --- schemas parse ---
        for s in os.listdir(os.path.join(root, "schemas")):
            json.load(open(os.path.join(root, "schemas", s), encoding="utf-8"))
        ok(True, "schemas are valid JSON")
        ok(vis_required in (True, False), "visual.required of the copied project restored for the checks above")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("SELFTEST OK (%d checks)" % checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
