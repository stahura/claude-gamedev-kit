"""SubagentStop hook (matcher: visual-reviewer): stores the visual-reviewer's verdict; the builder never supplies it.

Finds the reviewer's JSON verdict block, in order: last_assistant_message; the last SubagentHandback tool_use
input (background subagents end with SubagentHandback {"message": <report>}, and plain text after it is not
delivered); any other last tool_use input holding a ```json verdict; the last assistant text in its transcript. Reads
"review_id" from it and stores it in .claude/run-state/reviews/<id>.json (captured_by: subagent_stop) when:
  - the id is a visual review id (<phase>-visualA-r<N> or <phase>-visual-r<N>) started with `tools/review.py start`,
  - the verdict passes kitlib.validate_verdict (every shot x every rubric item, current shot_set_version, floor),
  - the transcript shows the reviewer opened every shot PNG of the current set (Read tool) from one folder that is not
    another round's snapshot (it may also open the previous round's PNGs).
The stored file's sha256 is logged with the "stored" line; `review.py close` refuses a verdict whose file no longer
matches it (tamper check against accidents and hand edits, not a forge-proof seal).
Otherwise: if the reviewer already handed back, a block cannot be acted on (the subagent has ended), so the review is
recorded invalid at once (.pending removed; the builder sees it in run-state.json and starts a new round). Without a
handback it blocks the stop once with the reasons; the second stop records it invalid. The second invalid or
unreviewed round in a row of one stage sets run-state.json status blocked (kitlib.check_failed_streak).
Every call is logged to .claude/run-state/hooks.log.jsonl (outcome stored/blocked/invalid/ignored/error).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib as K  # noqa: E402

AGENT = "visual-reviewer"
HOOK = "subagent_stop"
HANDBACK = "SubagentHandback"
ID_IN_TEXT = re.compile(r"\b(P\d+-visualA?-r\d+)\b")


def _walk(o):
    if isinstance(o, dict):
        yield o
        for x in o.values():
            yield from _walk(x)
    elif isinstance(o, list):
        for x in o:
            yield from _walk(x)


def _strings(o):
    """Every string inside a (possibly nested) tool input, "message" first."""
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        if "message" in o:
            yield from _strings(o["message"])
        for k, x in o.items():
            if k != "message":
                yield from _strings(x)
    elif isinstance(o, list):
        for x in o:
            yield from _strings(x)


def transcript(path: str) -> dict:
    """reads (paths opened with Read), last_text (last assistant text), handback (last SubagentHandback input text or
    None), tool_texts (inputs of other tool_use blocks, in order), prompt (first user text: the builder's prompt)."""
    t = {"reads": [], "last_text": "", "handback": None, "tool_texts": [], "prompt": ""}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, TypeError, ValueError):
        return t
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        for d in _walk(e):
            if d.get("type") != "tool_use":
                continue
            name, inp = str(d.get("name", "")), d.get("input")
            if name == "Read":
                p = (inp or {}).get("file_path") if isinstance(inp, dict) else None
                if p:
                    t["reads"].append(str(p).replace("\\", "/"))
            elif name == HANDBACK or name.endswith("__" + HANDBACK):
                t["handback"] = "\n".join(_strings(inp))
            else:
                text = "\n".join(_strings(inp))
                if "```json" in text or '"verdict"' in text:
                    t["tool_texts"].append(text)
        msg = e.get("message") if isinstance(e, dict) else None
        if isinstance(msg, dict) and msg.get("role") in ("assistant", "user"):
            c = msg.get("content")
            text = c if isinstance(c, str) else "".join(
                x.get("text", "") for x in c or [] if isinstance(x, dict) and x.get("type") == "text")
            if msg["role"] == "assistant" and text.strip():
                t["last_text"] = text
            elif msg["role"] == "user" and text.strip() and not t["prompt"]:
                t["prompt"] = text
    return t


def find_verdict(data: dict, t: dict):
    """(verdict, source) from the first source that holds one, else (None, "")."""
    sources = [("last_assistant_message", data.get("last_assistant_message")), ("handback", t["handback"])]
    sources += [("tool_input", x) for x in reversed(t["tool_texts"])]
    sources.append(("transcript_text", t["last_text"]))
    for src, text in sources:
        if isinstance(text, str) and text.strip():
            try:
                return K.extract_verdict(text), src
            except ValueError:
                continue
    return None, ""


def guess_id(t: dict) -> str:
    """The review id when no verdict carries one: from the builder's prompt, else the only pending visual review."""
    pend = {rid for rid, _ in K.pending_reviews() if K.VISUAL_ID.match(rid)}
    for rid in ID_IN_TEXT.findall(t["prompt"] or ""):
        if rid in pend:
            return rid
    return next(iter(pend)) if len(pend) == 1 else ""


def check(data: dict, cfg: dict, t: dict):
    """(review id or "", verdict or None, source, [problems])."""
    v, src = find_verdict(data, t)
    if v is None:
        return guess_id(t), None, "", ["no JSON verdict block found: end with exactly one fenced JSON verdict, in your "
                                       "SubagentHandback message and as your last plain-text message"]
    rid = str(v.get("review_id", ""))
    if not K.VISUAL_ID.match(rid):
        return rid, v, src, ['"review_id" must be the visual review id you were given (<phase>-visual[A]-r<N>), got %r' % rid]
    if not os.path.exists(os.path.join(K.REVIEWS, rid + ".pending")):
        return rid, v, src, ["review %s was not started with `python tools/review.py start %s`" % (rid, rid)]
    errs = K.validate_verdict(v, rid, cfg)
    try:
        _, names = K.shot_set(cfg)
    except ValueError as e:
        return rid, v, src, errs + [str(e)]
    folders = {}
    for p in t["reads"]:
        d, b = p.rsplit("/", 1) if "/" in p else ("", p)
        if b.lower().endswith(".png") and b[:-4] in names:
            folders.setdefault(d.lower(), set()).add(b[:-4])
    other_round = re.compile(r"/rounds/(?!%s$)[^/]+$" % re.escape(rid.lower()))
    full = [d for d, s in folders.items() if s == set(names) and not other_round.search(d)]
    if not full:
        seen = set().union(*[s for d, s in folders.items() if not other_round.search(d)] or [set()])
        missing = ", ".join(n for n in names if n not in seen) or "none, but they came from different folders"
        errs.append("open every full-size shot PNG of this round's folder with Read before the verdict (not opened: %s)"
                    % missing)
    else:
        full.sort(key=lambda d: (not d.endswith("/rounds/" + rid.lower()), not d.endswith("/final")))
        v["shots_folder"] = full[0]
    return rid, v, src, errs


def main() -> int:
    try:
        data = K.read_stdin_json()
    except K.HookInputError as e:
        K.log_hook(HOOK, "error", problems=["hook input: %s" % e])
        return 0   # nothing to capture; without a stored verdict the phase cannot close (fails safe)
    info = {"agent_type": data.get("agent_type"), "agent_id": data.get("agent_id")}
    if data.get("agent_type", AGENT) != AGENT:
        K.log_hook(HOOK, "ignored", **info)
        return 0
    cfg = K.config()
    t = transcript(data.get("agent_transcript_path", ""))
    handed_back = t["handback"] is not None
    rid, v, src, errs = check(data, cfg, t)
    info.update(review_id=rid, source=src, handback=handed_back)
    if not errs:
        v["captured_by"] = "subagent_stop"
        v["agent_id"] = data.get("agent_id", "")
        v["captured_from"] = src
        sha = K.store_review(rid, v)
        K.log_hook(HOOK, "stored", verdict=v.get("verdict"), sha256=sha, **info)
        return 0
    if not handed_back and not data.get("stop_hook_active"):
        K.emit({"decision": "block", "reason": "Your verdict was not recorded: " + "; ".join(errs) +
                ". Fix this and end again with the complete JSON verdict block (in your SubagentHandback message "
                "and as your last plain-text message)."})
        K.log_hook(HOOK, "blocked", problems=errs[:10], **info)
        return 0
    # Handed back already (a block cannot be acted on) or the second stop: record invalid now.
    blocked = ""
    if K.VISUAL_ID.match(rid or "") and os.path.exists(os.path.join(K.REVIEWS, rid + ".pending")):
        blocked = K.record_invalid(rid, errs)
    K.log_hook(HOOK, "invalid", problems=errs[:10], run_blocked=blocked, **info)
    return 0


if __name__ == "__main__":
    sys.exit(K.guarded(HOOK, main))
