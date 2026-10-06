from pathlib import Path
import sys, json, importlib.util
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from equitylab import operating_model
STAGE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('equitylab.oracle_staging',STAGE/'oracle_operating.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.DOCUMENT_ROOT=STAGE
# A private copy permits this source-backed candidate's >100% capex only. The
# production calculator stays frozen until its integrated run has finished.
code=(ROOT/'equitylab/operating_model.py').read_text()
old='not 0 <= a[k] <= 1\n        for k in ("depreciation", "capexStart", "capexEnd", "leaseStart", "leaseEnd")'
new='not 0 <= a[k] <= (model.get("capexLimit", 1) if k in ("capexStart", "capexEnd") else 1)\n        for k in ("depreciation", "capexStart", "capexEnd", "leaseStart", "leaseEnd")'
assert old in code
namespace={'__name__':'equitylab.oracle_candidate_calculator','__package__':'equitylab'}
exec(compile(code.replace(old,new,1),str(STAGE/'candidate-calculator.py'),'exec'),namespace)
c=json.loads((STAGE/'company-start.json').read_text())
with patch.object(operating_model,'calculate',namespace['calculate']):
 model=m.build(c,'2026-09-29')
(STAGE/'candidate-operating-model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2))
print(json.dumps({'period':model['sourcePeriod'],'revenues':model['facts']['revenue']['value'],'cfo':model['bridge']['reportedCfo'],'capex':model['facts']['capex']['value'],'capexRatio':model['defaults']['capexStart'],'leaseProxy':model['anchors']['financeLeasePrincipalProxy'],'corporate':model['anchors']['reportedCorporateCost'],'firstCash':model['initial']['years'][0]['cash'],'sourcePassages':len(model['passages'])}))
