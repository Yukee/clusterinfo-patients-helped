"""Render the aggregate report for the repository's reports branch."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path


def interval(value):
    return f"{value['mean']:,.1f} ({value['lower_95']:,.1f}–{value['upper_95']:,.1f})"


def percent(value):
    return "—" if value is None else f"{value['mean']:.1%}"


def cohort_row(label, cohort):
    return (f"| {label} | {cohort['valid_ids']:,} | {percent(cohort['help_seeking_share'])} "
            f"| {percent(cohort['action_intent_given_help_seeking'])} "
            f"| {interval(cohort['patients_who_find_help'])} "
            f"| {interval(cohort['patients_with_counterfactual_relief'])} |")


def publish(report, output):
    start = datetime.fromisoformat(report["observation_start_utc"])
    end = datetime.fromisoformat(report["exclusive_cutoff_utc"])
    through = (end - timedelta(microseconds=1)).date().isoformat()
    columns = ("valid_ids", "help_seeking_share", "action_intent_given_help_seeking",
               "patients_who_find_help", "patients_with_counterfactual_relief")
    summary = {key: report[key] for key in ("schema_version", "observation_start_utc",
                                             "exclusive_cutoff_utc", "retrieved_utc", "assumptions")}
    summary["full_period"] = {key: report["full_period"][key] for key in columns}
    summary["arrival_months"] = {month: {key: cohort[key] for key in columns}
                                 for month, cohort in report["arrival_months"].items()}
    lines = [
        "# ClusterInfo patient estimates", "",
        f"First arrivals from **{start.date().isoformat()}** through **{through}** (UTC).",
        "", "Patient counts are posterior means with 95% credible intervals in parentheses.", "",
        "| Arrival cohort | First-time IDs | Seeking help | Action intent among help-seekers | Find help | Counterfactual relief |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        cohort_row("**Full period**", summary["full_period"]),
    ]
    lines.extend(cohort_row(month, value) for month, value in sorted(summary["arrival_months"].items()))
    lines.extend(["", "“Find help” estimates how many patients act on something they learned. "
                  "“Counterfactual relief” estimates how many benefit earlier because of ClusterInfo.",
                  "", "[Download the estimates as JSON](latest.json) · "
                  "[Model and assumptions](https://github.com/Yukee/clusterinfo-patients-helped/tree/main)"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "latest.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    publish(json.loads(args.report.read_text()), args.output)
