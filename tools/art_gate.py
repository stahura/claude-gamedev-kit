"""Art bible gate: no build phase starts until this prints ART GATE OK.

  python tools/art_gate.py [--bible ART-BIBLE.md] [--shots [docs/shots/shots.json]] [--draft]

Content: the art bible (path from kit.json "visual.art_bible") has every required section filled (no empty section, no
`<placeholder>` outside comments), every docs/refs/ image it lists exists (at least one), and the last
`Approved: <name>, <YYYY-MM-DD>` line is filled in. With --shots, also the shot set: integer version, at least one
shot, each with a name and refs that exist.
Frozen (the run id is kit.json "run"; tags are made by the owner or at run start and never moved):
  - the git tag `<run>-start` exists, and ART-BIBLE.md at that tag already had the Approved line (only the owner
    writes it, between runs),
  - ART-BIBLE.md, the refs folder (visual.refs_dir) and the kit.json "visual" block are unchanged since `<run>-start`
    (working tree, untracked files included),
  - once the tag `<run>-lighting-lock` exists, the shot set is unchanged since it (P0 may still write it before).
--draft checks content only (the visual-direction session, before a run) and prints ART GATE DRAFT OK, never OK.
Exit 0 = OK (or SKIPPED when kit.json sets "visual.required": false and the visual block is unchanged since the start
tag), 1 = FAIL with reasons.
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = ["Reference images", "Style target", "Palette", "Lighting mood", "Material rules",
            "Budgets per asset class", "Scale conventions", "Do and don't", "Approval"]
APPROVED = re.compile(r"^Approved:\s*([^<>,\n]*\S)\s*,\s*(\d{4}-\d{2}-\d{2})\s*$", re.M)
PLACEHOLDER = re.compile(r"<[^<>\n]{1,80}>")
REF = re.compile(r"docs/refs/[^\s`|)\]]+\.(?:png|jpe?g|webp)", re.I)


def _cfg() -> dict:
    try:
        with open(os.path.join(ROOT, "kit.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except OSError as e:
        return 1, str(e)
    return r.returncode, r.stdout


def _sections(text: str) -> dict:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    parts = re.split(r"^## +(.+?)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def approved(text: str) -> bool:
    lines = [ln for ln in _sections(text).get("Approval", "").splitlines() if ln.strip().startswith("Approved:")]
    return bool(lines) and bool(APPROVED.match(lines[-1].strip()))


def check_bible(path: str) -> list:
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return ["missing art bible: %s (copy templates/ART-BIBLE.md)" % path]
    errs = []
    body = _sections(text)
    for s in SECTIONS:
        if s not in body:
            errs.append("section missing: ## " + s)
        elif not body[s].strip():
            errs.append("section empty: ## " + s)
        elif s != "Approval" and PLACEHOLDER.search(body[s]):
            errs.append("unfilled placeholder in ## %s: %s" % (s, PLACEHOLDER.search(body[s]).group(0)))
    refs = sorted(set(REF.findall(body.get("Reference images", ""))))
    if not refs:
        errs.append("no reference images (docs/refs/...) listed under ## Reference images")
    errs += ["reference image not found: " + r for r in refs if not os.path.isfile(os.path.join(ROOT, r))]
    if not approved(text):
        errs.append("not approved: the owner must add 'Approved: <name>, <YYYY-MM-DD>' under ## Approval")
    return errs


def check_shots(path: str) -> list:
    try:
        with open(path, encoding="utf-8-sig") as f:
            s = json.load(f)
    except (OSError, ValueError) as e:
        return ["shot set unreadable: %s (%s)" % (path, e)]
    errs = []
    if not isinstance(s.get("version"), int):
        errs.append("shot set needs an integer 'version'")
    shots = s.get("shots") or []
    if not shots:
        errs.append("shot set has no shots")
    for i, sh in enumerate(shots):
        name = sh.get("name") or "#%d" % i
        if not sh.get("name"):
            errs.append("shot %s has no name" % name)
        if not sh.get("refs"):
            errs.append("shot %s lists no refs" % name)
        errs += ["shot %s: ref not found: %s" % (name, r) for r in sh.get("refs", [])
                 if not os.path.isfile(os.path.join(ROOT, r))]
    return errs


def _tag(name: str) -> bool:
    return _git("rev-parse", "-q", "--verify", "refs/tags/" + name)[0] == 0


def changed_since(tag: str, paths: list) -> list:
    """Paths (tracked or untracked) that differ between the tag and the working tree."""
    out = set(_git("diff", "--name-only", tag, "--", *paths)[1].split("\n"))
    out |= set(_git("ls-files", "--others", "--", *paths)[1].split("\n"))
    return sorted(p for p in out if p.strip())


def check_frozen(cfg: dict, required: bool) -> list:
    vis = cfg.get("visual") or {}
    run = cfg.get("run", "")
    if _git("rev-parse", "--git-dir")[0] != 0:
        return ["not a git repository: the gate compares against the %s-start tag" % run]
    start = run + "-start"
    if not _tag(start):
        return ["tag %s missing: tag the run start (from the owner's brief commit) before the gate" % start]
    errs = []
    rc, old = _git("show", "%s:kit.json" % start)
    try:
        old_vis = json.loads(old).get("visual") or {} if rc == 0 else None
    except ValueError:
        old_vis = None
    if old_vis != vis:
        errs.append("kit.json \"visual\" block changed since %s (only the owner changes it, between runs)" % start)
    if not required:
        return errs
    bible = vis.get("art_bible", "ART-BIBLE.md")
    rc, text = _git("show", "%s:%s" % (start, bible))
    if rc != 0 or not approved(text):
        errs.append("the Approved line was not present in %s at %s: only the owner approves, before the run" % (bible, start))
    errs += ["changed since %s: %s (needs an owner commit between runs)" % (start, p)
             for p in changed_since(start, [bible, vis.get("refs_dir", "docs/refs")])]
    lock = run + "-lighting-lock"
    if _tag(lock):
        errs += ["shot set changed since %s: %s (frozen after the lighting lock)" % (lock, p)
                 for p in changed_since(lock, [vis.get("shot_set", "docs/shots/shots.json")])]
    return errs


def main() -> int:
    cfg = _cfg()
    vis = cfg.get("visual") or {}
    ap = argparse.ArgumentParser()
    ap.add_argument("--bible", default=vis.get("art_bible", "ART-BIBLE.md"))
    ap.add_argument("--shots", nargs="?", const=vis.get("shot_set", "docs/shots/shots.json"))
    ap.add_argument("--draft", action="store_true")
    a = ap.parse_args()
    required = vis.get("required", False) is True
    errs = []
    if required:
        errs += check_bible(os.path.join(ROOT, a.bible))
        if a.shots:
            errs += check_shots(os.path.join(ROOT, a.shots))
    if not a.draft and (required or _git("rev-parse", "-q", "--verify", "refs/tags/%s-start" % cfg.get("run", ""))[0] == 0):
        errs += check_frozen(cfg, required)
    for e in errs:
        print("ART GATE FAIL: " + e)
    if errs:
        return 1
    if not required:
        print("ART GATE SKIPPED (kit.json visual.required is false)")
    else:
        print("ART GATE DRAFT OK (content only; not valid for a run)" if a.draft else "ART GATE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
