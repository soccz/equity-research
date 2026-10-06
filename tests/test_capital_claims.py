import copy
import unittest
from equitylab.capital_claims import build
from equitylab.pipeline import load_latest
from equitylab.valuation import build as valuation
from equitylab.xbrl import company_filing


class CapitalClaimsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {c["id"]: c for c in load_latest()["companies"]}
        cls.rows = {
            k: company_filing(copy.deepcopy(cls.companies[k]), "2026-09-29")[1]
            for k in ("018260", "INTC")
        }

    def test_sds_issued_debt_is_not_an_authorization_or_actual_common_shares(self):
        r = build(copy.deepcopy(self.companies["018260"]), self.rows["018260"])
        self.assertEqual(r["principal"], 1220000000000)
        self.assertEqual(r["carryingAmount"], 1092677876058)
        self.assertEqual(r["disclosedPotentialShares"], 6777777)
        self.assertEqual(r["disclosedConversionPrice"], 180000)
        self.assertEqual(r["couponRate"], 0.025)
        self.assertIsNone(r["actualConvertedSharesAtPriceDate"])
        self.assertIsNone(r["adjustedConversionPriceAtPriceDate"])
        self.assertLess(r["priceDate"], r["conversionStart"])

    def test_sds_holds_inverse_but_preserves_reported_outstanding(self):
        r = valuation(copy.deepcopy(self.companies["018260"]), "2026-09-29")
        self.assertEqual(r["security"]["shares"]["value"], 77350186)
        self.assertIsNone(r["security"]["marketCapProxy"])
        self.assertIsNone(r["priceRequirement"])
        self.assertTrue(all(case["price"] is None for case in r["cases"]))
        self.assertIn("전환사채", " ".join(r["security"]["issues"]))

    def test_conflicting_or_wrong_context_debt_does_not_pass(self):
        for change in ("value", "sourceHash", "dimensions"):
            rows = copy.deepcopy(self.rows["018260"])
            for r in rows:
                if r["tag"] == "ConvertibleBondsNet":
                    r[change] = {"value": 1, "sourceHash": "wrong", "dimensions": []}[
                        change
                    ]
            with self.assertRaisesRegex(ValueError, "convertible amounts"):
                build(copy.deepcopy(self.companies["018260"]), rows)

    def test_intel_eps_exclusion_does_not_remove_capital_rights(self):
        c = copy.deepcopy(self.companies["INTC"])
        r = build(c, self.rows["INTC"])
        self.assertEqual(r["maximumWarrantShares"], 241000000)
        self.assertEqual(r["warrantExercisePrice"], 20)
        self.assertEqual(r["escrowUnreleasedRoundedShares"], 143000000)
        self.assertIsNone(r["actualWarrantExerciseAtPriceDate"])
        s = valuation(c, "2026-09-29")["security"]
        self.assertEqual(s["status"], "unresolved")
        self.assertIsNone(s["marketCapProxy"])
        self.assertEqual(
            s["shares"]["value"], c["valuation"]["security"]["shares"]["value"]
        )

    def test_new_filing_keeps_hold_instead_of_reusing_old_terms(self):
        c = copy.deepcopy(self.companies["018260"])
        c["financials"]["current"]["cfo"]["accession"] = "new-filing"
        r = build(c, self.rows["018260"])
        self.assertEqual(r["status"], "review_required")
        self.assertNotIn("principal", r)

    def test_future_filing_cannot_be_used(self):
        c = copy.deepcopy(self.companies["018260"])
        c["priceSummary"]["lastDate"] = "2026-08-13"
        with self.assertRaisesRegex(ValueError, "later than"):
            build(c, self.rows["018260"])

    def test_other_issuers_are_not_classified_from_a_tag_keyword(self):
        # NAVER/Krafton subsidiary issues, AVGO customer assets, NOW tagged
        # senior-note fair value and Netmarble's HYBE exchange are distinct.
        for symbol in ["035420", "259960", "AVGO", "NOW", "251270"]:
            self.assertIsNone(build(copy.deepcopy(self.companies[symbol]), []))


if __name__ == "__main__":
    unittest.main()
