"""Source-bound Tesla earnings and cash bridges, independent export."""
import copy, hashlib, json, sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from equitylab.tesla_operating import build, CASH_ROLES
p=json.loads((ROOT/'data/latest.json').read_text());s=json.loads((ROOT/p['snapshot']).read_text());c=next(c for c in s['companies'] if c['id']=='TSLA');m=build(copy.deepcopy(c),s['asOf']);f=m['facts']
def val(k,i):return f[k]['components'][i]['fact']['value']
def delta(k):return val(k,1)-val(k,2)
working=sum(sign*delta(tag) for tag,_,sign in CASH_ROLES[8:]);noncash=sum(sign*delta(tag) for tag,_,sign in CASH_ROLES[1:8] if tag!='ShareBasedCompensation')
cash_steps=[delta('ProfitLoss'),delta('ShareBasedCompensation'),noncash,-f['equityGain']['value'],working]
assert val('cfo',2)+sum(cash_steps)==val('cfo',1)
plt.rcParams.update({'font.family':FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc').get_name(),'axes.unicode_minus':False,'svg.fonttype':'path','font.size':10})
fig,axes=plt.subplots(2,1,figsize=(13,11));fig.patch.set_facecolor('#fafbf8');fig.subplots_adjust(left=.075,right=.97,top=.79,bottom=.18,hspace=.6)
fig.text(.075,.935,'Tesla | 매출총이익의 증가와 현금의 증가를 분리하다',fontsize=21,weight='bold',color='#193d3b')
fig.text(.075,.89,'2026년 상반기: 매출 +21.0%  /  영업이익 +1.3%  /  영업현금 +83.9%',fontsize=13,color='#365653')
fig.text(.075,.845,'단위: 십억 달러  ·  연결 공시 · 전년 동기 대비 산술 분해  ·  미래 수익성이나 인과관계의 검증이 아님',fontsize=10,color='#5b6e68')
def plot(ax,start,steps,end,labels,title):
 running=0; tops=[];ax.set_facecolor('#fafbf8')
 vals=[start,*steps]
 for i,v in enumerate(vals):
  old=running;running+=v;tops.extend([old,running]);bottom=min(old,running)/1e9
  ax.bar(i,abs(v)/1e9,bottom=bottom,width=.58,color='#32867c' if v>=0 else '#b87859',zorder=3)
  ax.plot([i+.29,i+.71],[running/1e9]*2,color='#889c95',lw=.8,ls='--')
 ax.bar(len(vals),end/1e9,width=.62,color='#1c685e',zorder=3);tops.append(end)
 ymax=max(tops)/1e9
 for i,v in enumerate(vals):
  old=sum(vals[:i]);new=old+v;ax.text(i,max(old,new)/1e9+ymax*.04,('%+.3f' if i else '%.3f')%(v/1e9),ha='center',fontsize=11,color='#233d38')
 ax.text(len(vals),end/1e9+ymax*.04,f'{end/1e9:.3f}',ha='center',fontsize=12,weight='bold',color='#1c685e')
 ax.set_xticks(range(len(labels)),labels);ax.set_ylim(0,ymax*1.22);ax.set_title(title,loc='left',pad=25,fontsize=14,weight='bold',color='#23413d');ax.grid(axis='y',color='#dce4df',lw=.6);ax.tick_params(length=0,pad=8)
 for sp in ax.spines.values():sp.set_visible(False)
profit=m['profitChange'];plot(axes[0],profit['start'],[r['value'] for r in profit['parts']],profit['end'],['전년 반기\n영업이익','매출총이익\n증가','연구개발비\n증가','판매관리비\n증가','구조조정비\n감소','당반기\n영업이익'],'매출총이익 +2.440 → 공통 비용 영향 −2.423 → 영업이익 +0.017')
plot(axes[1],val('cfo',2),cash_steps,val('cfo',1),['전년 반기\n영업현금','연결 순이익\n변화','주식보상\n조정 증가','상각·기타\n비현금 조정','지분 투자\n평가이익 제거','영업자산·\n부채 효과','당반기\n영업현금'],'영업현금 증가는 손익 증가와 다른 경로를 포함한다')
fig.text(.075,.12,'해석: 비용 증가는 미래 사업 투자일 수 있다. 현재 분해만으로 투자 실패 또는 지속 가능한 현금 개선을 확정하지 않는다.',fontsize=10,color='#795b3a')
fig.text(.075,.08,'현금표 조정은 실제 현금 유입 항목이 아니다. 순설비 취득·리스 원금·주식보상 대체 부담을 반영한 미래 경로를 별도로 검토한다.',fontsize=9,color='#526567')
fig.text(.075,.04,'출처: Tesla 2026-06-30 10-Q, accession 0001628280-26-049270. 원금액·태그·기간·원문 해시는 동봉 JSON.',fontsize=9,color='#526567')
base=ROOT/'artifacts/local/tesla-profit-cash-research'
for ext in ['png','svg','pdf']:fig.savefig(str(base)+'.'+ext,dpi=160,facecolor=fig.get_facecolor())
record={'modelHash':m['evidenceHash'],'asOf':s['asOf'],'profit':profit,'cash':{'start':val('cfo',2),'steps':cash_steps,'end':val('cfo',1)},'sources':f,'outputs':{ext:hashlib.sha256(Path(str(base)+'.'+ext).read_bytes()).hexdigest() for ext in ['png','svg','pdf']}}
Path(str(base)+'-manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');print('Source-bound Tesla PNG/SVG/PDF saved. Cash steps:',cash_steps)
