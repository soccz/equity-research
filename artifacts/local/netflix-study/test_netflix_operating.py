import unittest, copy, json, importlib.util
from pathlib import Path
from equitylab.operating_model import calculate

B = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "netflix_candidate", B / "netflix_operating.py"
)
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class NetflixOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = json.loads((B / "company-start.json").read_text())
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
        self.assertAlmostEqual(m["initial"]["years"][0]["capex"], 21029464000)
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


if __name__ == "__main__":
    unittest.main()
