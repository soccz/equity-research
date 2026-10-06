from pathlib import Path
import copy,json,sys
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from equitylab.operating_model import calculate
from equitylab.operating_inverse import margins
B=Path(__file__).resolve().parent;m=json.loads((B/'candidate-operating-model.json').read_text());cases=[]
for change in [{},{'tax':0},{'discount':.15},{'capexEnd':.15},{'workingCapital':.3},{'corporateEnd':.18},{'leaseStart':.005,'leaseEnd':.01}]:
 a=copy.deepcopy(m['defaults']);a.update(change);cases.append(dict(assumptions=a,calculation=calculate(m,a),inverse=margins(m,a)))
a=copy.deepcopy(m['defaults']);a['segments'][0]['growthStart']=.1;a['segments'][1]['marginEnd']=.65;cases.append(dict(assumptions=a,calculation=calculate(m,a),inverse=margins(m,a)))
(B/'cash-path-cases.json').write_text(json.dumps(dict(model=m,cases=cases),ensure_ascii=False));print(len(cases),'cash and inverse cases prepared')
