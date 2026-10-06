import copy
import unittest
from unittest.mock import patch
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate

from equitylab import meta_operating as candidate
from equitylab.valuation import build as valuation


class MetaOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.company = next(c for c in cls.snapshot["companies"] if c["id"] == "META")
        cls.company = copy.deepcopy(cls.company)
        cls.company["valuation"] = valuation(cls.company, cls.snapshot["asOf"])
        cls.model = candidate.build(copy.deepcopy(cls.company), cls.snapshot["asOf"])

    def test_three_period_cash_statements_reconcile_individually(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 130301000000)
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 130301000000)
        self.assertTrue(
            all(
                p["residual"] == p["incomeResidual"] == 0
                for p in m["bridge"]["periods"]
            )
        )
        deferred = m["bridge"]["periods"][0]["parts"][5]["fact"]
        self.assertEqual(deferred["tag"], "DeferredIncomeTaxesAndTaxCredits")
        self.assertEqual(deferred["value"], 18738000000)
        self.assertNotEqual(deferred["value"], 18755000000)

    def test_half_year_tax_benefit_is_not_a_negative_permanent_tax_assumption(self):
        m = self.model
        self.assertLess(m["anchors"]["currentReportedTaxRate"], 0)
        self.assertEqual(m["defaults"]["tax"], 0.21)
        self.assertIn("잔여2026분기", " ".join(m["rules"]))
        a = copy.deepcopy(m["defaults"])
        a["tax"] = 0.16
        r = calculate(m, a)
        for before, after in zip(m["initial"]["years"], r["years"]):
            self.assertAlmostEqual(
                after["cash"] - before["cash"],
                max(0, before["operatingIncome"] + before["netInterest"]) * 0.05,
                places=3,
            )

    def test_lease_capex_and_only_ppe_depreciation_are_separate(self):
        m = self.model
        self.assertEqual(m["facts"]["lease"]["value"], 3104000000)
        self.assertEqual(m["facts"]["depreciation"]["value"], 21550000000)
        self.assertLess(
            m["facts"]["depreciation"]["value"],
            m["facts"]["totalAmortization"]["value"],
        )
        for r in m["initial"]["years"]:
            expected = (
                r["operatingIncome"]
                + r["netInterest"]
                - r["tax"]
                + r["depreciation"]
                - r["workingCapital"]
                - r["capex"]
                - r["leasePrincipal"]
            )
            self.assertAlmostEqual(expected, r["cash"], places=3)
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], -1766640000, places=3)

    def test_advertising_profit_does_not_hide_reality_labs_losses_or_rights(self):
        m = self.model
        self.assertLess(m["segments"][1]["margin"], -8)
        self.assertLess(m["initial"]["years"][0]["segments"][1]["operatingIncome"], 0)
        a = copy.deepcopy(m["defaults"])
        a["capexStart"] = a["capexEnd"] = 0.1
        self.assertGreater(calculate(m, a)["equityValue"], 0)
        self.assertGreater(calculate(m, a)["price"], 0)
        self.assertGreater(calculate(m, a)["requiredTerminalCash"], 0)
        self.assertEqual(m["security"]["shares"]["value"], 2547506225)
        held = copy.deepcopy(m)
        held["security"].update(status="unresolved", marketCapProxy=None)
        self.assertIsNone(calculate(held, a)["price"])
        self.assertIsNone(calculate(held, a)["requiredTerminalCash"])

    def test_cash_statement_not_replaced_by_tax_note_amount(self):
        original = candidate.select

        def altered(rows, tag, start, end, dimensions, unit):
            r = original(rows, tag, start, end, dimensions, unit)
            if r and tag == "DeferredIncomeTaxesAndTaxCredits":
                return dict(r, value=18755000000)
            return r

        with patch.object(candidate, "select", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "period cash"):
                candidate.build(copy.deepcopy(self.company), self.snapshot["asOf"])

    def test_absent_lease_is_not_zero_and_new_filing_requires_review(self):
        original = candidate.select
        with patch.object(
            candidate,
            "select",
            side_effect=lambda rows, tag, *args: (
                None
                if tag == "FinanceLeasePrincipalPayments"
                else original(rows, tag, *args)
            ),
        ):
            with self.assertRaisesRegex(ValueError, "missing exact source"):
                candidate.build(copy.deepcopy(self.company), self.snapshot["asOf"])
        c = copy.deepcopy(self.company)
        c["narrative"]["accession"] = "future"
        self.assertEqual(
            candidate.build(c, self.snapshot["asOf"])["status"],
            "source_review_required",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
