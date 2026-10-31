#!/usr/bin/env python3
"""Anomaly Narrator - the detector finds the spike; the narrator writes the first incident note.

1. Synthesize three weeks of hourly payment metrics (success rate, volume, p95 latency,
   5xx error rate) with daily seasonality, then inject two incidents.
2. Detect: Isolation Forest on the multivariate hourly vector + robust z-scores per metric
   (rolling median / MAD) to say WHICH metrics moved and in which direction.
3. Group flagged hours into incidents and build an evidence pack: window, each metric's
   baseline vs incident value, % change, z-score - including the metrics that did NOT move.
4. Narrate: with GEMINI_API_KEY or ANTHROPIC_API_KEY set, an LLM drafts the note
   (what moved, what didn't, where to look first). Every number it writes is checked
   against the evidence pack; if it invents one, the deterministic template is used.
   Without a key you get the template. The detector decides what is real; the LLM only
   explains it.

Run:  python anomaly_narrator.py
Out:  incidents.md, timeline.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

sys.path.insert(0, str(Path(__file__).parent))
import llm  # noqa: E402

RNG = np.random.default_rng(7)
METRICS = {
    "success_rate":   ("payment success rate", "%",  "down_is_bad"),
    "txn_volume":     ("transactions per hour", "",   "either"),
    "p95_latency_ms": ("p95 latency", "ms",           "up_is_bad"),
    "error_rate_5xx": ("5xx error rate", "%",         "up_is_bad"),
}


def make_metrics(days: int = 21) -> pd.DataFrame:
    idx = pd.date_range("2026-10-06", periods=days * 24, freq="h")
    hour = idx.hour.values
    season = 1 + 0.45 * np.sin((hour - 9) / 24 * 2 * np.pi)          # busy afternoons
    vol = (4200 * season * (1 + 0.04 * RNG.standard_normal(len(idx)))).round()
    succ = 97.8 + 0.25 * RNG.standard_normal(len(idx))
    lat = 410 + 40 * season + 18 * RNG.standard_normal(len(idx))
    err = 0.35 + 0.06 * RNG.standard_normal(len(idx))
    d = pd.DataFrame({"success_rate": succ, "txn_volume": vol,
                      "p95_latency_ms": lat, "error_rate_5xx": err}, index=idx)

    # Incident 1: a bank partner degrades - success down, 5xx up, volume ok (Oct 14, 14:00-16:00)
    w1 = (idx >= "2026-10-14 14:00") & (idx <= "2026-10-14 16:00")
    d.loc[w1, "success_rate"] -= np.array([3.1, 4.6, 2.2])
    d.loc[w1, "error_rate_5xx"] += np.array([1.9, 2.8, 1.1])

    # Incident 2: a slow deploy - latency triples, nothing else moves (Oct 21, 02:00-03:00)
    w2 = (idx >= "2026-10-21 02:00") & (idx <= "2026-10-21 03:00")
    d.loc[w2, "p95_latency_ms"] *= np.array([2.9, 3.4])

    d["error_rate_5xx"] = d["error_rate_5xx"].clip(lower=0.02)
    return d.round(2)


def robust_z(s: pd.Series, window: int = 24 * 7) -> pd.Series:
    med = s.rolling(window, min_periods=48).median().shift(1)
    mad = (s - med).abs().rolling(window, min_periods=48).median().shift(1)
    return ((s - med) / (1.4826 * mad.replace(0, np.nan))).fillna(0)


def detect(d: pd.DataFrame) -> pd.DataFrame:
    z = pd.DataFrame({m: robust_z(d[m]) for m in METRICS}, index=d.index)
    # time-of-day normalised features for the forest
    feats = d.copy()
    for m in METRICS:
        hourly_med = d[m].groupby(d.index.hour).transform("median")
        feats[m] = d[m] - hourly_med
    forest = IsolationForest(n_estimators=300, contamination=0.012, random_state=7)
    flag_if = forest.fit_predict(feats.values) == -1
    flag_z = (z.abs() > 5).any(axis=1).values
    out = d.copy()
    out["flag"] = flag_if & flag_z           # both detectors must agree
    for m in METRICS:
        out[f"z_{m}"] = z[m].round(1)
    return out


def incidents(flagged: pd.DataFrame) -> list[dict]:
    """Group consecutive flagged hours; build the evidence pack for each."""
    groups, cur = [], []
    for ts, row in flagged.iterrows():
        if row.flag:
            if cur and (ts - cur[-1]) > pd.Timedelta(hours=1):
                groups.append(cur); cur = []
            cur.append(ts)
    if cur:
        groups.append(cur)

    packs = []
    for g in groups:
        start, end = g[0], g[-1]
        base_win = flagged.loc[start - pd.Timedelta(days=7): start - pd.Timedelta(hours=1)]
        base_win = base_win[base_win.index.hour.isin([t.hour for t in g])]   # same hours, prior days
        inc = flagged.loc[start:end]
        moved, steady = [], []
        for m, (label, unit, _) in METRICS.items():
            b, v = float(base_win[m].median()), float(inc[m].mean())
            pct = (v - b) / b * 100 if b else 0.0
            zmax = float(inc[f"z_{m}"].abs().max())
            item = {"metric": m, "label": label, "unit": unit,
                    "baseline": round(b, 2), "incident": round(v, 2),
                    "change_pct": round(pct, 1), "max_abs_z": round(zmax, 1)}
            (moved if zmax > 5 else steady).append(item)
        packs.append({
            "window_start": start.strftime("%Y-%m-%d %H:%M"),
            "window_end": (end + pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
            "duration_hours": len(g),
            "moved": sorted(moved, key=lambda x: -x["max_abs_z"]),
            "did_not_move": steady,
        })
    return packs


def fmt(v: float, unit: str) -> str:
    s = f"{v:,.0f}" if unit == "" or unit == "ms" else f"{v:g}"
    return f"{s}{unit}" if unit != "%" else f"{s}%"


LOOK_FIRST = {
    ("success_rate", "error_rate_5xx"): "an upstream partner or acquiring bank - check the per-bank success split and the 5xx origin",
    ("p95_latency_ms",): "a deploy or a slow dependency - check the release log and database/cache latency for the window",
    ("txn_volume",): "traffic shape - check the top merchants and any marketing or platform events",
}


def template_note(ev: dict) -> str:
    moved = ev["moved"]
    parts = []
    for m in moved:
        arrow = "fell" if m["change_pct"] < 0 else "rose"
        parts.append(f"{m['label']} {arrow} from {fmt(m['baseline'], m['unit'])} to "
                     f"{fmt(m['incident'], m['unit'])} ({m['change_pct']:+g}%)")
    line1 = f"{ev['window_start']} to {ev['window_end']} ({ev['duration_hours']}h): " + "; ".join(parts) + "."
    line2 = "Did not move: " + ", ".join(s["label"] for s in ev["did_not_move"]) + "." if ev["did_not_move"] else ""
    key = tuple(sorted(m["metric"] for m in moved))
    look = next((v for k, v in LOOK_FIRST.items() if set(k) == set(key)), None) or \
        LOOK_FIRST[("success_rate", "error_rate_5xx")] if "success_rate" in key else \
        next((v for k, v in LOOK_FIRST.items() if set(k) & set(key)), "the release log for the window")
    return "\n".join(x for x in [line1, line2, f"Look first at {look}."] if x)


SYSTEM = """You write the first draft of a payments incident note for an on-call engineer.
Format: three short lines.
1) The window and what moved - metric, baseline -> incident value, % change. Plain English.
2) "Did not move:" the metrics that stayed flat (this is diagnostic - say it).
3) "Look first at ..." one concrete place to start, inferred from WHICH metrics moved together.
Use ONLY numbers present in the evidence. Never compute new numbers or re-round. No jargon about models."""


def narrate(ev: dict) -> tuple[str, str]:
    text = llm.complete(SYSTEM, json.dumps(ev, indent=2), max_tokens=260)
    if text is None:
        return template_note(ev), "template (no API key)"
    bad = llm.unpinned(text, ev)
    if bad:
        return template_note(ev), f"template (LLM invented numbers: {sorted(bad)})"
    return text, f"llm ({llm.provider()})"


def plot(flagged: pd.DataFrame, packs: list[dict]):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(METRICS), 1, figsize=(11, 8), sharex=True)
    for ax, (m, (label, unit, _)) in zip(axes, METRICS.items()):
        ax.plot(flagged.index, flagged[m], lw=1, color="#4A6FA5")
        for p in packs:
            ax.axvspan(pd.Timestamp(p["window_start"]), pd.Timestamp(p["window_end"]),
                       color="#d9534f", alpha=0.18)
        ax.set_ylabel(f"{label}\n{unit}".strip(), fontsize=8)
        ax.grid(alpha=0.2)
    axes[0].set_title("Hourly payment metrics · shaded = detected incident")
    plt.tight_layout()
    plt.savefig("timeline.png", dpi=130)


def main():
    d = make_metrics()
    flagged = detect(d)
    packs = incidents(flagged)
    print(f"{len(d)} hourly points · {int(flagged.flag.sum())} flagged hours · "
          f"{len(packs)} incidents · LLM provider: {llm.provider()}\n")

    out = ["# Incident notes", "",
           "Isolation Forest + robust z-scores on hourly payment metrics. "
           f"Notes drafted by: {llm.provider()}; every number verified against the evidence pack.", ""]
    for i, ev in enumerate(packs, 1):
        note, src = narrate(ev)
        print(f"── incident {i}  [{src}]")
        print(note, "\n")
        out += [f"## Incident {i}", "", note, "", f"*source: {src}*", "",
                "<details><summary>evidence</summary>", "", "```json",
                json.dumps(ev, indent=2), "```", "</details>", ""]
    Path("incidents.md").write_text("\n".join(out), encoding="utf-8")
    plot(flagged, packs)
    print("wrote incidents.md and timeline.png")


if __name__ == "__main__":
    main()
