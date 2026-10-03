"""Automated performance gate for visual phases (the visual-reviewer does not judge performance).

  python tools/perf_gate.py --phase P1 <bench log>

Reads the last `BENCH avg_fps=<x> low1_fps=<y>` line of a benchmark log (any engine can print it; Godot:
`render_shots.gd -- --bench=<frames>`), compares it with kit.json visual.perf (min_avg_fps, min_low1_fps; null or
absent = not checked, e.g. offline or asset-only projects) and records the result in .claude/run-state/perf/<phase>.json,
which `tools/review.py close` requires for visual phases. Exit 0 = PERF OK or SKIPPED, 1 = FAIL.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".claude", "hooks"))
import kitlib as K  # noqa: E402

BENCH = re.compile(r"BENCH\s+avg_fps=([\d.]+)\s+low1_fps=([\d.]+)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("log")
    a = ap.parse_args()
    perf = K.visual(K.config()).get("perf") or {}
    lim = {k: perf.get(k) for k in ("min_avg_fps", "min_low1_fps")}
    if all(v is None for v in lim.values()):
        print("PERF SKIPPED (kit.json visual.perf sets no threshold)")
        return 0
    try:
        with open(a.log, encoding="utf-8", errors="replace") as f:
            hits = BENCH.findall(f.read())
    except OSError as e:
        print("PERF FAIL: cannot read %s (%s)" % (a.log, e))
        return 1
    if not hits:
        print("PERF FAIL: no 'BENCH avg_fps=<x> low1_fps=<y>' line in " + a.log)
        return 1
    avg, low = float(hits[-1][0]), float(hits[-1][1])
    errs = []
    if lim["min_avg_fps"] is not None and avg < lim["min_avg_fps"]:
        errs.append("avg %.1f fps < %s" % (avg, lim["min_avg_fps"]))
    if lim["min_low1_fps"] is not None and low < lim["min_low1_fps"]:
        errs.append("1%% low %.1f fps < %s" % (low, lim["min_low1_fps"]))
    os.makedirs(K.PERF, exist_ok=True)
    with open(os.path.join(K.PERF, a.phase + ".json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"avg_fps": avg, "low1_fps": low, "limits": lim, "ok": not errs, "log": a.log}, f, indent=2)
    if errs:
        print("PERF FAIL: " + "; ".join(errs))
        return 1
    print("PERF OK: avg %.1f fps, 1%% low %.1f fps" % (avg, low))
    return 0


if __name__ == "__main__":
    sys.exit(main())
