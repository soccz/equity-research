import copy
import unittest
from unittest.mock import patch
from equitylab import amd_operating as amd, amd_capital, cash_scope, valuation
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate
from equitylab.operating_judgment import build as judgment


class AmdOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.company = copy.deepcopy(next(c for c in s["companies"] if c["id"] == "AMD"))
        c = cls.company
        c["cashScope"] = cash_scope.build(c, s["asOf"])
        c["valuation"] = valuation.build(c, s["asOf"])
        cls.model = amd.build(c, s["asOf"])

    def test_continuing_cfo_reconciles_each_period_without_disposed_business(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 9_413_000_000)
        self.assertEqual(m["anchors"]["totalCfo"], 10_080_000_000)
        self.assertEqual(m["anchors"]["discontinuedCfo"], 667_000_000)
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [6_493_000_000, 5_321_000_000, 2_401_000_000],
        )
        self.assertTrue(
            all(
                p["reportedCfo"] + p["discontinuedCfo"] == p["totalCfo"]
                for p in m["bridge"]["periods"]
            )
        )
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 9_413_000_000)
        self.assertTrue(
            all(
                p["residual"] == p["incomeResidual"] == p["revenueResidual"] == 0
                for p in m["bridge"]["periods"]
            )
        )

    def test_source_specific_amortization_tax_and_recovery_signs(self):
        f = self.model["facts"]
        self.assertEqual(
            f["acquisitionAmortization"]["components"][0]["fact"]["tag"],
            "AdjustmentForAmortization",
        )
        self.assertEqual(f["acquisitionAmortization"]["value"], 2_214_000_000)
        self.assertEqual(
            f["deferredTax"]["components"][0]["fact"]["value"], 248_000_000
        )
        self.assertEqual(
            self.model["anchors"]["inventoryRecovery"]["value"], -67_000_000
        )
        self.assertEqual(
            f["otherNoncash"]["components"][1]["fact"]["value"], -61_000_000
        )

    def test_continuing_capex_does_not_include_disposal_settlement(self):
        m = self.model
        self.assertEqual(m["facts"]["capex"]["value"], 1_677_000_000)
        self.assertEqual(
            [p["capex"] for p in m["bridge"]["periods"]],
            [974_000_000, 1_197_000_000, 494_000_000],
        )
        self.assertAlmostEqual(
            m["initial"]["years"][0]["capex"], 1_677_000_000, delta=0.001
        )
        self.assertEqual(m["bridge"]["cashAfterInvestmentLeaseSbc"], 5_841_000_000)

    def test_corporate_adjustment_retains_sbc_and_future_lease_is_only_assumed(self):
        m = self.model
        self.assertEqual(m["anchors"]["reportedCorporateCost"], 4_153_000_000)
        self.assertAlmostEqual(
            m["initial"]["years"][0]["operatingIncome"], 6_488_000_000, delta=0.001
        )
        self.assertIsNone(m["anchors"]["actualFinanceLeasePrincipal"])
        a = copy.deepcopy(m["defaults"])
        a["leaseStart"] = a["leaseEnd"] = 0.01
        stressed = calculate(m, a)
        for x, y in zip(m["initial"]["years"], stressed["years"]):
            self.assertAlmostEqual(
                x["cash"] - y["cash"], x["revenue"] * 0.01, delta=0.001
            )

    def test_conditional_warrants_do_not_become_current_outstanding_shares(self):
        r = self.model["security"]["warrantReview"]
        self.assertEqual(
            [t["maximumShares"] for t in r["terms"]], [160_000_000, 160_000_000]
        )
        self.assertEqual(r["maximumCombinedShares"], 320_000_000)
        self.assertEqual(r["vestedSharesAtObservation"], 0)
        self.assertIsNone(r["vestedSharesAtPriceDate"])
        self.assertEqual(self.model["security"]["shares"]["value"], 1_632_475_042)
        self.assertEqual(self.model["security"]["status"], "unresolved")
        self.assertIsNone(self.model["initial"]["price"])
        c = copy.deepcopy(self.company)
        c["operatingModel"] = self.model
        self.assertIsNone(judgment(c)["requiredTerminalCash"])

    def test_future_contracts_and_maximum_guarantee_are_not_current_cash(self):
        anchors = {x["label"]: x for x in self.model["cashAnchors"]}
        self.assertEqual(anchors["상업 파트너 리스 최대 보증"]["value"], 4.1e9)
        self.assertEqual(anchors["후속 데이터센터 리스 약정"]["value"], 9.5e9)
        self.assertIn("이후", anchors["후속 데이터센터 리스 약정"]["period"])
        self.assertAlmostEqual(
            self.model["initial"]["years"][0]["cash"], 6_359_390_000, delta=0.001
        )

    def test_corrupted_annual_cash_and_new_corpus_invalidate_the_model(self):
        original = amd.select

        def changed(rows, tag, start, end, *args):
            r = original(rows, tag, start, end, *args)
            return (
                dict(r, value=r["value"] + 1e6)
                if r and tag == "InventoryLossAtRecoveryFromContractManufacturer"
                else r
            )

        with patch.object(amd, "select", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "period cash"):
                amd.build(copy.deepcopy(self.company), "2026-09-29")
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(amd.build(c, "2026-09-29")["status"], "source_review_required")

    def test_warrant_review_rejects_later_source_and_does_not_approve_new_filing(self):
        c = copy.deepcopy(self.company)
        c["priceSummary"]["lastDate"] = "2026-08-04"
        with self.assertRaisesRegex(ValueError, "later"):
            amd_capital.build(c)
        c = copy.deepcopy(self.company)
        c["financials"]["current"]["cfo"]["accession"] = "new"
        self.assertEqual(amd_capital.build(c)["status"], "review_required")


if __name__ == "__main__":
    unittest.main()
