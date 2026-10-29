"""Accuracy evaluation: synthetic (fixed seeds) + a subset of the public NAB benchmark.

Usage: python eval/run_eval.py [--no-nab]
Writes eval/results.json and eval/results.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spikelens.detectors import precision_recall, run_detector
from spikelens.synthetic import make_series

DETS = ["robust_z", "ewma", "seasonal", "iforest", "ensemble"]
KINDS = ["spikes", "level_shift", "seasonal_break", "mixed"]
SEEDS = range(10)
OUT = Path(__file__).parent
NAB = "https://raw.githubusercontent.com/numenta/NAB/master"
NAB_FILES = [
    "realKnownCause/machine_temperature_system_failure.csv",
    "realKnownCause/nyc_taxi.csv",
    "realKnownCause/ambient_temperature_system_failure.csv",
    "realKnownCause/cpu_utilization_asg_misconfiguration.csv",
    "realKnownCause/ec2_request_latency_system_failure.csv",
    "realAWSCloudwatch/ec2_cpu_utilization_825cc2.csv",
    "realAWSCloudwatch/rds_cpu_utilization_cc0c53.csv",
    "realTraffic/speed_7578.csv",
]


def synthetic() -> dict:
    out: dict = {}
    for seasonal in (True, False):
        for kind in KINDS:
            if not seasonal and kind == "seasonal_break":
                continue
            key = f"{kind}{'' if seasonal else ' (no seasonality)'}"
            out[key] = {}
            for d in DETS:
                ms = []
                for seed in SEEDS:
                    s = make_series(n=1440, period=60, kind=kind, seed=seed, amplitude=10.0 if seasonal else 0.0)
                    ms.append(precision_recall(run_detector(d, s.values).flags, s.labels, tolerance=2))
                out[key][d] = {m: round(float(np.mean([x[m] for x in ms])), 3) for m in ("precision", "recall", "f1")}
    return out


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def nab() -> dict:
    windows = json.loads(_get(f"{NAB}/labels/combined_windows.json"))
    out: dict = {}
    for f in NAB_FILES:
        rows = _get(f"{NAB}/data/{f}").decode().strip().splitlines()[1:]
        ts = [datetime.fromisoformat(r.split(",")[0]) for r in rows]
        vals = [float(r.split(",")[1]) for r in rows]
        wins = [(datetime.fromisoformat(a.split(".")[0]), datetime.fromisoformat(b.split(".")[0])) for a, b in windows[f]]
        in_win = np.array([any(a <= t <= b for a, b in wins) for t in ts])
        out[f] = {"points": len(vals), "windows": len(wins)}
        for d in DETS:
            flags = np.array(run_detector(d, vals).flags)
            hit = sum(bool(flags[[a <= t <= b for t in ts]].any()) for a, b in wins)
            n_flag = int(flags.sum())
            prec = float((flags & in_win).sum() / n_flag) if n_flag else 0.0
            rec = hit / len(wins) if wins else 0.0
            f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            out[f][d] = {"window_recall": round(rec, 3), "flag_precision": round(prec, 3), "f1": round(f1, 3), "flags": n_flag}
    return out


def to_md(syn: dict, nabres: dict | None) -> str:
    lines = ["## Synthetic benchmark (mean over 10 seeds, 1440 points each, ±2-point tolerance)", "",
             "| scenario | " + " | ".join(DETS) + " |", "|---|" + "---|" * len(DETS)]
    for k, v in syn.items():
        lines.append(f"| {k} | " + " | ".join(f"P {v[d]['precision']:.2f} / R {v[d]['recall']:.2f} / **F1 {v[d]['f1']:.2f}**" for d in DETS) + " |")
    if nabres:
        lines += ["", "## NAB subset (event-window metrics)", "",
                  "window_recall = fraction of labelled anomaly windows containing >=1 flag; flag_precision = fraction of flags inside a window.", "",
                  "| file | windows | " + " | ".join(DETS) + " |", "|---|---|" + "---|" * len(DETS)]
        for f, v in nabres.items():
            lines.append(f"| {f.split('/')[-1]} | {v['windows']} | " + " | ".join(
                f"R {v[d]['window_recall']:.2f} / P {v[d]['flag_precision']:.2f} ({v[d]['flags']} flags)" for d in DETS) + " |")
        avg = {d: np.mean([v[d]["f1"] for v in nabres.values()]) for d in DETS}
        avgr = {d: np.mean([v[d]["window_recall"] for v in nabres.values()]) for d in DETS}
        avgp = {d: np.mean([v[d]["flag_precision"] for v in nabres.values()]) for d in DETS}
        lines.append("| **mean** | | " + " | ".join(f"R {avgr[d]:.2f} / P {avgp[d]:.2f} / F1 {avg[d]:.2f}" for d in DETS) + " |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-nab", action="store_true")
    a = ap.parse_args()
    syn = synthetic()
    nabres = None
    if not a.no_nab:
        try:
            nabres = nab()
        except Exception as e:  # network unavailable
            print(f"NAB download failed ({e}); synthetic only")
    (OUT / "results.json").write_text(json.dumps({"synthetic": syn, "nab": nabres}, indent=2))
    md = to_md(syn, nabres)
    (OUT / "results.md").write_text(md)
    print(md)
