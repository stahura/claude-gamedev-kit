"""The only way to call a paid API in a run: enforces the per-service cap from kit.json and keeps a spend ledger.

Usage:
  python tools/paid.py <service> [--estimate N | --estimate-cmd "<dry-run command>"] -- <command ...>
  python tools/paid.py <service> --status
Steps: read the ledger (.claude/run-state/spend.json); get an estimate (explicit, from a dry-run command parsed with
estimate_regex, or the service's default_estimate); refuse (exit 3) when used + estimate > cap; read the balance
(balance_cmd + balance_regex) before and after; run the command; record the actual cost (balance drop, else the
estimate); mirror the totals into run-state.json. The pre_tool_guard hook denies the service's binaries outside this
wrapper. For a hard cap, also give the run its own API key/account holding only the budget (see README).
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".claude", "hooks"))
import kitlib as K  # noqa: E402

LEDGER = os.path.join(K.STATE, "spend.json")


def load_ledger() -> dict:
    try:
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_ledger(led: dict) -> None:
    os.makedirs(K.STATE, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8", newline="\n") as f:
        json.dump(led, f, indent=2)
    rs_path = os.path.join(K.ROOT, "run-state.json")
    try:
        with open(rs_path, encoding="utf-8") as f:
            rs = json.load(f)
    except (OSError, ValueError):
        rs = {}
    rs["spend"] = {k: {"cap": v.get("cap"), "used": v.get("used", 0)} for k, v in led.items()}
    with open(rs_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rs, f, indent=2)


def run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=K.ROOT)


def balance(svc: dict):
    if not svc.get("balance_cmd"):
        return None
    r = run(svc["balance_cmd"])
    m = re.search(svc.get("balance_regex", r"(\d+(?:\.\d+)?)"), r.stdout + r.stderr)
    return float(m.group(1)) if m else None


def main() -> int:
    argv = sys.argv[1:]
    cmd_parts = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd_parts = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("service")
    ap.add_argument("--estimate", type=float)
    ap.add_argument("--estimate-cmd")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    cfg = K.config()
    svc = cfg.get("paid_services", {}).get(a.service)
    if svc is None:
        print("paid.py: unknown service %r (add it to kit.json paid_services)" % a.service, file=sys.stderr)
        return 2
    led = load_ledger()
    entry = led.setdefault(a.service, {"cap": svc["cap"], "used": 0, "jobs": []})
    entry["cap"] = svc["cap"]
    if a.status:
        print(json.dumps({"service": a.service, "cap": entry["cap"], "used": entry["used"],
                          "left": entry["cap"] - entry["used"], "balance": balance(svc)}))
        return 0
    if not cmd_parts:
        print("paid.py: no command after --", file=sys.stderr)
        return 2
    est = a.estimate
    if est is None and a.estimate_cmd:
        r = run(a.estimate_cmd)
        m = re.search(svc.get("estimate_regex", r"(\d+(?:\.\d+)?)"), r.stdout + r.stderr)
        est = float(m.group(1)) if m else None
    if est is None:
        est = float(svc.get("default_estimate", svc["cap"]))   # unknown cost: assume the worst
    if entry["used"] + est > svc["cap"]:
        print("PAID REFUSED %s: used %.1f + estimate %.1f > cap %.1f" % (a.service, entry["used"], est, svc["cap"]))
        return 3
    b0 = balance(svc)
    cmd = subprocess.list2cmdline(cmd_parts) if os.name == "nt" else " ".join(shlex.quote(c) for c in cmd_parts)
    t0 = time.time()
    r = subprocess.run(cmd, shell=True, cwd=K.ROOT)
    b1 = balance(svc)
    cost = (b0 - b1) if (b0 is not None and b1 is not None) else est
    entry["used"] = round(entry["used"] + max(cost, 0.0), 3)
    entry["jobs"].append({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": cmd, "estimate": est, "cost": cost,
                          "balance_before": b0, "balance_after": b1, "exit": r.returncode,
                          "seconds": round(time.time() - t0, 1)})
    save_ledger(led)
    print("PAID %s: cost %.1f (estimate %.1f), used %.1f / cap %.1f, exit %d" % (
        a.service, cost, est, entry["used"], svc["cap"], r.returncode))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
