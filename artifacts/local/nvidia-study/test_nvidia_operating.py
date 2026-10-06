import copy
import unittest
from unittest.mock import patch
from equitylab import nvidia_operating as nv
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate


class NvidiaOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.company = copy.deepcopy(next(c for c in s['companies'] if c['id']=='NVDA'))
        cls.model = nv.build(copy.deepcopy(cls.company), s['asOf'])

    def test_all_original_periods_reconcile_before_trailing_combination(self):
        m = self.model
        self.assertEqual(m['bridge']['reportedCfo'],134_360_000_000)
        self.assertEqual([p['reportedCfo'] for p in m['bridge']['periods']],[102_718_000_000,74_421_000_000,42_779_000_000])
        self.assertTrue(all(p['residual']==p['incomeResidual']==p['revenueResidual']==0 for p in m['bridge']['periods']))
        self.assertEqual(sum(p['value'] for p in m['bridge']['parts']),m['bridge']['reportedCfo'])
        self.assertEqual([s['revenue'] for s in m['segments']],[275_409_000_000,27_561_000_000])

    def test_primary_tax_amount_is_not_replaced_by_rounded_narrative(self):
        self.assertEqual(self.model['facts']['tax']['components'][2]['fact']['value'],7_920_000_000)
        self.assertTrue(all(p['fact']['decimals']=='-6' for p in self.model['facts']['tax']['components']))

    def test_corporate_costs_keep_sbc_expensed_once_in_future(self):
        m = self.model
        self.assertEqual(m['anchors']['reportedCorporateCost'],10_290_000_000)
        r = m['initial']['years'][0]
        self.assertAlmostEqual(r['operatingIncome'],197_579_000_000,delta=.001)
        self.assertAlmostEqual(r['segmentOperatingIncome']-r['corporateCost'],r['operatingIncome'],delta=.001)
        self.assertEqual(r['cash'],r['operatingIncome']+r['netInterest']-r['tax']+r['depreciation']-r['workingCapital']-r['capex']-r['leasePrincipal'])

    def test_long_liability_cash_is_not_called_customer_advances(self):
        self.assertEqual(self.model['anchors']['workingCashEffect'],-29_134_000_000)
        self.assertEqual(self.model['anchors']['revenueIncrease'],87_032_000_000)
        self.assertIn('전액을 고객 선급금',self.model['anchorSummary'])

    def test_financed_asset_payment_is_not_a_verified_total_lease_payment(self):
        m = self.model
        self.assertEqual(m['facts']['financedAssets']['value'],120_000_000)
        self.assertAlmostEqual(m['initial']['years'][0]['leasePrincipal'],120_000_000,delta=.001)
        self.assertIsNone(m['anchors']['actualFinanceLeasePrincipal'])
        self.assertEqual(m['leaseLabel'],'설비·무형 분할취득 원금')

    def test_contract_totals_do_not_become_one_year_cash_spending(self):
        m = self.model
        self.assertEqual([x['value'] for x in m['cashAnchors'][:3]],[279e9,29e9,36e9])
        self.assertEqual(m['initial']['years'][0]['capex'],7_354_000_000)
        self.assertTrue(any('제3자' in p['text'] or 'third-party' in p['text'] for p in m['passages']))

    def test_corporate_stress_and_tax_recalculate_every_year(self):
        m = self.model
        a = copy.deepcopy(m['defaults']);a['corporateStart']+=.01;a['corporateEnd']+=.01
        r = calculate(m,a)
        for old,new in zip([*m['initial']['years'],m['initial']['terminal']],[*r['years'],r['terminal']]):
            self.assertAlmostEqual(old['cash']-new['cash'],old['revenue']*.01*(1-a['tax']),delta=.001)

    def test_mutated_cash_component_and_new_corpus_do_not_inherit_review(self):
        original=nv.select
        def changed(rows,tag,start,end,*args):
            r=original(rows,tag,start,end,*args)
            return dict(r,value=r['value']+1e6) if r and tag=='OtherNoncashIncomeExpense' and end=='2026-01-25' else r
        with patch.object(nv,'select',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'period cash'):
                nv.build(copy.deepcopy(self.company),'2026-09-29')
        c=copy.deepcopy(self.company);c['narrative']['evidenceHash']='changed'
        self.assertEqual(nv.build(c,'2026-09-29')['status'],'source_review_required')


if __name__=='__main__':unittest.main()
