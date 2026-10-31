# Incident notes

Isolation Forest + robust z-scores on hourly payment metrics. Notes drafted by: none; every number verified against the evidence pack.

## Incident 1

2026-10-14 14:00 to 2026-10-14 17:00 (3h): 5xx error rate rose from 0.33% to 2.27% (+586.9%); payment success rate fell from 97.79% to 94.37% (-3.5%).
Did not move: transactions per hour, p95 latency.
Look first at an upstream partner or acquiring bank - check the per-bank success split and the 5xx origin.

*source: template (no API key)*

<details><summary>evidence</summary>

```json
{
  "window_start": "2026-10-14 14:00",
  "window_end": "2026-10-14 17:00",
  "duration_hours": 3,
  "moved": [
    {
      "metric": "error_rate_5xx",
      "label": "5xx error rate",
      "unit": "%",
      "baseline": 0.33,
      "incident": 2.27,
      "change_pct": 586.9,
      "max_abs_z": 48.2
    },
    {
      "metric": "success_rate",
      "label": "payment success rate",
      "unit": "%",
      "baseline": 97.79,
      "incident": 94.37,
      "change_pct": -3.5,
      "max_abs_z": 18.2
    }
  ],
  "did_not_move": [
    {
      "metric": "txn_volume",
      "label": "transactions per hour",
      "unit": "",
      "baseline": 6023.0,
      "incident": 5883.67,
      "change_pct": -2.3,
      "max_abs_z": 1.1
    },
    {
      "metric": "p95_latency_ms",
      "label": "p95 latency",
      "unit": "ms",
      "baseline": 469.07,
      "incident": 481.54,
      "change_pct": 2.7,
      "max_abs_z": 2.1
    }
  ]
}
```
</details>

## Incident 2

2026-10-21 02:00 to 2026-10-21 04:00 (2h): p95 latency rose from 425ms to 1,364ms (+221.3%).
Did not move: payment success rate, transactions per hour, 5xx error rate.
Look first at a deploy or a slow dependency - check the release log and database/cache latency for the window.

*source: template (no API key)*

<details><summary>evidence</summary>

```json
{
  "window_start": "2026-10-21 02:00",
  "window_end": "2026-10-21 04:00",
  "duration_hours": 2,
  "moved": [
    {
      "metric": "p95_latency_ms",
      "label": "p95 latency",
      "unit": "ms",
      "baseline": 424.57,
      "incident": 1363.94,
      "change_pct": 221.3,
      "max_abs_z": 42.5
    }
  ],
  "did_not_move": [
    {
      "metric": "success_rate",
      "label": "payment success rate",
      "unit": "%",
      "baseline": 97.78,
      "incident": 97.89,
      "change_pct": 0.1,
      "max_abs_z": 1.4
    },
    {
      "metric": "txn_volume",
      "label": "transactions per hour",
      "unit": "",
      "baseline": 2360.0,
      "incident": 2373.0,
      "change_pct": 0.6,
      "max_abs_z": 0.9
    },
    {
      "metric": "error_rate_5xx",
      "label": "5xx error rate",
      "unit": "%",
      "baseline": 0.36,
      "incident": 0.35,
      "change_pct": -4.1,
      "max_abs_z": 0.9
    }
  ]
}
```
</details>
