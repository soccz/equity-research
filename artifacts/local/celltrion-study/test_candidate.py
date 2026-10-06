import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate

spec = importlib.util.spec_from_file_location(
    "celltrion_candidate", Path(__file__).with_name("celltrion_operating.py")
)
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CelltrionCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.company = copy.deepcopy(
            next(c for c in cls.snapshot["companies"] if c["id"] == "068270")
        )
        cls.model = candidate.build(copy.deepcopy(cls.company), cls.snapshot["asOf"])

    def test_three_cash_periods_preserve_the_change_of_working_capital_sign(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 995898364100)
        self.assertEqual(m["bridge"]["residual"], -796)
        ps = m["bridge"]["periods"]
        self.assertEqual(
            [p["workingRaw"] for p in ps], [-494964301000, 370230905000, 57071146000]
        )
        self.assertEqual(
            [p["workingCashEffect"] for p in ps],
            [-494964301000, -370230905000, -57071146000],
        )
        self.assertEqual([p["residual"] for p in ps], [-495, 40, 341])
        for p in ps:
            self.assertLessEqual(abs(p["residual"]), p["roundingBound"])
        self.assertTrue(
            m["anchors"]["presentationSigns"][1]["preferredLabel"].endswith(
                "negatedTotalLabel"
            )
        )

    def test_segment_gross_sales_and_internal_profit_have_separate_assumptions(self):
        m = self.model
        self.assertEqual(len(m["segments"]), 3)
        self.assertEqual(m["consolidation"]["segmentRevenue"], 7506557728000)
        self.assertEqual(m["consolidation"]["internalRevenue"], 2608752931000)
        self.assertEqual(m["consolidation"]["unallocatedOperatingIncome"], 368010259000)
        self.assertEqual(m["defaults"]["otherProfitStart"], 0)
        base = m["initial"]["years"][0]
        self.assertAlmostEqual(base["operatingIncome"], 1182234663000, delta=0.001)
        a = copy.deepcopy(m["defaults"])
        a["otherProfitStart"] = a["otherProfitEnd"] = 0.01
        changed = calculate(m, a)["years"][0]
        self.assertEqual(base["revenue"], changed["revenue"])
        self.assertAlmostEqual(
            changed["operatingIncome"] - base["operatingIncome"],
            changed["revenue"] * 0.01,
            delta=0.001,
        )

    def test_financing_interest_is_not_already_in_cfo(self):
        m = self.model
        self.assertEqual(m["facts"]["interestPaid"]["value"], 98263150436)
        self.assertEqual(m["facts"]["interestReceived"]["value"], 23368041737)
        for p in m["pharmaEvidence"]["cashClassification"]:
            self.assertEqual(
                p["cfoAfterCashInterest"],
                p["cfo"] - p["interestPaid"] + p["interestReceived"],
            )
        self.assertNotEqual(
            m["facts"]["capitalizedInterest"]["value"],
            m["facts"]["interestPaid"]["value"],
        )

    def test_development_stage_gross_and_impairment_are_not_cash_purchases(self):
        d = self.model["pharmaEvidence"]["development"]
        self.assertEqual(d["closing"]["value"], 1625432650000)
        self.assertEqual(d["added"]["value"], 158269666000)
        self.assertEqual(d["amortized"]["value"], 59614244000)
        self.assertEqual(
            d["grossBeforeImpairment"] - d["accumulatedImpairment"],
            d["closing"]["value"],
        )
        self.assertEqual(d["residual"], 0)
        self.assertNotEqual(
            d["added"]["value"],
            self.model["facts"]["intangible"]["components"][1]["fact"]["value"],
        )

    def test_supplier_financing_net_flow_is_not_gross_repayment_or_other_transfer(self):
        s = self.model["pharmaEvidence"]["supplierFinancing"]
        self.assertEqual(s["opening"]["value"], 42072483000)
        self.assertEqual(s["closing"]["value"], 12061927000)
        self.assertEqual(s["netFinancingCash"]["value"], -30946160000)
        self.assertEqual(s["fx"]["value"], 935604000)
        self.assertEqual(s["residual"], 0)
        self.assertEqual(s["disclosedOtherPayableTransfer"], 14176000000)
        self.assertEqual((s["ordinaryDays"], s["financedDays"]), (60, 180))
        self.assertEqual(
            self.model["anchors"]["excludedPayableCash"]["value"], -173930534000
        )

    def test_corrupted_segment_fact_cannot_hide_behind_a_cached_total(self):
        c = copy.deepcopy(self.company)
        c["segmentHistory"]["segments"][0]["revenue"]["components"][0]["fact"][
            "value"
        ] += 1000000
        with self.assertRaises(ValueError):
            candidate.build(c, self.snapshot["asOf"])

    def test_source_revision_requires_new_review(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            candidate.build(c, self.snapshot["asOf"])["status"],
            "source_review_required",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
