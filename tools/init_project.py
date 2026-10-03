"""Turn a fresh copy of the kit into a project.

  python tools/init_project.py --name "My Project" [--run r1] [--visual] [--addon godot] [--meshy-cap 250]
                                [--python python3]

Fills PROJECT_NAME / RUN_ID placeholders, copies templates/ (PLAN, PROGRESS, CLAUDE.md) to the root (ASSET-SPEC.md
stays a template, copied per asset), installs addons (skills into .claude/skills, tools into tools/, docs into
docs/<addon>/, gotchas appended to CLAUDE.md), sets kit.json, runs the self-test.
Visual is opt-in: --visual (automatic with an addon whose kit.addon.json has "visual": true, e.g. godot) sets
kit.json visual.required true, copies ART-BIBLE.md and templates/shots.json to docs/shots/, and fills the
`<!-- kit:visual-* -->` markers in PLAN.md and CLAUDE.md from templates/visual/snippets.md (P0 shot line, P1 style
slice, later phases renumbered). Without it nothing visual is copied, the markers are removed and visual.required is
false: a non-visual project works out of the box (art gate SKIPPED, no visual phases).
--python NAME rewrites the interpreter of every hook command in .claude/settings.json (the template uses `python`,
which Windows has; Linux images with only `python3` use --python python3). Without it the commands are unchanged.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = re.compile(r"^<!-- kit:(visual-[\w-]+) -->\n", re.M)


def fill(path: str, name: str, run: str) -> None:
    with open(path, encoding="utf-8") as f:
        s = f.read()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(s.replace("PROJECT_NAME", name).replace("RUN_ID", run))


def set_python(name: str) -> int:
    """Point every hook command in .claude/settings.json at interpreter `name`; returns how many were changed."""
    path = os.path.join(ROOT, ".claude", "settings.json")
    with open(path, encoding="utf-8") as f:
        s = f.read()
    new, n = re.subn(r'("command":\s*")python3?(\s)', lambda m: m.group(1) + name + m.group(2), s)
    if n:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
    return n


def snippets() -> dict:
    with open(os.path.join(ROOT, "templates", "visual", "snippets.md"), encoding="utf-8") as f:
        parts = re.split(r"^<!-- snippet:([\w-]+) -->\n", f.read(), flags=re.M)
    return {parts[i]: parts[i + 1].rstrip("\n") + "\n" for i in range(1, len(parts) - 1, 2)}


def apply_markers(text: str, visual: bool) -> str:
    """Replace (visual) or drop each marker line; after an inserted P1, renumber the later phases."""
    snip = snippets() if visual else {}
    out, pos, shift_from = [], 0, None
    for m in MARKER.finditer(text):
        out.append(text[pos:m.start()])
        if visual:
            out.append(snip.get(m.group(1), ""))
            if m.group(1) == "visual-p1":
                shift_from = sum(len(x) for x in out)
        pos = m.end()
    out.append(text[pos:])
    s = "".join(out)
    if shift_from is not None:
        s = s[:shift_from] + re.sub(r"\*\*P(\d+)", lambda n: "**P%d" % (int(n.group(1)) + 1), s[shift_from:])
    return re.sub(r"\n{3,}", "\n\n", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--run", default="r1")
    ap.add_argument("--visual", action="store_true", help="visual project: art bible, shot set, style slice (P1)")
    ap.add_argument("--addon", action="append", default=[])
    ap.add_argument("--meshy-cap", type=float)
    ap.add_argument("--python", help="interpreter for the hook commands in .claude/settings.json (e.g. python3)")
    a = ap.parse_args()
    visual = a.visual
    for addon in a.addon:
        if not os.path.isdir(os.path.join(ROOT, "addons", addon)):
            print("unknown addon", addon)
            return 2
        extra = os.path.join(ROOT, "addons", addon, "kit.addon.json")
        if os.path.exists(extra):
            with open(extra, encoding="utf-8") as f:
                visual = visual or json.load(f).get("visual") is True
    copies = [("PLAN.md", "PLAN.md"), ("PROGRESS.md", "PROGRESS.md"), ("CLAUDE.md", "CLAUDE.md")]
    if visual:
        copies += [("ART-BIBLE.md", "ART-BIBLE.md"), ("shots.json", os.path.join("docs", "shots", "shots.json"))]
    fresh = set()
    for f, dst in copies:
        src = os.path.join(ROOT, "templates", f)
        dst = os.path.join(ROOT, dst)
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(src, dst)
            fresh.add(f)
    for f in ("PLAN.md", "CLAUDE.md"):
        if f in fresh:
            path = os.path.join(ROOT, f)
            with open(path, encoding="utf-8") as fh:
                s = apply_markers(fh.read(), visual)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(s)
    for f in ("PLAN.md", "PROGRESS.md", "CLAUDE.md", "BRIEF.md", "ART-BIBLE.md"):
        if os.path.exists(os.path.join(ROOT, f)):
            fill(os.path.join(ROOT, f), a.name, a.run)
    for addon in a.addon:
        base = os.path.join(ROOT, "addons", addon)
        for sub, dest in (("skills", os.path.join(".claude", "skills")), ("tools", "tools"),
                          ("docs", os.path.join("docs", addon))):
            src = os.path.join(base, sub)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(ROOT, dest), dirs_exist_ok=True)
        extra = os.path.join(base, "CLAUDE-gotchas.md")
        if os.path.exists(extra):
            with open(extra, encoding="utf-8") as f, open(os.path.join(ROOT, "CLAUDE.md"), "a", encoding="utf-8", newline="\n") as out:
                out.write("\n" + f.read())
        cfg_extra = os.path.join(base, "kit.addon.json")
        if os.path.exists(cfg_extra):
            with open(cfg_extra, encoding="utf-8") as f:
                add = json.load(f)
            with open(os.path.join(ROOT, "kit.json"), encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("allowed_delete_roots", [])
            for r in add.get("allowed_delete_roots", []):
                if r not in cfg["allowed_delete_roots"]:
                    cfg["allowed_delete_roots"].append(r)
            with open(os.path.join(ROOT, "kit.json"), "w", encoding="utf-8", newline="\n") as f:
                json.dump(cfg, f, indent="\t")
    with open(os.path.join(ROOT, "kit.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["project"] = a.name
    cfg["run"] = a.run
    cfg.setdefault("visual", {})["required"] = visual
    if a.meshy_cap is not None:
        cfg["paid_services"]["meshy"]["cap"] = a.meshy_cap
    with open(os.path.join(ROOT, "kit.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, indent="\t")
    if a.python:
        set_python(a.python)
    with open(os.path.join(ROOT, "run-state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"run": a.run, "status": "planning", "phases": {}, "spend": {}, "updated": ""}, f, indent=2)
    if os.environ.get("KIT_INIT_NO_SELFTEST"):
        rc = 0
    else:
        rc = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "selftest.py")]).returncode
    print("initialised %s (%s), visual: %s, addons: %s; self-test %s" % (
        a.name, a.run, "yes" if visual else "no", ", ".join(a.addon) or "none", "OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
