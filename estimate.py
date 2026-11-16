#!/usr/bin/env python3
"""Refresh or replay the ClusterInfo patients-helped report."""
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from model import estimate, validate_factors
from posthog import ID_COLUMNS, cohort_sql, fetch_counts, visitor_rows

ROOT = Path(__file__).resolve().parent
START = datetime(2026, 9, 30, 23, 56, 5, tzinfo=timezone.utc)


def utc(text):
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.microsecond:
        raise ValueError("Use whole seconds for the observation cutoff.")
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def months_between(start, end):
    last = (end - timedelta(microseconds=1)).date().replace(day=1)
    month = start.date().replace(day=1)
    while month <= last:
        yield month.strftime("%Y-%m")
        month = (month + timedelta(days=32)).replace(day=1)


@contextmanager
def atomic_text(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", newline="",
                           delete=False) as stream:
        temp = Path(stream.name)
        try:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def export_ids(path, prefix, counts):
    expected = Counter({(r["arrival_month"], r["score"]): r["ids"] for r in counts
                        if r["arrival_month"] != "returning"})
    observed = Counter()
    with atomic_text(path) as stream:
        writer = csv.DictWriter(stream, fieldnames=ID_COLUMNS)
        writer.writeheader()
        for row in visitor_rows(prefix):
            writer.writerow(row)
            observed[row["arrival_month"], row["score"]] += 1
        if expected != observed:
            raise RuntimeError("ID export disagrees with the aggregate query. Retry the refresh.")


def refresh(args):
    factors = json.loads(args.assumptions.read_text())
    validate_factors(factors)
    now = datetime.now(timezone.utc)
    # Exclude today's partial traffic in scheduled reports.
    end = utc(args.as_of) if args.as_of else now.replace(hour=0, minute=0, second=0, microsecond=0)
    if end <= START or end > now:
        raise ValueError("The cutoff must be after the first actionable poll and no later than now.")
    prefix = cohort_sql(START, end)
    if args.ids_csv and args.ids_csv.resolve() == args.output.resolve():
        raise ValueError("Choose distinct report and CSV paths.")
    counts = fetch_counts(prefix)
    result = estimate(counts, list(months_between(START, end)), factors, args.draws, args.seed)
    if args.ids_csv:
        export_ids(args.ids_csv, prefix, counts)
    report = {"schema_version": 1, "project": 155394, "observation_start_utc": START.isoformat(),
              "exclusive_cutoff_utc": end.isoformat(), "retrieved_utc": now.isoformat(),
              "assumptions": factors, "posterior_draws": args.draws, "seed": args.seed,
              "cohort_sql_sha256": hashlib.sha256(prefix.encode()).hexdigest(),
              "aggregate_inputs": counts, **result}
    with atomic_text(args.output) as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"Arrival cohorts through {end.isoformat()} (exclusive), UTC")
    print(f"{'Cohort':<12}{'Valid IDs':>10} {'Seek help':>10} {'Intent | seek':>14}  "
          "Find help [95% CrI]           Counterfactual relief [95% CrI]")
    for name, data in [*result["arrival_months"].items(), ("All arrivals", result["full_period"])]:
        def pct(key):
            return f"{data[key]['mean']:.1%}" if data[key] is not None else "—"

        def count(key):
            v = data[key]
            return f"{v['mean']:.1f} [{v['lower_95']:.1f}, {v['upper_95']:.1f}]"
        print(f"{name:<12}{data['valid_ids']:>10} {pct('help_seeking_share'):>10} "
              f"{pct('action_intent_given_help_seeking'):>14}  "
              f"{count('patients_who_find_help'):<30}{count('patients_with_counterfactual_relief')}")
    print(f"Saved {args.output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", help="exclusive ISO-8601 UTC cutoff (default: today's 00:00 UTC)")
    parser.add_argument("--assumptions", type=Path, default=ROOT / "assumptions.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/latest.json")
    parser.add_argument("--ids-csv", type=Path, help="also export one row per valid first-time ID")
    parser.add_argument("--draws", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=20261116)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.with_name(args.output.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        refresh(args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        sys.exit(f"Refresh failed: {error}")
