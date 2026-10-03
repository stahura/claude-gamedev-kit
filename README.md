# claude-gamedev-kit

A template repository for unattended Claude Code game and asset builds in Godot. You write a brief; Claude Code
plans the work in phases and builds, tests, reviews, merges and releases each one on its own. Visual work is held
to a standard: an art bible gate (no build starts until the art bible is approved), a style slice that locks the
look on a small scene first, a reviewer subagent that sees only screenshots and scores them, and an automated
performance gate. A run protocol keeps long runs on track, and a watcher tells you when a run has finished or
stalled.

## Quick start
```bash
gh repo create <owner>/<new-project> --private --template <owner>/claude-gamedev-kit --clone
cd <new-project>
python3 tools/init_project.py --name "My Project" --addon godot --python python3   # Windows: python, no --python
git add -A && git commit -m "init from claude-gamedev-kit" && git push -u origin main
```
1. Fill in `BRIEF.md` (goal, definition of done, quality bar, budgets) and put reference images in `docs/refs/`.
   Commit, then create and push a run branch (for example `git checkout -b r1-run && git push -u origin r1-run`).
2. Run it. Interactively: open Claude Code in the repo and say "Read BRIEF.md; run it unattended per the
   run-protocol skill; report via run-report.json." Unattended: `tools/headless/launch.sh --branch r1-run`
   (`tools/headless/launch.ps1 -Branch r1-run` on Windows).
3. Watch it: `tools/watch/run_watch.sh --repo <owner>/<new-project> --branch r1-run --project-dir .` on the same
   machine, or add `--mode pc` (instead of `--project-dir`) from another machine. It prints one JSON line when the
   run ends or stalls.

## Requirements
- Claude Code CLI (`claude`), logged in or with `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` set
- Python 3.8 or newer (standard library only)
- git, and the GitHub CLI (`gh`) for creating the repo and for the watcher (or `curl` with `GH_TOKEN`)
- bash for the headless launcher and the watcher (on Windows: `launch.ps1`, or Git Bash)
- Godot 4 for the Godot addon (tested on 4.7.2)
- Optional: Blender for asset cleanup (`tools/blender/cleanup_asset.py`, tested on 5.2)

New to this? Read [How it works, for beginners](docs/HOW-IT-WORKS.md). License: [MIT](LICENSE).

The rest of this file is the detailed reference.

## Overview
A template for **unattended, multi-hour Claude Code runs** driven by orchestrating bots. The bots write a brief and
read results from GitHub; Claude Code plans, builds, tests, gets adversarially reviewed, merges, tags and releases
phase by phase, and ends with a machine-readable run report. Built from the lessons of a real overnight run
(9 phases, 10 reviews, 2 h 40 min; see "Why it looks like this") and a later pilot run (r1 lessons).

**Latest: r1 lessons (first pilot run)**, see [CHANGELOG.md](CHANGELOG.md): verdicts from background reviewers'
`SubagentHandback` are captured, every hook call is logged, per-stage review caps where below bar never halts the
run, the reviewer sees the previous round, the guard only denies real writes, headless launch + heartbeat + watcher.

## Start a new project (3 commands)
```bash
gh repo create <owner>/<new-project> --private --template <owner>/claude-gamedev-kit --clone
cd <new-project> && python tools/init_project.py --name "My Project" --addon godot --meshy-cap 250
git add -A && git commit -m "init from claude-gamedev-kit" && git push -u origin main
```
`init_project.py` fills the placeholders, moves `templates/` (PLAN, PROGRESS, CLAUDE.md) to the root, installs
addons and runs the self-test (`python tests/selftest.py` -> `SELFTEST OK (n checks)`). Omit `--addon` for a
non-Godot project. **Visual is opt-in:** `--visual` (automatic with `--addon godot`) turns on the visual pipeline
(art bible, shot set, P1 style slice); without it the project is non-visual (`visual.required` false, art gate
SKIPPED, no visual phases).

Then the bot fills in `BRIEF.md` (plus reference images in `docs/refs/`), commits it, and hands off with one line:

> Read BRIEF.md in `<owner>/<repo>` on branch `<run-branch>`; run it unattended per the run-protocol skill; report via run-report.json.

Run Claude Code in the repo (desktop app or `claude` CLI). Unattended on a box or PC: `tools/headless/launch.sh`
(or `launch.ps1`) runs `claude -p "<handoff line>" --permission-mode acceptEdits --session-id <id> --output-format
stream-json --verbose` with the committed allow list; never `bypassPermissions`. See "Headless runs" below.

## What is in it
| Path | What |
|---|---|
| `BRIEF.md` | Brief template the bots fill in (goal, non-negotiables, testable definition of done, quality bar + refs, scope, budgets, licenses, pre-answered questions, deliverables). |
| `templates/PLAN.md`, `PROGRESS.md`, `CLAUDE.md` | Plan with run rules and phase legend; append-only progress log format; project memory with gotchas carried between runs. |
| `kit.json` | Run config: run id, max Stop-hook continues, review timeout, allowed delete roots, heartbeat (`heartbeat`, `heartbeat_min`, `heartbeat_branch`), **paid services and caps**, `visual` (required, paths, lock phase, `review_caps` + `on_cap`, rubric items and stage-A subset, pass scores incl. `stage_a_min_score`, perf thresholds). |
| `run-state.json` | Live state for the bots (phases, reviews, spend, tests, release). Schema in `schemas/`. |
| `schemas/` | `run-state`, `run-report` (end of run; feeds the next brief) and `review-verdict` JSON schemas. |
| `.claude/settings.json` | Allow/deny lists (godot, godot_console, blender, ffmpeg allowed directly; Edit to `.claude/run-state/` denied, which covers every file-edit tool) and the six hooks; `autoContinueAtUsageLimit`. Commit it before a headless launch. |
| `.claude/hooks/stop_guard.py` | Keeps the run going while PLAN.md has `- [ ] **P` phases. Exits: `.claude/HALT`, no open phase, continue budget, **review hold** (a pending review younger than `review_timeout_min`); a stale review returns relaunch-once-then-unreviewed instructions. Visual projects: an `[x]` phase failing the close check blocks the stop; a stage at its review cap gets "close below bar and continue", never an end of run. Every decision is logged. |
| `.claude/hooks/pre_tool_guard.py` | PreToolUse for Bash, PowerShell and the file tools: paid-API binaries only via `tools/paid.py`; no deletes outside the project or on maybe-empty variable paths; no force push, remote deletes, repo/release deletes, tag moves/deletes; no writes to `.claude/run-state/`: only real write targets count (redirects, tee, cp/mv, rm, touch, sed -i, dd of=, PowerShell Set-Content/Out-File/Copy-Item..., also after `cd`), never text that merely mentions the path (heredoc bodies, commit messages, echo). Denies are logged. |
| `.claude/hooks/subagent_stop.py` | SubagentStop for the visual-reviewer: finds its JSON verdict (last message, `SubagentHandback` input, other tool input, last text), validates it (every shot x every rubric item, current shot-set version, every shot PNG of this round opened) and stores it; the builder never supplies visual verdicts. After a handback an unstorable verdict is recorded `invalid` at once (a block could not be acted on). Every call is logged to `.claude/run-state/hooks.log.jsonl`. |
| `.claude/hooks/session_start.py` | On compaction (and start/resume): re-injects the session id, run rules, open phases, pending reviews, below-bar phases, spend and the PROGRESS tail. |
| `.claude/hooks/permission_log.py` | PermissionRequest: in headless runs (`KIT_HEADLESS=1`) every permission request is denied with "skipped and logged, do not retry" and appended to `.claude/run-state/denied.jsonl`; interactive sessions are untouched. |
| `.claude/hooks/heartbeat.py` | PostToolUse: at most every `heartbeat_min` (10) minutes writes `heartbeat.json` and pushes it as a one-file commit to `<run branch>-heartbeat` from a detached process (git plumbing; never the run branch, never forced). `"heartbeat": false` disables it. |
| `.claude/agents/` | `plan-critic`, `adversarial-reviewer`, `visual-reviewer` (independent art director: sees only shots, bible, refs and the rubric; scores 1-5 per shot; writes no code): 15-minute limit, never delete outside their scratchpad, end with the JSON verdict. |
| `.claude/skills/run-protocol/` | The run protocol: phase loop, close-before-next, reviews and timeouts, logging, release, spend, when stuck, run report. |
| `tools/paid.py` | The only way to call a paid API: estimate -> refuse over cap -> balance before/after -> ledger (`.claude/run-state/spend.json`) -> run-state. |
| `tools/review.py` | `start / done / relaunch / unreviewed / close [--known-issues] / headline / list` for reviews; validates verdicts; drives the review hold. Visual `start` accepts only the next round, enforces `visual.review_caps` on reviewed rounds (a captured verdict) only, blocks the run after 2 rounds in a row without a captured verdict, snapshots the shots into `rounds/<id>/` and prints the reviewer brief (the previous round's top problems, never its scores, go in `previous-round.md`, read after scoring); `close` marks a phase `[x]` only if it passes the close check (stored visual pass whose hash matches the hook log, perf record, style slice closed), or `[x] (below bar)` with `--known-issues` once its stages are at their caps with at least one real verdict; `headline` puts the below-bar headline first in run-report.json. |
| `tools/headless/launch.sh`, `launch.ps1`, `resume.sh`, `session.py` | Headless launcher: pre-launch checks, session id, claude pid in `.claude/run-state/session.json`, `claude -p ... --permission-mode acceptEdits`, permission denials into `denied.jsonl`; `resume.sh` kills a still-live session before `claude -p --resume` (docs/headless.md). |
| `tools/watch/run_watch.sh` | Watcher for the orchestrating bot: blocks until the run ends (run-state status, run report, HALT) or stalls (no session-log or heartbeat write for the phase's `stall_min`, or a dead claude pid), prints one JSON line with the stall limit, `pid_alive` and the below-bar `headline`, optional wake POST (tools/watch/README.md). |
| `tools/perf_gate.py` | Automated performance gate: the benchmark's `BENCH avg_fps= low1_fps=` line against `kit.json` `visual.perf`. |
| `tools/init_project.py` | Project setup (above); `--python python3` for Linux boxes without `python`. |
| `tests/selftest.py` | Exercises every hook, `paid.py` (fake service), `review.py` (caps, below bar, previous round), the guard's write-target parsing, the heartbeat (throwaway git remote), the watcher (`--once`) and init in throwaway copies; also runs itself inside an `init --visual` project. |
| `docs/headless.md` | Headless unattended runs: pre-launch checklist, launch and resume, denied commands, heartbeat, watcher. |
| `addons/godot/` | `godot-headless` skill (commands, smoke-runner contract, traps), `godot-lighting-post` skill (Environment/CameraAttributes for the style slice's lighting, tested shot-render command), shot-set renderer, contact sheet, GLB bake, clip-import mesh stripper, four-view model render, log reader; optional `docs/stylized-techniques.md` (reference, not rules). |
| `docs/visual-pipeline.md` | Engine-agnostic visual pipeline: visual-direction session, art bible gate, look-and-fix loop with before/after and revert, art-director rubric, asset routes, style slice (lighting on placeholders, slice assets, style lock; Godot, Unity, Unreal), parallelism rule. |
| `templates/ART-BIBLE.md` | Art bible (refs, style target, palette, lighting, materials, budgets per asset class, scale, do/don't, owner approval line); copied to the root. |
| `templates/shots.json`, `ASSET-SPEC.md` | Fixed, versioned, seeded shot set (copied to `docs/shots/`); per-asset spec for per-asset agents. |
| `templates/visual/snippets.md` | The visual PLAN/CLAUDE.md parts `init_project.py --visual` inserts (P0 shot line, P1 style slice, run rule, style lock). |
| `tools/art_gate.py` | Pre-build gate: bible filled, refs exist, approved before the `<run>-start` tag; bible, refs and the kit.json `visual` block unchanged since that tag, shot set unchanged since `<run>-lighting-lock` (`--shots` checks the shot set, `--draft` content only). |
| `tools/blender/cleanup_asset.py` | Headless Blender cleanup: scale/pivot, decimate to budget, UVs, rebake, grade (strip baked lighting, push toward the bible palette and value range), LODs, GLB. Tested on Blender 5.2 (static GLB). |

## Visual pipeline
For any game, 3D or asset project (`docs/visual-pipeline.md`). Each step gates the next:
1. Visual-direction session (~1 h, owner + agent): concept images into `docs/refs/`, `ART-BIBLE.md` filled.
2. Owner approves the bible; `python tools/art_gate.py` prints `ART GATE OK` before any build phase.
3. Fixed shot set + look-and-fix: render, compare to refs, fix one change at a time (before/after kept, unclear
   changes reverted); iterations stay in the git-ignored `docs/shots/_work/`, only the final set, before/after pairs
   and the review snapshots are committed. Each round ends with a review; rounds per stage are capped by
   `visual.review_caps` (stage A 3, main stage 6, per-phase overrides). The builder never passes its own work: the
   visual-reviewer scores every shot 1-5 on every `visual.rubric` item (default silhouette, depth, light, palette,
   cohesion, secondary detail, ground, life), compares each shot with its previous round, and passes it at 4+ on every
   item; a hook stores its verdict and `review.py close` refuses a visual phase without it. Performance is the
   automated `perf_gate.py` check. **Below bar never halts the run:** a stage at its cap closes with
   `review.py close P<N> --known-issues` (honest scores and known issues in run-state.json and the run report).
4. Style slice (P1), a ~60 x 60 m diorama or equivalent: lighting and post first, on a small dressed patch (one real
   rock, a few grass cards), locked; the core asset is prototyped on a side track meanwhile and has its own review
   budget.
5. Then the slice assets, one per route (AI generator only for characters, creatures and organic hero props via
   `paid.py`; every generated asset through Blender cleanup with the bible grade; environments from modular kits).
   When it passes, the look is locked: `docs/style_reference/` + the "Style lock" section of CLAUDE.md.
6. Only then content, and per-asset agents, each with an `ASSET-SPEC.md`, the bible and the style lock.
Non-visual projects: initialise without `--visual` (the default).

## Headless runs
`docs/headless.md` has the details. In short:
1. Before launch: allow list committed in `.claude/settings.json` (the run cannot change it), folder trust accepted,
   run branch fetched and checked out, `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) set, selftest OK.
2. `tools/headless/launch.sh --branch <run-branch>` (`launch.ps1 -Branch` on Windows) generates the session id,
   runs `claude -p` with `--permission-mode acceptEdits --session-id <id> --output-format stream-json --verbose` and
   records the claude pid, session id, start time and branch in `.claude/run-state/session.json`.
   `tools/headless/resume.sh` resumes it (`claude -p --resume <id> ... --permission-mode acceptEdits`) after killing the
   old process if it is still alive, so a stall pickup never runs two sessions. Never `bypassPermissions` /
   `--dangerously-skip-permissions`.
3. Off-allowlist commands are denied and logged by the PermissionRequest hook (`.claude/run-state/denied.jsonl`),
   never left waiting on a prompt; the run logs them and moves on.
4. The PostToolUse heartbeat pushes `heartbeat.json` to `<run branch>-heartbeat` at most every 10 minutes, so a
   watcher on another machine can see the run is alive without touching the run branch.
5. `tools/watch/run_watch.sh --repo <owner>/<repo> --branch <run-branch> [--mode pc]` blocks until done (0), stall
   (2: no session-log or heartbeat write for the phase's stall limit, kit.json `stall_min` default 30 with per-phase
   overrides for render/bake phases, or the recorded claude pid is dead; a single longer tool call looks like a stall
   unless it runs `heartbeat.py --beat`), blocked/halted (3), watcher error (4) or the 6 h cap (5), and prints one
   JSON line (with the stall limit used, `pid_alive`, and the below-bar `headline`).

## What the guard is (and is not)
The hooks, deny rules and gates **prevent accidents and shortcuts, not malice.** `python`, `blender -P <script>`,
`godot -s <script>` and any other interpreter the allow list permits run arbitrary code: they can call a paid API
with a key from the environment, delete files, force-push through a subprocess, or write `.claude/run-state/`
directly. The builder also writes the reviewer's prompt. Treat the guard as seatbelts; real containment is the
section below (separate account, repo-scoped token, the paid key only inside `paid.py`'s user). When a command is
blocked, the run rule is to stop and report it, never to wrap or re-route it.

**Stored verdicts are accident-proof, not forge-proof.** The guard stops an accidental write to
`.claude/run-state/reviews/*.json`; it does **not** stop a deliberate forge (a python one-liner can write a verdict
file, and the hook log next to it). As a tamper check the SubagentStop hook logs the sha256 of every verdict file it
stores to `.claude/run-state/hooks.log.jsonl`, and `review.py close` refuses a phase whose stored visual verdicts do
not match the logged hashes (edited after storing, or never stored by the hook). That catches a hand edit or a copied
verdict; a builder that forges both the file and the log line is out of scope. Trust comes from the separate
account and the reviewer's own transcript, not from these files.

## Making the spend cap real
`paid.py` + the guard stop accidents, not intent (above). For a hard cap: (1) give each run its **own API key/account holding
only the run budget** (the only cap the provider enforces); (2) on a Linux VM, keep the key in a file owned by another
user and allow it only through `sudo -u paybot python tools/paid.py ...` (sudoers rule for that one command), so a
session cannot call the API around the wrapper; (3) run unattended sessions under a separate OS account with a
repo-scoped GitHub token, so a mistake cannot reach other repos or files. Add services in `kit.json` (`cap`, `binaries`, `balance_cmd`,
`balance_regex`, `estimate_regex`).

## Why it looks like this (run-2 lessons)
- A background reviewer hung all night on one permission prompt (`rm -f "$S"/*.png`): reviewer timeouts, the review
  ledger, the delete guard and the reviewers' no-delete rule.
- The Stop hook pushed the session past a running review: the review hold.
- Phases overlapped, so tags and zips mixed phases: close (merge, tag, release) before starting the next.
- Estimated timestamps crept into the log: timestamps only from `date`/git.
- A cosmetic system consumed gameplay randomness and the long test flipped between win and loss: seeded gameplay RNG,
  long test run twice.
- Reviews caught the bugs self-tests missed (soft-locks, input routing, vacuous tests) and judged visuals harsher than
  the author: keep them, give them a schema, cap them at two rounds.
- The 18-hour plan took 2 h 40 min: bots set scope and the bar, Claude sizes phases.
- Windows shell friction (UTF-16 logs, BOMs, `/tmp`, heredocs): see `templates/CLAUDE.md` gotchas.

## Why it looks like this (r1 lessons, first pilot run)
- 6 of 8 visual verdicts were lost: background reviewers end with `SubagentHandback` and put the verdict only there;
  the hook read only plain text and its block came after the subagent had ended. Now the hook reads the handback,
  records `invalid` at once when nothing storable arrived, and logs every call.
- All 8 rounds went to lighting on placeholders and the water shader never started: per-stage caps (stage A 3), a
  dressed patch for stage A, the core asset on a side track, and below bar closes the stage instead of ending the run.
- The reviewer's requests oscillated: it now gets the previous round's shots and verdict and must not reverse itself
  without saying why.
- The guard denied three harmless commands that only mentioned `.claude/run-state` in text: it now parses real write
  targets.

## Platforms
Hook stdin is decoded with BOM handling (UTF-8/UTF-16, as some Windows agent hosts send), and the PreToolUse guard
fails closed: unreadable input is denied, never treated as empty.
Hooks and tools are Python 3.8+ stdlib only and run on Windows and Linux. Hook commands use
`python "$CLAUDE_PROJECT_DIR/..."` (Windows has `python`); on Linux images with only `python3`, initialise with
`python3 tools/init_project.py ... --python python3`, which rewrites every hook command (or symlink `python`).
Hook calls are logged to `.claude/run-state/hooks.log.jsonl` (SubagentStop: every call with its outcome
stored/blocked/invalid/ignored/error and the verdict source; Stop decisions; guard denies; hook exceptions). Software
rendering (lavapipe under `xvfb-run`) gives the same image as a GPU, only slower, so visual review can run on a Linux
machine without a GPU; the performance gate and real-time play-testing need a GPU.
