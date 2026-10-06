from pathlib import Path
import importlib.util,sys,unittest,json,copy
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT));STAGE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('equitylab.costco_operating',STAGE/'costco_operating.py');m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);m.DOCUMENT_ROOT=STAGE
spec=importlib.util.spec_from_file_location('test_costco_staging',STAGE/'test_costco_operating.py');test=importlib.util.module_from_spec(spec);spec.loader.exec_module(test)
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test))
if not r.wasSuccessful():raise SystemExit(1)
from equitylab.operating_model import calculate
from equitylab.operating_inverse import margins
model=m.build(json.loads((STAGE/'COST-company.json').read_text()),'2026-09-29');cases=[]
for change in [{},{'capexEnd':.07},{'workingCapital':.2},{'tax':.3},{'netInterest':.04},{'discount':.15}]:
 a={**copy.deepcopy(model['defaults']),**change};cases.append(dict(assumptions=a,calculation=calculate(model,a),inverse=margins(model,a)))
(STAGE/'COST-candidate.json').write_text(json.dumps(model,ensure_ascii=False,indent=2))
(STAGE/'COST-cash-path-cases.json').write_text(json.dumps(dict(model=model,cases=cases),ensure_ascii=False,allow_nan=False))
