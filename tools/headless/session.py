"""Session bookkeeping for the headless launchers (launch.sh, launch.ps1, resume.sh). Stdlib only.

  python tools/headless/session.py set key=value ...     # merge into .claude/run-state/session.json (value: JSON or text)
  python tools/headless/session.py get <key>             # print one field ("" when missing)
  python tools/headless/session.py alive                 # session.json's pid: exit 0 alive and its command line names
                                                         # the session id, 1 dead, 2 alive but another process (pid
                                                         # reused), 3 alive but the command line is unreadable
  python tools/headless/session.py denials <stream> <id> # copy the result's permission_denials into denied.jsonl
  python tools/headless/session.py log <message>         # append a timestamped line to .claude/run-state/resume.log

session.json (runtime, git-ignored): {session_id, pid, started, branch, head, mode: "headless", log_path, stream,
launcher, resumes, resumed_at}.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(ROOT, ".claude", "run-state")
SESSION = os.path.join(STATE, "session.json")
LOG = os.path.join(STATE, "resume.log")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load() -> dict:
    try:
        with open(SESSION, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(d: dict) -> None:
    os.makedirs(STATE, exist_ok=True)
    tmp = SESSION + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, SESSION)


def cmdline(pid: int) -> str:
    """The process's command line, "" when it does not exist, None when it cannot be read on this OS."""
    p = "/proc/%d/cmdline" % pid
    if os.path.isdir("/proc/1"):
        try:
            with open(p, "rb") as f:
                return f.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            return ""
    try:
        r = subprocess.run(["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    if os.name == "nt":
        try:
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True, timeout=10)
            return r.stdout if str(pid) in r.stdout else ""
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def alive() -> int:
    d = load()
    try:
        pid = int(d.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        return 1
    cl = cmdline(pid)
    if cl == "":
        return 1
    if cl is None:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return 1
        except OSError:
            pass
        return 3
    sid = str(d.get("session_id") or "")
    if os.name == "nt":
        return 3 if sid else 0
    return 0 if sid and sid in cl else 2


def denials(stream: str, sid: str) -> None:
    rows = []
    try:
        for line in open(stream, encoding="utf-8-sig", errors="replace"):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("type") == "result":
                for d in e.get("permission_denials") or []:
                    rows.append({"ts": now(), "session_id": sid, "tool": d.get("tool_name", ""),
                                 "input": json.dumps(d.get("tool_input", ""))[:500],
                                 "source": "stream-json permission_denials"})
    except OSError:
        pass
    if rows:
        os.makedirs(STATE, exist_ok=True)
        with open(os.path.join(STATE, "denied.jsonl"), "a", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    print("session: %d permission denial(s) from the result logged" % len(rows), file=sys.stderr)


def main() -> int:
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 2
    if a[0] == "set":
        d = load()
        for kv in a[1:]:
            k, _, v = kv.partition("=")
            try:
                d[k] = json.loads(v)
            except ValueError:
                d[k] = v
        save(d)
    elif a[0] == "get" and len(a) == 2:
        v = load().get(a[1], "")
        print(v if isinstance(v, str) else json.dumps(v))
    elif a[0] == "alive":
        return alive()
    elif a[0] == "denials" and len(a) == 3:
        denials(a[1], a[2])
    elif a[0] == "log":
        line = "%s %s" % (now(), " ".join(a[1:]))
        os.makedirs(STATE, exist_ok=True)
        with open(LOG, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
        print("resume: " + " ".join(a[1:]), file=sys.stderr)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
