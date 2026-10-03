"""PermissionRequest hook: in headless runs nobody answers a permission prompt, so every request is denied at once
(never a hang), with a message telling Claude to skip it, and appended to .claude/run-state/denied.jsonl
(ts, session_id, tool, input summary). Interactive sessions are untouched (no output: the normal prompt shows).

Headless = env KIT_HEADLESS=1 (set by tools/headless/launch.sh / launch.ps1), or .claude/run-state/session.json
has mode "headless" and this session's id. Output (Claude Code PermissionRequest hook):
  {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                          "decision": {"behavior": "deny", "message": "...", "interrupt": false}}}
The launcher also copies the stream-json result's permission_denials into denied.jsonl (belt and braces).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib as K  # noqa: E402

HOOK = "permission_log"
DENIED = os.path.join(K.STATE, "denied.jsonl")
MESSAGE = ("Not on the allowlist (headless run): this command was skipped and logged in .claude/run-state/denied.jsonl. "
           "Use an allowlisted alternative or move on; do not retry the same command or wrap it in another one.")


def headless(data: dict) -> bool:
    if os.environ.get("KIT_HEADLESS") == "1":
        return True
    try:
        with open(os.path.join(K.STATE, "session.json"), encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        return False
    return s.get("mode") == "headless" and s.get("session_id") in (None, "", data.get("session_id"))


def summary(ti) -> str:
    if isinstance(ti, dict):
        for k in ("command", "file_path", "notebook_path", "url", "pattern", "path"):
            if ti.get(k):
                return str(ti[k])[:500]
    return json.dumps(ti, default=str)[:500]


def main() -> int:
    try:
        data = K.read_stdin_json()
    except K.HookInputError as e:
        K.log_hook(HOOK, "error", problems=["hook input: %s" % e])
        return 0
    tool = data.get("tool_name", "")
    if not headless(data):
        K.log_hook(HOOK, "ignored", tool=tool, reason="interactive session")
        return 0
    rec = {"ts": K.utc_now(), "session_id": data.get("session_id", ""), "tool": tool,
           "input": summary(data.get("tool_input")), "source": "permission_request_hook"}
    try:
        os.makedirs(K.STATE, exist_ok=True)
        with open(DENIED, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass
    K.emit({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                   "decision": {"behavior": "deny", "message": MESSAGE, "interrupt": False}}})
    K.log_hook(HOOK, "denied", tool=tool, input=rec["input"][:300])
    return 0


if __name__ == "__main__":
    sys.exit(K.guarded(HOOK, main))
