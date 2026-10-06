import copy
import unittest
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate

from equitylab import operating_inverse as inverse


class OperatingInverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.models = {
            c["id"]: c["operatingModel"]
            for c in s["companies"]
            if (c.get("operatingModel") or {}).get("status") == "research_workspace"
        }

    def test_recover_known_business_margin_by_matching_its_whole_cash_value(self):
        for cid in ["MSFT", "AVGO", "LRCX", "AMAT", "AAPL", "000270"]:
            with self.subTest(company=cid):
                m = copy.deepcopy(self.models[cid])
                a = copy.deepcopy(m["defaults"])
                changed = copy.deepcopy(a)
                changed["segments"][0]["marginEnd"] = 0.55
                target = calculate(m, changed)["equityValue"]
                self.assertGreater(target, 0)
                m["security"]["marketCapProxy"] = target
                r = inverse.margins(m, a)["rows"][0]
                self.assertEqual(r["status"], "solved")
                self.assertAlmostEqual(r["requiredMargin"], 0.55, places=11)
                self.assertLess(abs(r["relativeMarketResidual"]), 1e-10)
                self.assertEqual(a, m["defaults"])

    def test_unresolved_security_never_becomes_an_implied_price(self):
        m = copy.deepcopy(self.models["MSFT"])
        m["security"]["status"] = "held"
        r = inverse.margins(m, m["defaults"])
        self.assertTrue(
            all(
                x["status"] == "security_unresolved" and x["requiredMargin"] is None
                for x in r["rows"]
            )
        )

    def test_above_range_is_not_extrapolated(self):
        m = copy.deepcopy(self.models["AVGO"])
        m["security"]["marketCapProxy"] = 1e17
        r = inverse.margins(m, m["defaults"])
        self.assertTrue(
            all(
                x["status"] == "above_supported_range" and x["requiredMargin"] is None
                for x in r["rows"]
            )
        )

    def test_zeroed_product_does_not_create_an_identified_margin(self):
        m = copy.deepcopy(self.models["TSLA"])
        a = copy.deepcopy(m["defaults"])
        i = next(
            i
            for i, s in enumerate(m["segments"])
            if s["id"] == "AutomotiveRegulatoryCreditsMember"
        )
        a["segments"][i]["growthStart"] = a["segments"][i]["growthEnd"] = -1
        r = inverse.margins(m, a)["rows"][i]
        self.assertEqual(r["status"], "no_margin_identification")

    def test_signed_root_with_negative_terminal_cash_is_not_a_valuation(self):
        m = copy.deepcopy(self.models["MSFT"])
        m["security"]["marketCapProxy"] = 1
        r = inverse.margins(m, m["defaults"])["rows"][0]
        self.assertEqual(r["status"], "nonpositive_terminal")
        self.assertIsNone(r["requiredMargin"])

    def test_invalid_other_assumptions_fail_before_inversion(self):
        m = self.models["MSFT"]
        a = copy.deepcopy(m["defaults"])
        a["discount"] = a["terminal"]
        with self.assertRaises(ValueError):
            inverse.margins(m, a)

    def test_each_solution_changes_only_its_own_margin_and_recomputes_taxes(self):
        for cid, m in self.models.items():
            a = copy.deepcopy(m["defaults"])
            r = inverse.margins(m, a)
            for i, row in enumerate(r["rows"]):
                if row["status"] != "solved":
                    continue
                changed = copy.deepcopy(a)
                changed["segments"][i]["marginEnd"] = row["requiredMargin"]
                check = calculate(m, changed)
                self.assertAlmostEqual(
                    check["equityValue"] / m["security"]["marketCapProxy"], 1, places=9
                )
                self.assertGreater(check["terminal"]["cash"], 0)
                for j in range(len(a["segments"])):
                    if j != i:
                        self.assertEqual(changed["segments"][j], a["segments"][j])


if __name__ == "__main__":
    unittest.main()
