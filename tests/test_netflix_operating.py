import unittest, copy
from equitylab.operating_model import calculate

from equitylab import netflix_operating as candidate
from equitylab.pipeline import load_latest


class NetflixOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = next(c for c in load_latest()["companies"] if c["id"] == "NFLX")
        cls.model = candidate.build(copy.deepcopy(cls.company), "2026-09-29")

    def test_cash_bridge_uses_exact_thousand_dollar_rows_and_signs(self):
        m = self.model
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [10149273000, 7034017000, 5212457000],
        )
        self.assertEqual(m["facts"]["sbc"]["value"], 487327000)
        self.assertEqual(m["bridge"]["reportedCfo"], 11970833000)
        for part in m["bridge"]["parts"]:
            self.assertEqual(
                part["value"],
                sum(
                    x["coefficient"] * x["fact"]["value"]
                    for x in part["fact"]["components"]
                ),
            )

    def test_content_payment_uses_cash_adjustment_not_balance_change(self):
        m = self.model
        e = m["contentEvidence"]
        self.assertEqual(
            [p["contentCash"] for p in e["periods"]],
            [17707455000, 9911018000, 8010775000],
        )
        self.assertEqual(e["contentCash"], 19607698000)
        self.assertEqual(e["contentLiabilityChange"]["value"], -122111000)
        self.assertEqual(e["contentAmortization"]["value"], 17296189000)
        self.assertAlmostEqual(
            m["defaults"]["depreciation"] * m["facts"]["revenue"]["value"], 17668603000
        )

    def test_historical_content_cash_is_not_subtracted_twice(self):
        m = self.model
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], 6769438500)
        self.assertAlmostEqual(m["initial"]["years"][0]["capex"], 1421766000)
        self.assertAlmostEqual(m["initial"]["years"][0]["contentCash"], 19607698000)
        self.assertEqual(m["facts"]["acquisitions"]["value"], 602938000)
        self.assertIsNone(m["bridge"]["cashAfterInvestmentLeaseSbc"])
        self.assertIsNone(m["anchors"]["actualFinanceLeasePayment"])

    def test_termination_fee_is_not_removed_again_from_operating_margin(self):
        m = self.model
        e = m["contentEvidence"]
        self.assertEqual(e["feeAmount"], 2800000000)
        self.assertEqual(e["currentCashBeforeFeeOnly"], 4234017000)
        self.assertEqual(e["priorCfo"], 5212457000)
        self.assertEqual(m["initial"]["years"][0]["operatingIncome"], 14354517000)
        self.assertEqual(m["initial"]["years"][0]["netInterest"], -847451000)
        self.assertEqual(e["nonRoutineBrazilPayment"], 729000000)

    def test_obligations_include_recognized_amount_and_unknown_future_titles(self):
        e = self.model["contentEvidence"]
        recognized = sum(x["value"] for x in e["recognizedContentLiabilities"])
        self.assertEqual(e["obligationTotal"], 25106705000)
        self.assertEqual(recognized, 5492122000)
        self.assertEqual(e["unrecognizedDerived"], 19614583000)
        self.assertEqual(e["obligations"][0]["value"], 11939734000)
        self.assertIn("unknown obligations", e["obligationScope"]["text"])

    def test_receivable_scope_is_checked_against_original_caption(self):
        m = self.model
        e = m["contentEvidence"]
        self.assertEqual(m["anchors"]["workingStockNet"], -608049000)
        self.assertEqual(
            e["workingStockTerms"][0]["fact"]["tag"],
            "TradeReceivablesHeldForSaleAmount",
        )
        self.assertIn("Trade receivables", e["tradeSource"]["text"])
        self.assertNotEqual(e["workingStockTerms"][0]["fact"]["value"], 4725393000)

    def test_new_source_requires_fee_and_content_review(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "new"
        self.assertEqual(
            candidate.build(c, "2026-09-29")["status"], "source_review_required"
        )

    def test_content_sensitivity_changes_cash_once_without_rewriting_source(self):
        m = self.model
        baseline = copy.deepcopy(m)
        a = copy.deepcopy(m["defaults"])
        a["contentStart"] += 0.01
        a["contentEnd"] += 0.01
        r = calculate(m, a)
        for old, new in zip(
            [*m["initial"]["years"], m["initial"]["terminal"]],
            [*r["years"], r["terminal"]],
        ):
            self.assertAlmostEqual(
                old["cash"] - new["cash"], new["revenue"] * 0.01, places=4
            )
            self.assertEqual(old["capex"], new["capex"])
            self.assertEqual(old["operatingIncome"], new["operatingIncome"])
        self.assertEqual(m, baseline)

    def test_terminal_content_payment_and_warning_include_separate_content(self):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["segments"][0].update(growthStart=0.08, growthEnd=0.04)
        a["contentStart"], a["contentEnd"] = 0.4, 0.45
        r = calculate(m, a)
        self.assertAlmostEqual(
            r["terminal"]["contentCash"],
            r["years"][-1]["revenue"] * (1 + a["terminal"]) * 0.45,
            places=4,
        )
        self.assertFalse(r["reinvestmentCaution"])
        a["contentEnd"] = 0
        self.assertTrue(calculate(m, a)["reinvestmentCaution"])

    def test_content_zero_is_explicit_and_missing_or_invalid_is_rejected(self):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["contentStart"] = a["contentEnd"] = 0
        r = calculate(m, a)
        self.assertEqual(r["years"][0]["contentCash"], 0)
        self.assertAlmostEqual(
            r["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            19607698000,
            places=4,
        )
        for key in ("contentStart", "contentEnd"):
            for invalid in (None, -0.01, 1.01, float("nan"), True):
                changed = copy.deepcopy(m["defaults"])
                changed[key] = invalid
                with self.assertRaises(ValueError):
                    calculate(m, changed)
            changed = copy.deepcopy(m["defaults"])
            del changed[key]
            with self.assertRaises(ValueError):
                calculate(m, changed)


if __name__ == "__main__":
    unittest.main()
