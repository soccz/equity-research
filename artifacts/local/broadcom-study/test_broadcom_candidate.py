import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from equitylab.pipeline import load_latest

STAGE=Path(__file__).resolve().parent

def module(file,name):
    spec=importlib.util.spec_from_file_location("equitylab."+name,STAGE/file)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

calc=module("operating_model_candidate.py","broadcom_calc_candidate")
broadcom=module("broadcom_operating.py","broadcom_candidate")

class BroadcomCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot=load_latest()
        cls.company=copy.deepcopy(next(c for c in snapshot["companies"] if c["id"]=="AVGO"))
        with patch("equitylab.operating_model.calculate",calc.calculate):
            cls.model=broadcom.build(copy.deepcopy(cls.company),snapshot["asOf"])

    def test_each_cash_period_reconciles_before_trailing_addition(self):
        b=self.model["bridge"]
        self.assertEqual([p["reportedCfo"] for p in b["periods"]],[27537000000,32950000000,19834000000])
        self.assertEqual(b["reportedCfo"],40653000000)
        self.assertEqual(sum(x["value"] for x in b["parts"]),b["reportedCfo"])
        self.assertTrue(all(x["residual"]==0 for x in b["periods"]))

    def test_four_corporate_costs_reconcile_both_segments(self):
        m=self.model;y=m["initial"]["years"][0]
        self.assertEqual(len(m["anchors"]["corporateAdjustments"]),4)
        self.assertEqual(m["anchors"]["reportedCorporateCost"],16956000000)
        self.assertEqual(y["segmentOperatingIncome"],59770000000)
        self.assertEqual(y["operatingIncome"],42814000000)
        self.assertEqual(y["corporateCost"],16956000000)

    def test_acquisition_amortization_is_not_the_whole_cash_amortization(self):
        m=self.model;f=m["facts"]
        self.assertEqual(f["acquisitionAmortization"]["value"],7994000000)
        self.assertEqual(f["depreciation"]["value"],632000000)
        self.assertEqual(m["initial"]["years"][0]["depreciation"],8626000000)
        self.assertGreater(m["anchors"]["unmodeledAmortization"],0)
        self.assertIsNone(m["anchors"]["actualFinanceLeasePrincipal"])
        self.assertEqual(m["defaults"]["leaseStart"],0)

    def test_long_term_cash_and_factoring_totals_are_not_growth_working_capital(self):
        m=self.model
        self.assertEqual(m["anchors"]["workingCashEffect"],-9996000000)
        self.assertEqual(m["anchors"]["revenueIncrease"],25217000000)
        self.assertEqual(m["facts"]["capex"]["value"],1250000000)
        self.assertEqual(m["bridge"]["cashAfterInvestmentLeaseSbc"],30921000000)

    def test_customer_notes_are_not_issuer_dilution_and_maximum_is_not_paid_cash(self):
        a=self.model["anchors"]
        self.assertEqual(a["backstopMaximum"],29e9)
        self.assertEqual(a["backstopPaid"],0)
        self.assertEqual(a["customerNotesMaximum"],42e9)
        self.assertEqual(a["customerNotesIssued"],0)
        self.assertEqual(self.model["security"],self.company["valuation"]["security"])

    def test_support_stress_is_discounted_once_without_a_terminal_recurrence(self):
        m=self.model;r=m["initial"]
        plain=copy.deepcopy(m);del plain["contractSupport"]
        original=calc.calculate(plain,m["defaults"])
        self.assertEqual(r["terminal"],original["terminal"])
        self.assertEqual(r["years"],original["years"])
        self.assertEqual(len(r["contingentLossCases"]),9)
        for c in r["contingentLossCases"]:
            self.assertAlmostEqual(c["presentValue"],29e9*c["fraction"]/(1.12**c["year"]))
            self.assertAlmostEqual(c["equityValue"],r["equityValue"]-c["presentValue"])
            self.assertAlmostEqual(c["price"],c["equityValue"]/m["security"]["shares"]["value"])
        self.assertGreater(r["contingentLossCases"][0]["presentValue"],r["contingentLossCases"][2]["presentValue"])

    def test_support_never_resolves_a_held_security_or_nonpositive_value(self):
        m=copy.deepcopy(self.model);m["security"]["status"]="held";m["security"]["marketCapProxy"]=None
        r=calc.calculate(m,m["defaults"])
        self.assertTrue(all(c["price"] is None for c in r["contingentLossCases"]))
        a=copy.deepcopy(m["defaults"]);a["capexStart"]=a["capexEnd"]=1
        r=calc.calculate(m,a)
        self.assertIsNone(r["equityValue"])
        self.assertTrue(all(c["equityValue"] is None for c in r["contingentLossCases"]))

    def test_changed_cash_sign_or_source_contract_does_not_pass(self):
        original=broadcom.select
        def changed(rows,tag,start,end,*args):
            r=original(rows,tag,start,end,*args)
            return dict(r,value=-r["value"]) if r and tag=="OtherNoncashIncomeExpense" and end=="2025-11-02" else r
        with patch.object(broadcom,"select",side_effect=changed):
            with self.assertRaisesRegex(ValueError,"period cash"):
                broadcom.build(copy.deepcopy(self.company),"2026-09-29")
        c=copy.deepcopy(self.company);c["narrative"]["evidenceHash"]="changed"
        self.assertEqual(broadcom.build(c,"2026-09-29")["status"],"source_review_required")

if __name__=="__main__":unittest.main()
