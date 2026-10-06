import copy
import unittest
from equitylab import business
from equitylab.pipeline import load_latest


class BusinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {c["id"]: c for c in load_latest()["companies"]}
        cls.us = business.build(copy.deepcopy(cls.companies["MSFT"]), "2026-09-29")
        cls.kr = business.build(copy.deepcopy(cls.companies["005380"]), "2026-09-29")

    def test_microsoft_reported_segments_reconcile_with_the_same_filing(self):
        b = self.us
        self.assertEqual(len(b["segments"]), 3)
        self.assertEqual(b["reconciliations"]["revenue"]["reportedTotal"], 331839000000)
        self.assertEqual(
            b["reconciliations"]["operatingIncome"]["reportedTotal"], 155237000000
        )
        self.assertTrue(
            all(r["unexplained"] == 0 for r in b["reconciliations"].values())
        )
        cloud = b["segments"][1]
        self.assertEqual(cloud["current"]["revenue"]["value"], 137791000000)
        self.assertEqual(cloud["current"]["revenue"]["accession"], b["accession"])

    def test_finance_lease_principal_is_deducted_once_noncash_is_not_deducted(self):
        b = self.us
        q = b["cash"]
        self.assertEqual(b["leases"]["principal"]["value"], 3101000000)
        self.assertEqual(b["leases"]["noncashFinanceAdditions"]["value"], 24608000000)
        self.assertEqual(q["afterCashPurchases"] - q["afterLeasePrincipal"], 3101000000)
        self.assertNotEqual(
            q["afterLeasePrincipal"], q["afterCashPurchases"] - 24608000000
        )
        self.assertEqual(b["balances"]["debt"]["value"], 40294000000)
        self.assertEqual(b["balanceChecks"]["debt"]["unexplained"], 0)

    def test_hyundai_external_and_internal_revenues_are_not_interchangeable(self):
        b = self.kr
        auto = b["segments"][0]
        self.assertEqual(auto["current"]["revenue"]["value"], 71371243000000)
        self.assertEqual(auto["current"]["grossRevenue"]["value"], 117211986000000)
        self.assertEqual(b["reconciliations"]["revenue"]["status"], "reconciled")
        self.assertEqual(
            b["reconciliations"]["operatingIncome"]["reportedAdjustment"], -86936000000
        )

    def test_cash_difference_has_no_invented_elimination_explanation(self):
        r = self.kr["reconciliations"]["cfo"]
        self.assertEqual(r["subtotal"], 7609602000000)
        self.assertEqual(r["reportedTotal"], 4849653000000)
        self.assertEqual(r["unexplained"], -2759949000000)
        self.assertIsNone(r["reportedAdjustment"])
        self.assertEqual(r["status"], "unresolved_difference")
        finance = self.kr["segments"][1]["current"]
        self.assertEqual(finance["cfo"]["value"], -3556146000000)
        self.assertGreater(finance["debtNoncurrent"]["value"], 0)

    def test_automotive_price_is_held_and_missing_receivables_not_zero(self):
        self.assertIsNone(self.kr["pricing"])
        self.assertIn("우선주", self.kr["pricingHold"])
        self.assertIsNone(
            self.kr["segments"][0]["current"]["financialReceivablesCurrent"]
        )

    def test_dates_dimensions_currency_and_conflicts_are_selected_strictly(self):
        r = self.us["segments"][0]["current"]["revenue"]
        select = lambda rows, **changes: business.select(
            rows,
            r["tag"],
            changes.get("start", r["start"]),
            changes.get("end", r["end"]),
            changes.get("dimensions", r["dimensions"]),
            changes.get("unit", "USD"),
        )
        self.assertEqual(select([r]), r)
        self.assertIsNone(select([r], dimensions=[]))
        self.assertIsNone(select([r], unit="KRW"))
        self.assertIsNone(select([r], start="2026-01-01"))
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            select([r, dict(r, value=123)])

    def test_future_filing_is_not_available_to_business_analysis(self):
        c = copy.deepcopy(self.companies["MSFT"])
        c["financials"]["current"]["cfo"]["filedAt"] = "2026-10-01"
        with self.assertRaisesRegex(ValueError, "future filing"):
            business.build(c, "2026-09-29")

    def test_balance_contexts_retain_reported_dates_even_if_taxonomy_uses_duration(
        self,
    ):
        f = self.kr["segments"][1]["current"]["debtCurrent"]
        self.assertEqual((f["start"], f["end"]), ("2026-01-01", "2026-06-30"))
        self.assertEqual(f["value"], 56812456000000)

    def test_wrong_entity_and_typed_contexts_are_rejected(self):
        xml = b"""<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:t="urn:test"><context id="c"><entity><identifier scheme="SEC">0000789019</identifier></entity><period><instant>2026-06-30</instant></period><scenario><d:typedMember dimension="t:extra"><t:item>x</t:item></d:typedMember></scenario></context><unit id="u"><measure>USD</measure></unit><t:Revenue contextRef="c" unitRef="u">12</t:Revenue></xbrl>"""
        c = self.companies["MSFT"]
        source = dict(file="unused", sha256="unused", url="https://example.invalid/")
        self.assertEqual(
            business.instance_rows(xml, c, source, "test", "2026-07-29"), []
        )
        with self.assertRaisesRegex(ValueError, "issuer mismatch"):
            business.instance_rows(
                xml.replace(b"0000789019", b"0000000001"),
                c,
                source,
                "test",
                "2026-07-29",
            )


if __name__ == "__main__":
    unittest.main()
