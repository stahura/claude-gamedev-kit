"""PreToolUse guard for Bash, PowerShell and the file tools (works in bypass-permissions mode too).

Denies:
  - paid-API binaries (kit.json paid_services[*].binaries) unless the command goes through `python tools/paid.py`,
  - deletes outside the project (and the paths in allowed_delete_roots), and deletes on variable paths that may be
    empty (`rm -f "$S"/*`: the prompt that stalled a run-2 reviewer all night),
  - force pushes, remote branch/tag deletes, repo/release deletes, moving or deleting tags (run tags anchor the art
    gate),
  - writes to .claude/run-state/ (stored review verdicts, ledgers, counters): Write/Edit/MultiEdit/NotebookEdit on any
    path inside it, and shell commands whose write TARGET resolves inside it: redirections (>, >>, 2>, &>, *>), tee,
    cp/mv/install/ln destinations (mv sources too), rm/rmdir/del/touch/truncate/mkdir/shred operands, dd of=,
    sed -i files, find -delete roots, PowerShell Set-Content/Add-Content/Out-File/New-Item/Clear-Content/Remove-Item/
    Rename-Item paths and Copy-Item/Move-Item destinations; `cd` into the folder first counts. Heredoc bodies and the
    text arguments of other commands (echo, printf, git commit -m, grep, cat) are never scanned, so a mention of the
    path in text is not a write. Only the hooks and tools write there.
Anything else is allowed (exit 0 with no output). Denies are logged to .claude/run-state/hooks.log.jsonl. It stops
accidents, not intent: any interpreter can still write anything (README, "Making the spend cap real").
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib as K  # noqa: E402

HOOK = "pre_tool_guard"
DESTRUCTIVE_GIT = [
    (r"\bgit\s+push\b[^\n;&|]*\s(--force\b|-f\b|--force-with-lease\b)", "force push"),
    (r"\bgit\s+push\b[^\n;&|]*\s(--delete\b|:refs/)", "remote branch/tag delete"),
    (r"\bgit\s+tag\b[^\n;&|]*\s(-f\b|--force\b|-d\b|--delete\b)", "moving or deleting a tag"),
    (r"\bgh\s+repo\s+delete\b", "repo delete"),
    (r"\bgh\s+release\s+delete(\s|$)", "release delete (use `gh release delete-asset` for old zips)"),
    (r"\bgit\s+reset\s+--hard\b[^\n;&|]*\borigin/", "hard reset to a remote on a pushed branch"),
]
FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
OPS = sorted(["&>>", "&>", "*>>", "*>", ">>", ">|", ">&", ">", "<<<", "<<", "<", "&&", "||", "|&", "|", ";", "&", "\n",
              "(", ")"], key=len, reverse=True)
FD_REDIRECT = re.compile(r"^\d+(>>|>&|>)")
SEPARATORS = {"&&", "||", "|&", "|", ";", "&", "\n", "(", ")"}
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][\w.-]*)\1")
DELETES = {"rm", "rmdir", "del", "erase", "rd", "remove-item", "ri", "unlink"}
CREATES = {"touch", "truncate", "mkdir", "md", "shred", "new-item", "ni", "clear-content", "clc"}
PS_WRITERS = {"set-content", "sc", "add-content", "ac", "out-file", "new-item", "ni", "clear-content", "clc",
              "remove-item", "ri", "rename-item", "rni", "ren"}
PS_COPY = {"copy-item", "cpi", "copy", "move-item", "mi", "move"}
PS_SWITCHES = {"recurse", "force", "append", "nonewline", "passthru", "noclobber", "container", "whatif", "confirm"}
WRAPPERS = {"sudo", "env", "command", "nohup", "time", "nice", "exec", "builtin", "xargs"}


# --- shell parsing (POSIX shells and PowerShell, good enough for literal paths) ---

def strip_heredocs(cmd: str) -> str:
    """Drop heredoc bodies (<<EOF ... EOF) and PowerShell here-strings (@' ... '@): they are data, not commands."""
    cmd = re.sub(r"@'\r?\n.*?\r?\n'@", "''", cmd, flags=re.S)
    cmd = re.sub(r'@"\r?\n.*?\r?\n"@', "''", cmd, flags=re.S)
    out, waiting = [], []
    for line in cmd.split("\n"):
        if waiting:
            if line.strip() == waiting[0]:
                waiting.pop(0)
            continue
        out.append(line)
        waiting = [m.group(2) for m in HEREDOC.finditer(line)]
    return "\n".join(out)


def tokenize(cmd: str) -> list:
    """[(text, is_op)]: quotes removed (quoted operators stay words), backslashes literal except before a shell
    metacharacter (Windows paths survive), `2>` / `*>` style redirections as operators."""
    out, buf, has, i, n = [], [], False, 0, len(cmd)

    def flush():
        nonlocal buf, has
        if has:
            out.append(("".join(buf), False))
        buf, has = [], False
    while i < n:
        c = cmd[i]
        if c in "'\"":
            j = i + 1
            while j < n and cmd[j] != c:
                j += 2 if (c == '"' and cmd[j] == "\\" and j + 1 < n and cmd[j + 1] in '"\\$`') else 1
            seg = cmd[i + 1:j]
            buf.append(re.sub(r'\\(["\\$`])', r"\1", seg) if c == '"' else seg)
            has, i = True, j + 1
            continue
        if c == "\\" and i + 1 < n and cmd[i + 1] in " \t\"'$`;&|<>()\n":
            buf.append(cmd[i + 1])
            has, i = True, i + 2
            continue
        if c in " \t\r":
            flush()
            i += 1
            continue
        if not has:
            m = FD_REDIRECT.match(cmd, i)
            if m:
                out.append((m.group(1), True))
                i = m.end()
                continue
        op = next((o for o in OPS if cmd.startswith(o, i)), None)
        if op:
            flush()
            out.append((op, True))
            i += len(op)
            continue
        buf.append(c)
        has, i = True, i + 1
    flush()
    return out


def simple_commands(cmd: str) -> list:
    """[(words, redirect targets)] per simple command."""
    cmds, words, targets, toks, i = [], [], [], tokenize(cmd), 0
    while i < len(toks):
        text, is_op = toks[i]
        if is_op and text in SEPARATORS:
            if words or targets:
                cmds.append((words, targets))
            words, targets = [], []
        elif is_op and ">" in text:
            if i + 1 < len(toks) and not toks[i + 1][1]:
                t = toks[i + 1][0]
                if not (text == ">&" and (t.isdigit() or t == "-")) and not re.match(r"^&?\d$", t):
                    targets.append(t)
                i += 1
        elif is_op and text in ("<", "<<", "<<<"):
            i += 1   # input redirection: its operand is not a write
        elif not is_op:
            words.append(text)
        i += 1
    if words or targets:
        cmds.append((words, targets))
    return cmds


def _name(w: str) -> str:
    b = re.split(r"[\\/]", w)[-1].lower()
    return b[:-4] if b.endswith(".exe") else b


def _operands(args: list, takes_value=()) -> list:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a == "--":
            continue
        elif a.startswith("-") and len(a) > 1:
            skip = a in takes_value
        else:
            out.append(a)
    return out


def _ps_args(args: list):
    """PowerShell (named {param: value}, positional [values])."""
    named, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("-") and len(a) > 1 and not re.match(r"^-\d", a):
            key = a[1:].split(":", 1)[0].lower()
            if ":" in a or key in PS_SWITCHES or i + 1 >= len(args) or args[i + 1].startswith("-"):
                named[key] = a.split(":", 1)[1] if ":" in a else True
            else:
                named[key] = args[i + 1]
                i += 1
        else:
            pos.append(a)
        i += 1
    return named, pos


def write_targets(words: list) -> list:
    """Paths a simple command writes, deletes or creates (literal operands only)."""
    while words and (re.match(r"^\w+=", words[0]) or _name(words[0]) in WRAPPERS):
        words = words[1:]
        while words and words[0].startswith("-"):
            words = words[1:]
    if not words:
        return []
    name, args = _name(words[0]), words[1:]
    if name == "tee":
        return _operands(args)
    if name in ("cp", "install", "ln"):
        t = [a.split("=", 1)[1] for a in args if a.startswith("--target-directory=")]
        if "-t" in args and args.index("-t") + 1 < len(args):
            t.append(args[args.index("-t") + 1])
        ops = _operands(args, ("-t", "-m", "-o", "-g", "-S", "--suffix"))
        return t or ops[-1:]
    if name == "mv":
        return _operands(args, ("-t", "-S", "--suffix"))          # sources disappear, the destination changes
    if name == "dd":
        return [a[3:] for a in args if a.startswith("of=")]
    if name == "sed" and any(a.startswith("-i") or a.startswith("--in-place") for a in args):
        script_given = any(a in ("-e", "-f") or a.startswith(("--expression", "--file")) for a in args)
        ops = _operands(args, ("-e", "-f", "-l"))
        return ops if script_given else ops[1:]
    if name == "find" and "-delete" in args:
        return [a for a in args[:next((i for i, a in enumerate(args) if a.startswith(("-", "(", "!"))), len(args))]]
    if name in PS_COPY:
        named, pos = _ps_args(args)
        dest = [named[k] for k in ("destination",) if isinstance(named.get(k), str)] or pos[1:2]
        if name in ("move-item", "mi", "move"):
            dest += [named[k] for k in ("path", "literalpath") if isinstance(named.get(k), str)] or pos[:1]
        if name in ("copy", "move") and not named:
            dest = pos[-1:] + (pos[:-1] if name == "move" else [])
        return dest
    if name in PS_WRITERS:
        named, pos = _ps_args(args)
        got = [named[k] for k in ("path", "literalpath", "filepath") if isinstance(named.get(k), str)]
        if name in ("new-item", "ni") and isinstance(named.get("name"), str):
            got.append(os.path.join(got[0] if got else ".", named["name"]))
        return got or pos[:1] if name not in DELETES | {"remove-item"} else got + pos
    if name in DELETES or name in CREATES:
        return _operands(args, ("-s", "--size", "-r", "--reference", "-m", "--mode", "-n", "--iterations"))
    return []


def nested_scripts(words: list) -> list:
    """The script string of `bash -c "..."`, `sh -c`, `powershell -Command "..."` (scanned like a command)."""
    if not words:
        return []
    name = _name(words[0])
    if name in ("bash", "sh", "zsh", "dash") and "-c" in words[1:]:
        i = words.index("-c")
        return words[i + 1:i + 2]
    if name in ("powershell", "pwsh"):
        for i, w in enumerate(words[1:], 1):
            if w.lower() in ("-command", "-c") and i + 1 < len(words):
                return [" ".join(words[i + 1:])]
    return []


def shell_writes(cmd: str, cwd: str, depth: int = 0) -> list:
    """[(command name, absolute target)] for every write target of every simple command, following `cd`."""
    out = []
    for words, redirects in simple_commands(strip_heredocs(cmd)):
        name = _name(words[0]) if words else ""
        if name in ("cd", "set-location", "sl", "pushd", "chdir") and len(words) > 1:
            dest = _ps_args(words[1:])[1] or [words[-1]]
            cwd = resolve(dest[0], cwd)
        for t in redirects:
            out.append((">", resolve(t, cwd)))
        for t in write_targets(words):
            out.append((name, resolve(t, cwd)))
        if depth < 2:
            for s in nested_scripts(words):
                out += shell_writes(s, cwd, depth + 1)
    return out


def resolve(path: str, cwd: str) -> str:
    p = os.path.expanduser(str(path).strip().strip("'\""))
    if os.name == "nt" and re.match(r"^/[a-zA-Z]/", p):        # Git Bash /c/... -> C:/...
        p = p[1] + ":" + p[2:]
    elif os.name != "nt":
        p = p.replace("\\", "/")                                # PowerShell-style separators on Linux
    return os.path.normpath(p if os.path.isabs(p) or re.match(r"^[a-zA-Z]:[\\/]", p) else os.path.join(cwd, p))


def in_run_state(path: str, cwd: str = "") -> bool:
    full = os.path.normcase(os.path.realpath(resolve(path, cwd or K.ROOT)))
    rs = os.path.normcase(os.path.realpath(K.STATE))
    return full == rs or full.startswith(rs + os.sep)


def inside_allowed(path: str, cfg: dict) -> bool:
    roots = [os.path.realpath(os.path.join(K.ROOT, r)) for r in cfg.get("allowed_delete_roots", ["."])]
    extra = os.environ.get("KIT_SCRATCH_DIRS", "")
    roots += [os.path.realpath(p) for p in extra.split(os.pathsep) if p]
    p = path.strip().strip("'\"")
    # C:\ or C:/ (drive), \\server or //server (UNC), \x (root of the current drive in PowerShell/cmd).
    win_abs = bool(re.match(r"^[a-zA-Z]:[\\/]", p) or p.startswith("\\") or re.match(r"^//[^/]", p))
    if os.name != "nt":
        # Drive-letter and UNC paths are absolute on every OS; on Linux/macOS they can never be inside the project.
        if win_abs:
            return False
    elif re.match(r"^/[a-zA-Z]/", p):        # Git Bash /c/... -> C:/...
        p = p[1] + ":" + p[2:]
    full = os.path.realpath(p if (os.path.isabs(p) or win_abs) else os.path.join(K.ROOT, p))
    return any(full == r or full.startswith(r + os.sep) for r in roots)


def deny(reason: str, data: dict = None) -> int:
    K.emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "kit guard: " + reason}})
    d = data or {}
    ti = d.get("tool_input") or {}
    K.log_hook(HOOK, "denied", tool=d.get("tool_name"), reason=reason[:300],
               input=str(ti.get("command") or ti.get("file_path") or ti.get("notebook_path") or "")[:300])
    return 0


def main() -> int:
    try:
        data = K.read_stdin_json()
    except K.HookInputError as e:
        return deny("unreadable hook input (%s): denied (fail closed)" % e)
    cfg = K.config()
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or K.ROOT
    if data.get("tool_name") in FILE_TOOLS:
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        if path and in_run_state(path, cwd):
            return deny(".claude/run-state/ is written only by the kit's hooks and tools (stored verdicts, ledgers): "
                        "use tools/review.py, tools/paid.py or tools/perf_gate.py.", data)
        return 0
    cmd = str(ti.get("command", ""))
    if not cmd:
        return 0
    code = strip_heredocs(cmd)
    for rx, what in DESTRUCTIVE_GIT:
        if re.search(rx, code):
            return deny("%s is not allowed in unattended runs." % what, data)
    writes = shell_writes(cmd, cwd)
    hit = [(n, t) for n, t in writes if in_run_state(t)]
    if hit:
        return deny("shell write into .claude/run-state/ (%s %s): only the kit's hooks and tools write there." % (
            hit[0][0], os.path.relpath(hit[0][1], K.ROOT) if hit[0][1].startswith(K.ROOT) else hit[0][1]), data)
    for name, svc in cfg.get("paid_services", {}).items():
        for b in svc.get("binaries", []):
            if re.search(r"(^|[\s;&|(\"'])%s(\.exe|\.cmd)?(\s|$)" % re.escape(b), code) and "tools/paid.py" not in code.replace("\\", "/"):
                return deny("%s is a paid API: run it as `python tools/paid.py %s [--estimate N] -- <command>` "
                            "(spend cap and ledger)." % (b, name), data)
    for words, _ in simple_commands(code):
        if not words or _name(words[0]) not in DELETES:
            continue
        for t in write_targets(words):
            if re.search(r"\$\{?\w+\}?", t) and not re.search(r"\$\{\w+:\?", t):
                return deny("delete on a variable path (%s): use a literal path or ${VAR:?} so an empty variable "
                            "cannot widen the delete." % t, data)
            if not inside_allowed(t.replace("*", "x"), cfg):
                return deny("delete outside the project (%s). Only the project, %s and KIT_SCRATCH_DIRS may be "
                            "deleted from." % (t, ", ".join(cfg.get("allowed_delete_roots", []))), data)
    return 0


def _fail_closed(e) -> None:
    deny("guard error (%s): denied (fail closed)" % type(e).__name__)


if __name__ == "__main__":
    sys.exit(K.guarded(HOOK, main, on_error=_fail_closed))
