"""Independent Beta posteriors for the two polls; expected patient counts."""
from array import array
from collections import defaultdict
from math import floor, isfinite
from random import Random
from statistics import fmean

ACTION_PRIORS = ((1, 4), (2, 3), (3, 2), (4, 1))
FACTORS = {"multiple_id_correction", "act_given_intent_and_help_seeking",
           "helped_given_act_and_help_seeking", "counterfactual_share"}


def validate_factors(factors):
    if not isinstance(factors, dict) or set(factors) != FACTORS:
        raise ValueError("The assumptions file must contain exactly: " + ", ".join(sorted(FACTORS)))
    for key, value in factors.items():
        if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key} must be a probability between 0 and 1.")


def summary(values):
    values = sorted(values)

    def quantile(p):
        position = p * (len(values) - 1)
        lo = floor(position)
        return values[lo] + (position - lo) * (values[min(lo + 1, len(values) - 1)] - values[lo])

    return {"mean": fmean(values), "lower_95": quantile(.025), "upper_95": quantile(.975)}


def scale(interval, factor):
    return {key: value * factor for key, value in interval.items()}


def estimate(rows, months, factors, draws=100000, seed=20261116):
    validate_factors(factors)
    if draws < 2:
        raise ValueError("At least two posterior draws are required.")
    by_month = {m: [0] * 4 for m in months}
    scores = [defaultdict(int) for _ in range(4)]
    for row in rows:
        e = row["score"]
        new = row["arrival_month"] != "returning"
        if new:
            by_month[row["arrival_month"]][e] += row["ids"]
            for key in ("ids", "intent_yes", "intent_no", "intent_conflict"):
                scores[e][key] += row[key]
        for key in ("actionable_yes", "actionable_no", "actionable_conflict"):
            scores[e][key] += row[key]

    rng = Random(seed)
    help_draws, joint_draws, evidence = [], [], []
    for e, counts in enumerate(scores):
        h = (1 + counts["intent_yes"], 1 + counts["intent_no"])
        a0, b0 = ACTION_PRIORS[e]
        a = (a0 + counts["actionable_yes"], b0 + counts["actionable_no"])
        h_samples = array("d", (rng.betavariate(*h) for _ in range(draws)))
        a_samples = array("d", (rng.betavariate(*a) for _ in range(draws)))
        help_draws.append(h_samples)
        joint_draws.append(array("d", (s * p for s, p in zip(h_samples, a_samples))))
        evidence.append({"score": e, **counts, "help_posterior": h, "action_prior": [a0, b0],
                         "action_posterior": a, "help_probability": summary(h_samples),
                         "action_probability_given_help": summary(a_samples)})

    def cohort(counts):
        total = sum(counts)
        help_count = array("d", (sum(n * s for n, s in zip(counts, sample))
                                 for sample in zip(*help_draws)))
        joint_count = array("d", (sum(n * q for n, q in zip(counts, sample))
                                  for sample in zip(*joint_draws)))
        acted = scale(summary(joint_count),
                      factors["multiple_id_correction"] * factors["act_given_intent_and_help_seeking"])
        relief = scale(acted, factors["helped_given_act_and_help_seeking"] * factors["counterfactual_share"])
        return {"valid_ids": total, "ids_by_score": counts,
                "help_seeking_share": scale(summary(help_count), 1 / total) if total else None,
                "action_intent_given_help_seeking": summary(j / h for j, h in zip(joint_count, help_count)) if total else None,
                "patients_who_find_help": acted, "patients_with_counterfactual_relief": relief}

    totals = [sum(group[e] for group in by_month.values()) for e in range(4)]
    return {"scores": evidence, "full_period": cohort(totals),
            "arrival_months": {m: cohort(counts) for m, counts in by_month.items()}}
