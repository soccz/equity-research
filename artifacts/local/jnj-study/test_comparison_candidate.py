import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from equitylab.pipeline import load_latest
from equitylab.celltrion_operating import build as build_celltrion

path = Path(__file__).with_name('pharma_comparison.py')
spec = importlib.util.spec_from_file_location('pharma_candidate', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PharmaComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cs = {c['id']:c for c in s['companies']}
        cls.jnj, cls.cell, cls.asof = cs['JNJ'],cs['068270'],s['asOf']
        cls.cell['operatingModel'] = build_celltrion(cls.cell, cls.asof)
        cls.model = m.build(copy.deepcopy(cls.jnj), cls.cell, cls.asof)

    def test_profit_decline_is_not_assigned_to_product_loss(self):
        p = self.model['pretax']
        self.assertEqual(p['consolidated']['change'], -7385e6)
        self.assertEqual([x['value'] for x in p['changeComponents']], [804e6,-209e6,-7980e6])
        self.assertEqual(sum(x['value'] for x in p['changeComponents']),p['consolidated']['change'])

    def test_cash_growth_reconciles_but_does_not_prove_collection_improvement(self):
        c = self.model['cash']
        self.assertEqual(c['cfo']['change'],3078e6)
        self.assertEqual(c['residuals'],dict(current=0,previous=0))
        self.assertEqual([x['value'] for x in c['changeComponents']],[-5767e6,-2893e6,-10e6,-70e6,7493e6,4325e6])
        ar = next(r for r in c['rows'] if r['tag']=='IncreaseDecreaseInAccountsReceivable')
        self.assertEqual((ar['effectCurrent'],ar['effectPrevious']),(-1947e6,-2283e6))

    def test_product_scope_keeps_rounding_and_unknown_counterparty_sales(self):
        s,r = self.model['products']
        self.assertEqual((s['worldwide']['current']['value'],s['worldwide']['previous']['value']),(1396e6,3278e6))
        self.assertEqual(s['rounding'],dict(current=1e6,previous=0))
        self.assertEqual(len(r['regions']),3)
        self.assertEqual(r['rounding'],dict(current=0,previous=0))
        for product in (s,r):
            self.assertIsNone(product['celltrion']['matchedProductSales'])
            self.assertIsNone(product['celltrion']['matchedCash'])
        self.assertIsNone(self.model['decision']['relativePreference'])

    def test_book_charge_cash_acquisition_and_legal_reserve_are_distinct(self):
        c = self.model['cash']
        charge = next(x for x in c['rows'] if x['tag']=='InProcessResearchAndDevelopmentCharge')
        self.assertEqual(charge['current']['value'],2e6)
        self.assertEqual(self.model['investments'][2]['values']['current']['value'],0)
        self.assertEqual(self.model['investments'][1]['values']['previous']['value'],14458e6)
        self.assertEqual(self.model['legalReserve']['approximatePresentValue'],3.7e9)
        self.assertIsNone(self.model['legalReserve']['maximumExposure'])

    def test_changed_source_and_future_or_reclassified_period_require_review(self):
        c = copy.deepcopy(self.jnj)
        c['narrative']['evidenceHash']='changed'
        self.assertEqual(m.build(c,self.cell,self.asof)['status'],'source_review_required')
        c = copy.deepcopy(self.jnj)
        c['financials']['priorEnd']='2025-06-30'
        with self.assertRaisesRegex(ValueError,'periods changed'):
            m.build(c,self.cell,self.asof)
        with self.assertRaisesRegex(ValueError,'future filing'):
            m.build(copy.deepcopy(self.jnj),self.cell,'2026-07-22')

    def test_wrong_cash_sign_or_duplicate_geography_cannot_silently_reconcile(self):
        source,rows=m.company_filing(copy.deepcopy(self.jnj),self.asof)
        rows=copy.deepcopy(rows)
        for r in rows:
            if r['tag']=='IncreaseDecreaseInOtherOperatingAssets' and r['start']=='2025-12-29':
                r['value'] *= -1
        with patch.object(m,'company_filing',return_value=(source,rows)):
            with self.assertRaisesRegex(ValueError,'cash bridge does not reconcile'):
                m.build(copy.deepcopy(self.jnj),self.cell,self.asof)


if __name__=='__main__':
    unittest.main()
