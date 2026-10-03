"""PostToolUse hook (matcher *): a cheap heartbeat a watcher can read from GitHub without touching the run branch.

At most every kit.json heartbeat_min minutes (default 10; "heartbeat": false disables it) it writes
.claude/run-state/heartbeat.json {ts_utc, session_id, branch, head_sha, last_tool, run_status} and starts a detached
background process (`heartbeat.py --push`) that commits that one file to the heartbeat branch (kit.json
heartbeat_branch, default <run branch>-heartbeat) with git plumbing: hash-object, mktree, commit-tree (parent: the
previous heartbeat commit when fetchable), `git push origin <sha>:refs/heads/<branch>`. It never touches the working
tree, the index or the run branch, never forces, gives up after ~20 s; failures are only logged (hooks.log.jsonl).
The hook itself returns at once and never fails the tool call.

  python .claude/hooks/heartbeat.py --beat   # from a long render loop: beat now (at most once a minute)
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib as K  # noqa: E402

HOOK = "heartbeat"
BEAT = os.path.join(K.STATE, "heartbeat.json")
LOCK = os.path.join(K.STATE, "heartbeat.lock")
PARENT_REF = "refs/kit/heartbeat"
DEADLINE_S = 20


def settings(cfg: dict):
    """(enabled, interval minutes, heartbeat branch or "" for <run branch>-heartbeat)."""
    hb = cfg.get("heartbeat", True)
    return hb is not False, float(cfg.get("heartbeat_min", 10)), str(cfg.get("heartbeat_branch") or "")


def due(minutes: float) -> bool:
    try:
        return time.time() - os.path.getmtime(BEAT) >= minutes * 60
    except OSError:
        return True


def write_beat(rec: dict) -> None:
    os.makedirs(K.STATE, exist_ok=True)
    tmp = BEAT + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, BEAT)


def spawn_push() -> None:
    args = [sys.executable, os.path.abspath(__file__), "--push"]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
          "cwd": K.ROOT, "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED, NEW_PROCESS_GROUP, NO_WINDOW
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)


def beat(data: dict, minutes: float) -> int:
    cfg = K.config()
    enabled, interval, _ = settings(cfg)
    if not enabled or not due(min(interval, minutes)):
        return 0
    try:
        with open(BEAT, encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        prev = {}
    sid = data.get("session_id") or prev.get("session_id") or ""
    if not sid:
        try:
            with open(os.path.join(K.STATE, "session.json"), encoding="utf-8") as f:
                sid = json.load(f).get("session_id", "")
        except (OSError, ValueError):
            pass
    write_beat({"ts_utc": K.utc_now(), "session_id": sid, "branch": prev.get("branch", ""),
                "head_sha": prev.get("head_sha", ""), "last_tool": data.get("tool_name", prev.get("last_tool", "")),
                "run_status": K.load_rs().get("status", "")})
    spawn_push()
    return 0


def git(args: list, deadline: float, inp: str = None) -> str:
    left = deadline - time.time()
    if left <= 0:
        raise RuntimeError("deadline")
    r = subprocess.run(["git"] + args, cwd=K.ROOT, input=inp, capture_output=True, text=True, timeout=left,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (args[0], (r.stderr or r.stdout).strip()[:300]))
    return r.stdout.strip()


def push() -> int:
    """Background: fill branch/head into heartbeat.json and push it as a one-file commit to the heartbeat branch."""
    deadline = time.time() + DEADLINE_S
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except OSError:
        try:
            if time.time() - os.path.getmtime(LOCK) < 120:
                return 0   # another push is running
            os.remove(LOCK)
        except OSError:
            return 0
        return push()
    hb_branch = ""
    try:
        _, _, hb_branch = settings(K.config())
        branch = git(["rev-parse", "--abbrev-ref", "HEAD"], deadline)
        head = git(["rev-parse", "HEAD"], deadline)
        with open(BEAT, encoding="utf-8") as f:
            rec = json.load(f)
        rec.update(branch=branch, head_sha=head)
        write_beat(rec)
        if branch == "HEAD":
            raise RuntimeError("detached HEAD: no run branch to name the heartbeat branch after")
        hb_branch = hb_branch or branch + "-heartbeat"
        git(["remote", "get-url", "origin"], deadline)
        blob = git(["hash-object", "-w", BEAT], deadline)
        tree = git(["mktree"], deadline, "100644 blob %s\theartbeat.json\n" % blob)
        parent = ""
        try:
            git(["fetch", "--quiet", "--no-tags", "origin", "+refs/heads/%s:%s" % (hb_branch, PARENT_REF)], deadline)
        except RuntimeError:
            pass   # first heartbeat (branch absent) or offline: keep the local parent if any
        try:
            parent = git(["rev-parse", "--verify", "--quiet", PARENT_REF], deadline)
        except RuntimeError:
            parent = ""
        args = ["-c", "user.name=kit-heartbeat", "-c", "user.email=kit-heartbeat@localhost", "commit-tree", tree,
                "-m", "heartbeat %s %s" % (rec.get("ts_utc", ""), rec.get("run_status", ""))]
        if parent:
            args[args.index("commit-tree") + 2:args.index("commit-tree") + 2] = ["-p", parent]
        sha = git(args, deadline)
        git(["push", "--quiet", "origin", "%s:refs/heads/%s" % (sha, hb_branch)], deadline)
        git(["update-ref", PARENT_REF, sha], deadline)
        K.log_hook(HOOK, "pushed", branch=hb_branch, commit=sha[:12])
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
        K.log_hook(HOOK, "push_failed", branch=hb_branch, problems=[str(e)[:300]])
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass
    return 0


def main() -> int:
    if "--push" in sys.argv:
        return push()
    if "--beat" in sys.argv:
        return beat({"tool_name": "beat"}, 1.0)
    try:
        data = K.read_stdin_json()
    except K.HookInputError:
        data = {}
    return beat(data, float("inf"))


if __name__ == "__main__":
    sys.exit(K.guarded(HOOK, main))
