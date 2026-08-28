#!/usr/bin/env python3
"""Run the assembly-line simulator and write a replayable event log.

Usage:
  python scripts/run_sim.py --config configs/automotive_line.yaml \
      --seed 42 --duration 7200 --out data/runs/smoke.jsonl [--mqtt localhost]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.simulation.emit import EventSink      # noqa: E402
from app.simulation.engine import LineSim, load_config  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/automotive_line.yaml")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--duration", type=float, default=7200.0, help="simulated seconds")
    ap.add_argument("--out", default="data/runs/run.jsonl")
    ap.add_argument("--mqtt", default=None, help="MQTT broker host (omit = offline mode)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    sink = EventSink(args.out, mqtt_host=args.mqtt)
    sim = LineSim(cfg, seed=args.seed, sink=sink)
    summary = sim.run(args.duration)
    sink.close()

    size_mb = Path(args.out).stat().st_size / 1e6
    print(f"\n=== SIM SUMMARY — {cfg['site']['name']} ===")
    print(f"seed={args.seed}  duration={args.duration:.0f}s  mqtt={'ONLINE' if sink.mqtt_online else 'offline'}")
    print(f"parts spawned={summary['spawned']}  completed={summary['completed']}  "
          f"scrapped={summary['scrapped']}  FPY={1 - summary['scrapped'] / max(summary['spawned'], 1):.2%}")
    print(f"bad supplier batches detected: {summary['bad_batches'] or 'none'}")
    print("\nTop-8 stations by utilization (bottleneck view):")
    for sid, u in list(summary["utilization"].items())[:8]:
        bar = "#" * int(u * 40)
        print(f"  {sid:>4}  {u:6.2%}  {bar}")
    if summary["defects_sample"]:
        print("\nDefect events (with ground-truth causes):")
        print(json.dumps(summary["defects_sample"], indent=2))
    print(f"\nevents: {summary['event_counts']}")
    print(f"wrote {args.out} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
