import copy
import unittest
from unittest.mock import patch
from equitylab import hynix_operating as hy
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest
from equitylab.valuation import build as valuation


class HynixOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.company = copy.deepcopy(next(c for c in s['companies'] if c['id'] == '000660'))
        cls.company['valuation'] = valuation(cls.company, s['asOf'])
        cls.model = hy.build(copy.deepcopy(cls.company), s['asOf'])

    def test_three_original_cash_tables_reconcile_independently(self):
        m = self.model
        self.assertEqual(m['bridge']['reportedCfo'], 126_925_786_000_000)
        self.assertEqual([p['reportedCfo'] for p in m['bridge']['periods']], [53_373_126_000_000,91_742_501_000_000,18_189_841_000_000])
        self.assertEqual([p['indirectRows'] for p in m['bridge']['periods']], [33,28,28])
        self.assertEqual([p['residual'] for p in m['bridge']['periods']], [0,0,0])
        self.assertEqual(sum(p['value'] for p in m['bridge']['parts']), m['bridge']['reportedCfo'])
        self.assertEqual(len(m['segments']), 1)

    def test_annual_and_half_year_raw_pension_signs_differ(self):
        part = next(p for p in self.model['bridge']['parts'] if p['label']=='사외적립자산의납부')
        self.assertEqual([p['coefficient'] for p in part['fact']['components']], [1,-1,1])
        self.assertEqual([p['fact']['value'] for p in part['fact']['components']], [-736_528_000_000,172_839_000_000,265_487_000_000])
        self.assertEqual(part['value'], -643_880_000_000)

    def test_future_starts_from_operating_profit_and_keeps_sbc_cost(self):
        m = self.model
        r = m['initial']['years'][0]
        self.assertEqual(r['operatingIncome'], m['facts']['operatingIncome']['value'])
        self.assertEqual(m['facts']['fairValueGain']['components'][1]['fact']['value'], 63_178_974_000_000)
        self.assertEqual(m['facts']['dividendsReceived']['components'][1]['fact']['value'], 13_983_648_000_000)
        self.assertEqual(r['cash'], r['operatingIncome']+r['netInterest']-r['tax']+r['depreciation']-r['workingCapital']-r['capex']-r['leasePrincipal'])
        self.assertIsNone(m['initial']['price'])
        self.assertIsNone(m['initial']['requiredTerminalCash'])

    def test_purchase_commitment_is_not_current_cash_investment(self):
        m = self.model
        row = next(r for r in m['cashAnchors'] if r['label']=='미기표 유형자산 구매 약정')
        self.assertEqual(row['value'], 61_484_533_000_000)
        self.assertNotEqual(m['initial']['years'][0]['capex'], row['value'])
        self.assertEqual([p['depreciationNoteDifference'] for p in m['bridge']['periods']], [12_000_000,6_000_000,5_000_000])

    def test_margin_decline_and_higher_investment_have_separate_cash_effects(self):
        m = self.model
        a = copy.deepcopy(m['defaults'])
        a['segments'][0]['marginEnd'] -= .1
        a['capexEnd'] += .05
        r = calculate(m, a)
        revenue = m['segments'][0]['revenue']
        expected = revenue*.1*(1-a['tax'])+revenue*.05
        self.assertAlmostEqual(m['initial']['years'][4]['cash']-r['years'][4]['cash'], expected, delta=.1)
        self.assertEqual(r['years'][4]['leasePrincipal'], m['initial']['years'][4]['leasePrincipal'])

    def test_altered_cash_sign_fails_against_original_table(self):
        original = hy.select
        def altered(rows, tag, start, end, *args):
            r = original(rows, tag, start, end, *args)
            return dict(r, value=-r['value']) if r and tag==hy.PENSION and end=='2025-12-31' else r
        with patch.object(hy, 'select', side_effect=altered):
            with self.assertRaisesRegex(ValueError, 'source-table amount/sign'):
                hy.build(copy.deepcopy(self.company), '2026-09-29')

    def test_missing_adjustment_cannot_be_filled_with_zero(self):
        original = hy.select
        def absent(rows, tag, start, end, *args):
            return None if tag=='AdjustmentsForShareBasedPayment' and end=='2026-06-30' else original(rows, tag, start, end, *args)
        with patch.object(hy, 'select', side_effect=absent):
            with self.assertRaisesRegex(ValueError, 'source missing'):
                hy.build(copy.deepcopy(self.company), '2026-09-29')

    def test_new_corpus_cannot_inherit_review(self):
        c = copy.deepcopy(self.company)
        c['narrative']['evidenceHash'] = 'changed'
        self.assertEqual(hy.build(c, '2026-09-29')['status'], 'source_review_required')


if __name__ == '__main__':
    unittest.main()
