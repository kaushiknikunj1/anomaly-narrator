# Anomaly Narrator

The anomaly detector I built for payment metrics cut time-to-detect by 70%. It did not cut time-to-*understand* at all. The alert fired, someone woke up, and the next twenty minutes were the same every time: open four dashboards, work out which metrics moved together, work out which ones *didn't*, and type the first line of the incident channel.

This project automates those twenty minutes. The detector still decides what is real. A language model only writes the first draft of the note — and it is not allowed to invent a number.

```
── incident 1  [template (no API key)]
2026-10-14 14:00 to 2026-10-14 17:00 (3h): 5xx error rate rose from 0.33% to 2.27% (+586.9%); payment success rate fell from 97.79% to 94.37% (-3.5%).
Did not move: transactions per hour, p95 latency.
Look first at an upstream partner or acquiring bank - check the per-bank success split and the 5xx origin.
```

That is the deterministic template. With an API key the same evidence pack goes to an LLM, which reasons about *why* those metrics moved together — and is then checked.

## How it works

1. **Data.** Three weeks of hourly payment metrics — success rate, volume, p95 latency, 5xx rate — synthetic, with daily seasonality, and two injected incidents: a partner-bank degradation (success ↓, 5xx ↑, nothing else moves) and a slow deploy (latency ×3, nothing else moves).
2. **Detect.** Two detectors must agree: an Isolation Forest on the time-of-day-normalised multivariate vector, and a robust z-score per metric (rolling median / MAD). The forest says *something is off*; the z-scores say *which metric, which direction*.
3. **Evidence pack.** Flagged hours are grouped into incidents. For each: the window, every metric's same-hour baseline vs incident value, % change, max |z| — including the metrics that stayed flat. "What didn't move" is the most diagnostic line in any incident note and the one humans skip when tired.
4. **Narrate + verify.** The pack goes to an LLM with a three-line format. Every number in the reply is checked against the pack; if any was invented or re-rounded, the deterministic template is used instead and the output says so.

## Run it

```bash
pip install -r requirements.txt
python anomaly_narrator.py
```

Runs with no API key (template notes). For LLM-drafted notes set `GEMINI_API_KEY` (preferred, gemini-2.5-flash) or `ANTHROPIC_API_KEY` (claude-opus-5-5 via the official SDK).

Outputs: `incidents.md` and `timeline.png`.

## Honest limits

- The "look first at" line is where the model adds value and also where it can be confidently wrong. The template version is a lookup on which metrics co-moved; the LLM version reasons. In production I would show both.
- Two detectors agreeing is conservative on purpose. It will miss slow drifts. That's a different alert.

Companion case study: [Payment Metrics Anomaly Detection](https://nikunjkaushik.com/projects/anomaly-detection.html) · essay: [Anomaly detection meets LLMs](https://nikunjkaushik.com/blog/anomaly-detection-llms.html).
