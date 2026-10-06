from pathlib import Path
import json,shutil,re
root=Path('.');stage=root/'artifacts/local/micron-study'
for src in (stage/'data/sources').iterdir():
    dst=root/'data/sources'/src.name
    if dst.exists() and dst.read_bytes()!=src.read_bytes():
        if not src.name.endswith('.manifest.json'):raise ValueError('Existing original differs: '+str(dst))
        a,b=json.loads(src.read_text()),json.loads(dst.read_text())
        if any(a.get(k)!=b.get(k) for k in ['file','sha256','url','accession','cik']):raise ValueError('Existing source identity differs: '+str(dst))
    elif not dst.exists():shutil.copy2(src,dst)
p=root/'data/segment-continuity.json';contract=json.loads(p.read_text());new=next(r for r in json.loads((stage/'data/segment-continuity.json').read_text())['cases'] if r['company']=='MU');new['annualSource']=json.loads((root/'data/sources/filing-0000723125-25-000028-xbrl.manifest.json').read_text());contract['cases']=[r for r in contract['cases'] if r['company']!='MU']+[new];p.write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n')
s=(stage/'micron_operating.py').read_text();s=s[:s.index('\nif __name__ == "__main__":')];s=s.replace('from pathlib import Path\n','').replace('from equitylab.', 'from .');s=re.sub(r'ANNUAL_ROOT = \(.*?\)  # Staging only; switch on integration\.', 'ANNUAL_ROOT = ROOT',s,flags=re.S);(root/'equitylab/micron_operating.py').write_text(s)
p=root/'equitylab/operating_model.py';s=p.read_text();i=s.index('    if c["id"] == "AAPL":');s=s[:i]+'''    if c["id"] == "MU":
        from .micron_operating import build as micron_build

        return micron_build(c, as_of)
'''+s[i:];p.write_text(s)
p=root/'scripts/local-coverage.py';s=p.read_text().replace('                    export(load_latest())\n                report["status"]', '                    if not reused:\n                        export(load_latest())\n                export(load_latest())\n                report["status"]');p.write_text(s)
p=root/'equitylab/security.py';s=p.read_text().replace('            "의결권있는주식(보통주)",','            "의결권있는주식(보통주)",\n            "의결권이있는주식(보통주)",');p.write_text(s)
s=(stage/'test_candidate.py').read_text();start=s.index('class MicronOperatingTests');s='''import copy
import unittest
from unittest.mock import patch
from equitylab import micron_operating as mu
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest
from equitylab.segment_history import build as segments


'''+s[start:];a=s.index('        cls.company =');b=s.index('\n    def test_',a);s=s[:a]+'''        snapshot = load_latest()
        cls.company = copy.deepcopy(next(c for c in snapshot["companies"] if c["id"] == "MU"))
        cls.company["segmentHistory"] = segments(cls.company, snapshot["asOf"])
        cls.model = mu.build(copy.deepcopy(cls.company), snapshot["asOf"])
'''+s[b:];(root/'tests/test_micron_operating.py').write_text(s)
p=root/'tests/test_security.py';s=p.read_text();i=s.index('    def test_all_korean_sources');s=s[:i]+'''    def test_explicit_common_label_with_particle_keeps_preferred_rights_separate(self):
        c = copy.deepcopy(self.companies["009150"])
        table = load(c, self.snapshot["asOf"])
        self.assertEqual(table["shares"]["value"], 72693696)
        self.assertTrue(table["classes"][0]["common"])
        self.assertFalse(table["classes"][1]["common"])
        self.assertTrue(any("우선주" in t for t in table["issues"]))
        self.assertFalse(any("보통주)" in t for t in table["issues"]))
        self.assertEqual(build(c, self.snapshot["asOf"])["security"]["status"], "unresolved")

'''+s[i:];p.write_text(s)
print('Integrated Micron model, source continuity, share label and no-op export improvement')
