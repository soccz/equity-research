import copy
import unittest
from equitylab.hynix_capital import build
from equitylab.pipeline import load_latest
from equitylab.valuation import build as valuation


class HynixCapitalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = next(c for c in load_latest()['companies'] if c['id']=='000660')

    def test_completed_issue_does_not_add_both_adr_and_underlying(self):
        c = copy.deepcopy(self.company)
        r = build(c, c['valuation']['security']['shares'])
        self.assertEqual(r['issuedAfterKnownIssue'], 730_492_365)
        self.assertEqual(r['latestIssued']['value'], r['issuedAfterKnownIssue'])
        self.assertEqual(r['latestTreasury']['value'], 1_625_769)
        self.assertIsNone(r['currentOutstanding'])
        self.assertIsNone(r['repurchase']['actualShares'])
        self.assertEqual(r['repurchase']['end'], '2026-11-19')

    def test_known_later_changes_hold_price_but_preserve_opening_count(self):
        c = copy.deepcopy(self.company)
        s = valuation(c, '2026-09-29')['security']
        self.assertEqual(s['status'], 'unresolved')
        self.assertIsNone(s['marketCapProxy'])
        self.assertEqual(s['shares']['value'], 711_075_500)
        self.assertIn('반기 이후', ' '.join(s['issues']))

    def test_later_filing_is_not_used_before_its_disclosure(self):
        c = copy.deepcopy(self.company)
        c['priceSummary']['lastDate'] = '2026-08-18'
        r = build(c, c['valuation']['security']['shares'])
        self.assertIsNone(r['latestIssued'])
        self.assertIsNone(r['latestTreasury'])
        self.assertIsNone(r['repurchase'])
        self.assertTrue(all(p['filedAt'] <= '2026-08-18' for p in r['passages']))

    def test_changed_opening_share_scope_is_not_silently_accepted(self):
        c = copy.deepcopy(self.company)
        shares = copy.deepcopy(c['valuation']['security']['shares'])
        shares['issued'] += 1
        with self.assertRaisesRegex(ValueError, 'starting share table'):
            build(c, shares)


if __name__ == '__main__':
    unittest.main()
