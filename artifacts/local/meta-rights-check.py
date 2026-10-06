import copy
import importlib.util
import unittest
from unittest.mock import patch
from equitylab.pipeline import load_latest
from equitylab.xbrl import company_filing

spec=importlib.util.spec_from_file_location('rights','artifacts/local/meta-rights-candidate.py')
rights=importlib.util.module_from_spec(spec);spec.loader.exec_module(rights)


class MetaRightsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s=load_latest();cls.company=next(c for c in s['companies'] if c['id']=='META')
        _,rows=company_filing(cls.company,s['asOf'])
        cls.rows=[r for r in rows if r['unit']=='shares' and r['start'] is None and cls.company['financials']['end']<=r['end']<=cls.company['priceSummary']['lastDate']]
        cls.members=['CommonClassAMember','CommonClassBMember']

    def test_equal_cash_rights_reconcile_precise_same_day_counts(self):
        r=rights.meta_entitlement(copy.deepcopy(self.company),self.rows,self.members,[])
        self.assertEqual(r['shares']['value'],2547506225)
        self.assertEqual(r['shares']['end'],'2026-07-24')
        self.assertEqual([v['fact']['value'] for v in r['shares']['components']],[2205128509,342377716])
        self.assertIn('different voting rights',r['evidence']['quote'])
        self.assertIn('대용치',r['assumption'])

    def test_missing_class_or_changed_date_cannot_use_weighted_average(self):
        for rows in [self.rows[1:],[dict(r,end='2026-07-25') if r['tag']=='EntityCommonStockSharesOutstanding' else r for r in self.rows]]:
            self.assertIsNone(rights.meta_entitlement(copy.deepcopy(self.company),rows,self.members,[]))

    def test_preferred_and_new_class_require_separate_allocation(self):
        self.assertIsNone(rights.meta_entitlement(copy.deepcopy(self.company),self.rows,self.members,[{'value':1}]))
        self.assertIsNone(rights.meta_entitlement(copy.deepcopy(self.company),self.rows,self.members+['NewClassMember'],[]))

    def test_new_filing_or_source_hash_cannot_inherit_review(self):
        c=copy.deepcopy(self.company);c['financials']['current']['cfo']['accession']='future'
        self.assertIsNone(rights.meta_entitlement(c,self.rows,self.members,[]))
        rows=[dict(r,sourceHash='changed') for r in self.rows]
        self.assertIsNone(rights.meta_entitlement(copy.deepcopy(self.company),rows,self.members,[]))

    def test_cash_rights_phrase_must_exist_in_verified_original(self):
        original=rights.extract
        def changed(blob):
            return [dict(p,text='voting rights only') if p['ordinal']==210 else p for p in original(blob)]
        with patch.object(rights,'extract',side_effect=changed):
            self.assertIsNone(rights.meta_entitlement(copy.deepcopy(self.company),self.rows,self.members,[]))


if __name__=='__main__':unittest.main(verbosity=2)
