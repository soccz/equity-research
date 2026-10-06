import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate

spec=importlib.util.spec_from_file_location('equitylab.mobis_candidate',Path(__file__).with_name('mobis_operating.py'))
mobis=importlib.util.module_from_spec(spec);spec.loader.exec_module(mobis)

class MobisCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s=load_latest();cls.company=next(c for c in s['companies'] if c['id']=='012330');cls.model=mobis.build(copy.deepcopy(cls.company),s['asOf'])

    def test_period_cash_and_consolidation_reconcile_before_trailing(self):
        m=self.model;b=m['bridge']
        self.assertEqual([p['reportedCfo'] for p in b['periods']],[4472515e6,2332982e6,2673289e6])
        self.assertEqual(b['reportedCfo'],4132208e6)
        self.assertEqual(sum(x['value'] for x in b['parts']),b['reportedCfo'])
        self.assertTrue(all(p['residual']==p['revenueResidual']==p['incomeResidual']==0 for p in b['periods']))

    def test_internal_sales_and_reported_profit_removal_are_separate(self):
        m=self.model;b=m['consolidation'];y=m['initial']['years'][0]
        self.assertEqual(b['segmentRevenue'],77785777e6)
        self.assertEqual(b['internalRevenue'],15470716e6)
        self.assertEqual(b['reportedRevenue'],62315061e6)
        self.assertEqual(b['unallocatedOperatingIncome'],-106160e6)
        self.assertAlmostEqual(y['operatingIncome'],3488579e6,delta=.02)
        self.assertAlmostEqual(y['otherOperatingProfit'],-106160e6,delta=.01)
        self.assertLess(m['segments'][0]['margin'],0)

    def test_reserve_usage_is_not_the_cash_statement_adjustment(self):
        p=self.model['anchors']['warrantyReconciliationPeriods'][1]
        self.assertEqual(p['opening']['value'],1724312e6)
        self.assertEqual(p['added'],577337e6)
        self.assertEqual(p['used'],599000e6)
        self.assertEqual(p['cashExpenseAdjustment'],128023e6)
        self.assertEqual(p['cashUseAdjustment'],-276992e6)
        self.assertEqual(p['usageLessCashAdjustment'],322008e6)
        self.assertEqual(p['additionLessCashExpense'],449314e6)
        self.assertEqual(p['reimbursementAsset']['value'],582187e6)
        self.assertEqual(p['opening']['value']+p['added']-p['used']+p['other'],p['closing']['value'])
        self.assertIsNone(self.model['anchors']['warrantyReconciliationPeriods'][2]['reimbursementAsset'])

    def test_future_proxy_does_not_substitute_gross_settlement_or_dividend_cash(self):
        m=self.model;y=m['initial']['years'][0]
        self.assertAlmostEqual(y['warrantyAccrual'],603775e6,delta=.01)
        self.assertAlmostEqual(y['warrantyUse'],655753e6,delta=.01)
        self.assertAlmostEqual(y['cash'],2127966900000,delta=.01)
        self.assertGreater(m['anchors']['dividendCash'],0)
        self.assertGreater(m['anchors']['equityMethodNetIncome'],0)
        self.assertIsNone(m['bridge']['cashAfterInvestmentLeaseSbc'])
        self.assertIsNone(m['initial']['price'])

    def test_trade_proxy_excludes_reimbursements_pensions_and_warranty(self):
        m=self.model;a=m['anchors'];self.assertEqual(len(a['tradeFacts']),3)
        self.assertEqual(a['workingCashEffect'],-43686e6)
        self.assertEqual(m['initial']['years'][0]['workingCapital'],0)
        stressed=copy.deepcopy(m['defaults']);stressed['warrantyUseStart']+=.01;stressed['warrantyUseEnd']+=.01
        r=calculate(m,stressed)
        self.assertAlmostEqual(m['initial']['years'][0]['cash']-r['years'][0]['cash'],m['consolidation']['reportedRevenue']*.01,delta=.01)
        self.assertEqual(m['initial']['years'][0]['operatingIncome'],r['years'][0]['operatingIncome'])

    def test_individual_cash_and_warranty_sign_errors_are_detected(self):
        original=mobis.select
        for target in ['AdjustmentsForAssetsLiabilitiesOfOperatingActivities','ProvisionUsedOtherProvisions']:
            def changed(rows,tag,start,end,*args):
                r=original(rows,tag,start,end,*args)
                return dict(r,value=-r['value']) if r and tag==target and end=='2026-06-30' else r
            with patch.object(mobis,'select',side_effect=changed):
                with self.assertRaises(ValueError):mobis.build(copy.deepcopy(self.company),'2026-09-29')
        c=copy.deepcopy(self.company);c['narrative']['evidenceHash']='changed'
        self.assertEqual(mobis.build(c,'2026-09-29')['status'],'source_review_required')

if __name__=='__main__':unittest.main()
