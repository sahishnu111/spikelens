"""Parse nginx/apache combined logs and generic timestamped lines into per-minute series."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# 127.0.0.1 - - [10/Oct/2026:13:55:36 +0000] "GET /x HTTP/1.1" 500 2326 "-" "curl"
COMBINED = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<req>[^"]*)" (?P<status>\d{3}) (?P<size>\S+)'
)
# 2026-10-10 13:55:36,123 ERROR something / 2026-10-10T13:55:36Z [warn] ...
GENERIC = re.compile(
    r"^\[?(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?\s*(?P<rest>.*)$"
)
LEVEL = re.compile(r"\b(ERROR|ERR|FATAL|CRITICAL|CRIT|WARN|WARNING|INFO|DEBUG|TRACE)\b", re.I)
ERROR_LEVELS = {"ERROR", "ERR", "FATAL", "CRITICAL", "CRIT"}


@dataclass
class LogEvent:
    ts: datetime
    is_error: bool
    fmt: str


def _parse_generic_ts(ts: str) -> datetime:
    ts = ts.replace(",", ".").replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts.replace(" ", "T", 1))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_line(line: str) -> LogEvent | None:
    line = line.strip()
    if not line:
        return None
    m = COMBINED.match(line)
    if m:
        try:
            ts = datetime.strptime(m["ts"], "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            return None
        return LogEvent(ts, int(m["status"]) >= 500, "combined")
    m = GENERIC.match(line)
    if m:
        try:
            ts = _parse_generic_ts(m["ts"])
        except ValueError:
            return None
        lvl = LEVEL.search(m["rest"])
        return LogEvent(ts, bool(lvl and lvl.group(1).upper() in ERROR_LEVELS), "generic")
    return None


@dataclass
class LogSeries:
    timestamps: list[str]
    counts: list[int]
    errors: list[int]
    error_rate: list[float]
    parsed: int
    skipped: int
    formats: dict[str, int]


def logs_to_series(lines: Iterable[str], bucket_seconds: int = 60) -> LogSeries:
    counts: Counter[datetime] = Counter()
    errors: Counter[datetime] = Counter()
    fmts: Counter[str] = Counter()
    parsed = skipped = 0
    for line in lines:
        ev = parse_line(line)
        if ev is None:
            skipped += bool(line.strip())
            continue
        parsed += 1
        fmts[ev.fmt] += 1
        epoch = int(ev.ts.timestamp())
        b = datetime.fromtimestamp(epoch - epoch % bucket_seconds, tz=UTC)
        counts[b] += 1
        errors[b] += ev.is_error
    if not counts:
        return LogSeries([], [], [], [], 0, skipped, {})
    start, end = min(counts), max(counts)
    ts, c, e, r = [], [], [], []
    t = start
    step = timedelta(seconds=bucket_seconds)
    while t <= end:  # fill empty buckets with zero so gaps (outages) are visible
        ts.append(t.isoformat())
        c.append(counts[t])
        e.append(errors[t])
        r.append(round(errors[t] / counts[t], 4) if counts[t] else 0.0)
        t += step
    return LogSeries(ts, c, e, r, parsed, skipped, dict(fmts))
