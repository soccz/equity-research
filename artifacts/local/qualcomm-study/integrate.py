"""Apply the reviewed candidate only after the active integrated run has ended."""
from pathlib import Path
import json,shutil
B=Path(__file__).resolve().parent;ROOT=B.parents[2]
p=sorted((ROOT/'artifacts/local/runs').glob('*/run.json'))[-1]
r=json.loads(p.read_text())
if r.get('status')=='running':raise RuntimeError('The latest integrated run is still active: '+str(p))
s=(B/'qualcomm_operating.py').read_text().replace('from pathlib import Path\n','').replace('from equitylab.','from .').replace('DOCUMENT_ROOT = Path(__file__).resolve().parent','DOCUMENT_ROOT = ROOT').replace('Qualcomm candidate:','Qualcomm:')
s=s[:s.index('\n\nif __name__ == "__main__":')]
(ROOT/'equitylab/qualcomm_operating.py').write_text(s+'\n')
s=(B/'test_qualcomm_operating.py').read_text();start=s.index('B = Path');end=s.index('\n\nclass Qualcomm',start)
s=s[:start]+'from equitylab import qualcomm_operating as candidate\nfrom equitylab.pipeline import load_latest'+s[end:]
s=s.replace('import unittest, copy, json, importlib.util','import unittest, copy').replace('from pathlib import Path\n','').replace('json.loads((B / "company-start.json").read_text())','next(c for c in load_latest()["companies"] if c["id"]=="QCOM")')
(ROOT/'tests/test_qualcomm_operating.py').write_text(s)
for p in (B/'data/sources').iterdir():
 dst=ROOT/'data/sources'/p.name
 if dst.exists():assert dst.read_bytes()==p.read_bytes()
 else:shutil.copy2(p,dst)
p=ROOT/'equitylab/operating_model.py';s=p.read_text();assert 'from .qualcomm_operating' not in s;s=s.replace('def build(c, as_of):\n','def build(c, as_of):\n    if c["id"] == "QCOM":\n        from .qualcomm_operating import build as qualcomm\n\n        return qualcomm(c, as_of)\n');p.write_text(s)
p=ROOT/'app/operating-model.js';s=p.read_text();assert 'function licensingEvidence' not in s;s=s.replace('  function render(c){',(B/'ui-fragment.js').read_text()+'  function render(c){',1).replace('${softwareEvidence(m)}','${softwareEvidence(m)}${licensingEvidence(m)}');p.write_text(s)
p=ROOT/'app/styles.css';p.write_text(p.read_text()+'''\n.operating-licensing-evidence{margin:24px 0;padding:18px;border:1px solid var(--line)}
.operating-licensing-evidence h3{margin-top:24px}
@media print{.operating-licensing-evidence h3{break-after:avoid}.operating-licensing-evidence table{break-inside:avoid}.operating-licensing-evidence td,.operating-licensing-evidence th{padding:5px 8px}}
''')
print('Qualcomm model, source, tests and renderer integrated; browser and artifact assertions still required')
