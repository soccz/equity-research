import copy
import unittest

from equitylab.pipeline import load_latest
from equitylab.naver_operating import build
from equitylab.operating_model import calculate
from equitylab.operating_inverse import margins
from equitylab.operating_judgment import build as judgment


class NaverInvestmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = load_latest()
        cls.company = copy.deepcopy(
            next(c for c in snapshot["companies"] if c["id"] == "035420")
        )
        cls.model = build(cls.company, snapshot["asOf"])

    def test_original_book_movement_includes_the_small_other_change(self):
        e = self.model["equityInvestments"]
        self.assertEqual(e["total"]["value"], 17375469887643)
        self.assertEqual(e["holdings"][0]["value"], 14929275576000)
        self.assertEqual(sum(x["value"] for x in e["holdings"]), e["total"]["value"])
        self.assertEqual(e["movements"][-2], dict(label="기타증감", value=14487000))
        self.assertEqual(e["movementResidual"], 0)
        self.assertEqual(e["tableToXbrlRounding"], dict(opening=432, closing=357))
        self.assertEqual(e["consolidatedOwnership"], 0.5)
        self.assertEqual(e["directOwnership"], 0.4225)
        self.assertIsNone(e["approvedEquityValue"])

    def test_missing_investment_value_never_means_zero_or_growth_failure(self):
        m = self.model
        r = calculate(m, m["defaults"])
        self.assertIsNone(r["requiredTerminalCash"])
        self.assertIsNone(r["investmentBridge"]["selectedSubtotal"])
        self.assertGreater(
            r["price"], 0
        )  # Separately labeled cash component remains visible.
        self.assertEqual(
            margins(m, m["defaults"])["rows"][0]["status"], "investment_unassessed"
        )
        c = dict(self.company, operatingModel=m)
        self.assertEqual(judgment(c)["state"], "투자자산 가치 보완")

    def test_asset_is_added_once_without_changing_operating_cash_or_tax(self):
        m = self.model
        zero = dict(m["defaults"], equityInvestmentValue=0)
        chosen = dict(zero, equityInvestmentValue=12e12)
        r0, r = calculate(m, zero), calculate(m, chosen)
        self.assertEqual(r0["years"], r["years"])
        self.assertEqual(r0["terminal"], r["terminal"])
        self.assertEqual(r0["equityValue"], r["equityValue"])
        self.assertEqual(
            r["investmentBridge"]["selectedSubtotal"] - r["equityValue"], 12e12
        )
        self.assertAlmostEqual(
            r0["requiredTerminalCash"] - r["requiredTerminalCash"],
            12e12
            * (1 + chosen["discount"]) ** 5
            * (chosen["discount"] - chosen["terminal"]),
            delta=0.01,
        )
        # Changes in book observations do not silently become valuation inputs.
        changed = copy.deepcopy(m)
        changed["equityInvestments"]["total"]["value"] *= 3
        self.assertEqual(r, calculate(changed, chosen))

    def test_margin_root_uses_the_market_remainder_and_not_twice_the_asset(self):
        m = copy.deepcopy(self.model)
        a = dict(m["defaults"], equityInvestmentValue=12e12)
        target = copy.deepcopy(a)
        target["segments"][0]["marginEnd"] = 0.35
        m["security"]["marketCapProxy"] = calculate(m, target)["investmentBridge"][
            "selectedSubtotal"
        ]
        row = margins(m, a)["rows"][0]
        self.assertEqual(row["status"], "solved")
        self.assertAlmostEqual(row["requiredMargin"], 0.35, places=11)
        self.assertEqual(a["segments"], m["defaults"]["segments"])

    def test_security_and_nonpositive_market_remainder_keep_their_holds(self):
        m = copy.deepcopy(self.model)
        a = dict(m["defaults"], equityInvestmentValue=m["security"]["marketCapProxy"])
        self.assertEqual(
            margins(m, a)["rows"][0]["status"], "nonpositive_market_remainder"
        )
        self.assertIsNone(calculate(m, a)["requiredTerminalCash"])
        m["security"]["status"] = "held"
        self.assertEqual(margins(m, a)["rows"][0]["status"], "security_unresolved")
        self.assertIsNone(calculate(m, a)["investmentBridge"]["selectedSubtotalPrice"])

    def test_invalid_values_and_missing_field_are_rejected(self):
        m = self.model
        for invalid in [-1, True, "0", float("nan"), float("inf")]:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                calculate(m, dict(m["defaults"], equityInvestmentValue=invalid))
        a = copy.deepcopy(m["defaults"])
        del a["equityInvestmentValue"]
        with self.assertRaises(ValueError):
            calculate(m, a)


if __name__ == "__main__":
    unittest.main()
