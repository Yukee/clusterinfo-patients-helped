import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from estimate import START, export_ids, months_between, utc
from model import estimate, validate_factors
from posthog import COLUMNS, fetch_counts

FACTORS = json.loads(Path(__file__).with_name("assumptions.json").read_text())


def row(m, score, ids, yes=0, no=0, a_yes=0, a_no=0):
    return dict(zip(COLUMNS, (m, score, ids, yes, no, 0, a_yes, a_no, 0)))


class PipelineTests(unittest.TestCase):
    def test_full_period_posterior_and_counts(self):
        # Frozen aggregate counts from the verified 16 Nov 2026 11:59:28 UTC snapshot.
        rows = [row("all", 0, 4069, 123, 236), row("all", 1, 2390, 206, 360, 0, 1),
                row("all", 2, 1907, 309, 398, 6), row("all", 3, 994, 282, 275, 28, 1),
                row("returning", 3, 1, 1, 0, 1)]
        result = estimate(rows, ["all"], FACTORS, draws=5000)
        full = result["full_period"]
        self.assertEqual(full["valid_ids"], 9360)
        self.assertEqual([s["action_posterior"] for s in result["scores"]], [(1,4),(2,4),(9,2),(33,2)])
        self.assertAlmostEqual(full["action_intent_given_help_seeking"]["mean"], .479, delta=.006)
        self.assertAlmostEqual(full["help_seeking_share"]["mean"], .385, delta=.003)
        expected = sum(r["ids"] * (1+r["intent_yes"])/(2+r["intent_yes"]+r["intent_no"])
                       * s["action_posterior"][0]/sum(s["action_posterior"])
                       for r,s in zip(rows[:4],result["scores"])) * .8 * .9
        self.assertAlmostEqual(full["patients_who_find_help"]["mean"], expected, delta=8)
        for key in ("mean", "lower_95", "upper_95"):
            self.assertAlmostEqual(full["patients_who_find_help"][key] * .25,
                                   full["patients_with_counterfactual_relief"][key])

    def test_months_zero_and_custom_factors(self):
        f = {**FACTORS, "helped_given_act_and_help_seeking": 0}
        result = estimate([row("first",0,90),row("last",3,100)], ["first","empty","last"], f, draws=100)
        cohorts = result["arrival_months"]
        self.assertIsNone(cohorts["empty"]["action_intent_given_help_seeking"])
        self.assertEqual(result["full_period"]["patients_with_counterfactual_relief"]["upper_95"], 0)
        self.assertAlmostEqual(sum(c["patients_who_find_help"]["mean"] for c in cohorts.values()),
                               result["full_period"]["patients_who_find_help"]["mean"])
        with self.assertRaises(ValueError):
            validate_factors({**f, "counterfactual_share": 1.2})
        self.assertEqual(list(months_between(START, utc("2026-11-01"))), ["2026-09","2026-10"])

    def test_truncated_query_never_publishes(self):
        with patch("posthog.query", return_value={"hasMore":True,"results":[]}):
            with self.assertRaises(ValueError):
                fetch_counts("")

    def test_failed_export_preserves_existing_file(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "ids.csv"
            path.write_text("previous\n")
            with patch("estimate.visitor_rows", return_value=[]), self.assertRaises(RuntimeError):
                export_ids(path, "", [row("2026-10", 0, 2)])
            self.assertEqual(path.read_text(), "previous\n")
