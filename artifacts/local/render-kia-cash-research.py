"""Standalone source-bound Kia cash and warranty research figure."""
import json
import hashlib
from pathlib import Path
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from equitylab.kia_operating import build
pointer = json.loads((ROOT/'data/latest.json').read_text())
snapshot = json.loads((ROOT/pointer['snapshot']).read_text())
c = next(c for c in snapshot['companies'] if c['id']=='000270')
m = build(c, snapshot['asOf'])
f = m['facts']
val = lambda key, period: f[key]['components'][period]['fact']['value']
delta = lambda key: val(key,1)-val(key,2)
start = val('cfo',2)
steps = [delta('netIncome'),delta('adjustments'),delta('workingCash'),delta('interestIncome')-delta('interestExpense')+delta('dividends'),-delta('cashTaxes')]
assert start+sum(steps)==val('cfo',1)
w = m['warranty']['periods'][1]
assert w['opening']['value']+w['added']-w['used']+w['other']==w['closing']['value']
font = FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc').get_name()
plt.rcParams.update({'font.family':font,'axes.unicode_minus':False,'svg.fonttype':'path','font.size':10})
fig,axes=plt.subplots(2,1,figsize=(13,11));fig.patch.set_facecolor('#fafbf8');fig.subplots_adjust(left=.075,right=.975,top=.78,bottom=.18,hspace=.58)
fig.text(.075,.935,'기아 | 이익 감소와 현금 증가가 함께 나타난 이유',fontsize=22,weight='bold',color='#193d3b')
fig.text(.075,.89,'2026년 상반기 영업이익 4.834조 원 (−16.3%)  /  영업현금 7.167조 원 (+33.9%)',fontsize=13,color='#365653')
fig.text(.075,.845,'단위: 조 원  ·  연결 공시 기준  ·  회계 항목의 증감 분해이며 인과관계·정상 현금 전망은 별도 판단',fontsize=10,color='#5b6e68')
def waterfall(ax, start, steps, end, labels, title):
 vals=[start,*steps];running=0;ax.set_facecolor('#fafbf8')
 for i,v in enumerate(vals):
  old=running;running+=v
  ax.bar(i,abs(v)/1e12,bottom=min(old,running)/1e12,width=.56,color='#32867c' if v>=0 else '#b87859',zorder=3)
  ax.text(i,max(old,running)/1e12+.17, f'{v/1e12:+.3f}' if i else f'{v/1e12:.3f}',ha='center',fontsize=11,color='#233d38')
  ax.plot([i+.28,i+.72],[running/1e12]*2,color='#889c95',lw=.8,ls='--')
 ax.bar(len(vals),end/1e12,width=.64,color='#1c685e',zorder=3);ax.text(len(vals),end/1e12+.17,f'{end/1e12:.3f}',ha='center',fontsize=13,weight='bold',color='#1c685e')
 ax.set_xticks(range(len(labels)),labels,fontsize=10);ax.set_ylim(0,max(start,end,start+max(steps))*1.20/1e12)
 ax.set_title(title,loc='left',fontsize=14,pad=25,weight='bold',color='#23413d');ax.grid(axis='y',color='#dce4df',lw=.6,zorder=0);ax.tick_params(length=0,pad=8)
 for sp in ax.spines.values():sp.set_visible(False)
waterfall(axes[0],start,steps,val('cfo',1),['전년 반기\n영업현금','순이익\n변화','비현금 등\n이익 조정','영업자산·\n부채 효과','이자·배당\n순유입','법인세\n지급 감소','당반기\n영업현금'],'영업현금 증가 1.814조 원: 세금 지급과 자산·부채 변동도 기여')
waterfall(axes[1],w['opening']['value'],[w['added'],-w['used'],w['other']],w['closing']['value'],['기초\n보증충당부채','충당부채\n증가','충당부채\n사용','기타\n변동','기말\n보증충당부채'],'판매보증: 기말 잔액은 늘었지만, 증가액과 현금표 비용 조정은 다르다')
fig.text(.075,.115,'당반기 충당부채 증가 2.662  ≠  판관비 판매보증비 2.106  ≠  현금표 보증비 조정 2.018',fontsize=11,weight='bold',color='#795b3a')
fig.text(.075,.077,'충당부채 사용 2.180은 현금표 조정과 일치한다. 고객 직접 지급액·현재 판매분 결함률로 단정하지 않는다.',fontsize=9,color='#526567')
fig.text(.075,.04,'출처: 기아 반기보고서 20260916000427, 연결 현금흐름 및 충당부채 주석. 원금액·기간·XBRL 태그·해시는 동봉 JSON.',fontsize=9,color='#526567')
base=ROOT/'artifacts/local/kia-cash-warranty-research'
for ext in ['png','svg','pdf']:fig.savefig(str(base)+'.'+ext,dpi=160,facecolor=fig.get_facecolor())
record={'company':c['id'],'accession':m['accession'],'modelHash':m['evidenceHash'],'period':['2026-01-01','2026-06-30'],'cashChange':{'start':start,'steps':steps,'end':val('cfo',1)},'warranty':w,'sources':{k:v for k,v in f.items() if k in ['cfo','netIncome','adjustments','workingCash','cashTaxes','interestIncome','interestExpense','dividends']},'outputs':{ext:hashlib.sha256(Path(str(base)+'.'+ext).read_bytes()).hexdigest() for ext in ['png','svg','pdf']},'scope':'Author arithmetic reconciliation. No causal or investment preference approval.'}
Path(str(base)+'-manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print('Saved Kia cash/warranty PNG, SVG, PDF and original fact manifest')
