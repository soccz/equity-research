"""Standalone source-bound chart, independent from the app snapshot renderer."""
import json
import hashlib
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Patch

root=Path(__file__).resolve().parents[2]
source=root/'artifacts/local/cloud-pair-cash-burden-review.json'
data=json.loads(source.read_text())
font=FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc').get_name()
plt.rcParams.update({'font.family':font,'axes.unicode_minus':False,'svg.fonttype':'path','font.size':11})
fig,axes=plt.subplots(1,2,figsize=(14,8),sharey=True)
fig.patch.set_facecolor('#fafbf8')
fig.subplots_adjust(left=.065,right=.98,top=.73,bottom=.28,wspace=.14)
fig.text(.065,.93,'같은 12개월, 투자 이후의 현금 부담',fontsize=23,weight='bold',color='#193d3b')
fig.text(.065,.875,'영업현금에서 총 설비 취득·원금 상환·주식보상 대용 비용을 차감한 연구자 정의',fontsize=12,color='#526567')
fig.text(.065,.825,'2025.07.01–2026.06.30  /  십억 달러  /  Microsoft 연간 · Amazon 최근 1년 연결',fontsize=10,color='#526567')
labels=['공시\n영업현금','− 총 현금\n설비 취득','− 리스·시설\n금융 원금','− 주식보상\n대체 가정','계산한\n잔액']
for ax,c in zip(axes,data['companies']):
 values=[c['cfo'],-c['grossPpeCash'],-c['leaseAndFacilityPrincipal'],-c['sbcReplacementProxy']]
 assert sum(values)==c['grossBasisResidual']
 values=[v/1e9 for v in values];residual=c['grossBasisResidual']/1e9
 running=0
 ax.set_facecolor('#fafbf8');ax.axhline(0,color='#718487',lw=.8,zorder=1)
 for i,v in enumerate(values):
  old=running;running+=v
  ax.bar(i,abs(v),bottom=min(old,running),width=.62,color=('#338980' if i==0 else '#b77b61' if i<3 else '#b9a990'),edgecolor='#fafbf8',hatch='///' if i==3 else None,zorder=3)
  ax.text(i,max(old,running)+7,f'{v:+,.3f}' if i else f'{v:,.3f}',ha='center',fontsize=11,color='#243c3a')
  if i<3:ax.plot([i+.31,i+.69],[running,running],color='#81918d',lw=.8,ls='--')
 ax.bar(4,abs(residual),bottom=min(0,residual),width=.68,color='#1e7166' if residual>=0 else '#a75037',zorder=3)
 ax.text(4,residual+(8 if residual>=0 else -10),f'{residual:+,.3f}',ha='center',va='bottom' if residual>=0 else 'top',fontsize=15,weight='bold',color='#1e7166' if residual>=0 else '#a75037')
 ax.set_title('Microsoft' if c['company']=='MSFT' else 'Amazon',loc='left',weight='bold',fontsize=17,pad=20,color='#243c3a')
 ax.set_xticks(range(5),labels,fontsize=10);ax.set_ylim(-66,211);ax.set_yticks([0,50,100,150,200]);ax.tick_params(length=0,pad=8)
 ax.grid(axis='y',color='#dfe5df',lw=.6,zorder=0)
 for spine in ax.spines.values():spine.set_visible(False)
axes[0].set_ylabel('십억 달러',labelpad=10,color='#526567')
fig.legend(handles=[Patch(facecolor='#b9a990',hatch='///',label='주식보상 비용을 현금 보상으로 대체하는 가정')],loc='lower left',bbox_to_anchor=(.055,.155),frameon=False,fontsize=10)
fig.text(.065,.145,'설비 매각·인센티브 유입은 양쪽 모두 더하지 않음. 차입 차환·인수·비지배지분·현금세금 정상화는 별도 검토.',fontsize=9,color='#526567')
fig.text(.065,.11,'잔액은 배당가능현금·기업 공시 FCF·미래 전망을 뜻하지 않음. 증설과 유지투자의 구별 및 회수 검증이 남아 있음.',fontsize=9,color='#526567')
fig.text(.065,.064,'출처: Microsoft 2026 Form 10-K · Amazon 2025 Form 10-K 및 2026 Q2 Form 10-Q. 원금액·태그·공시 링크는 동봉 JSON.',fontsize=9,color='#526567')
base=root/'artifacts/local/cloud-pair-cash-burden'
for ext in ['png','svg','pdf']:fig.savefig(str(base)+'.'+ext,dpi=160,facecolor=fig.get_facecolor())
record={'sourceFile':str(source.relative_to(root)),'sourceHash':hashlib.sha256(source.read_bytes()).hexdigest(),'modelHashes':{c['company']:c['operatingEvidenceHash'] for c in data['companies']},'period':data['period'],'outputs':{ext:hashlib.sha256(Path(str(base)+'.'+ext).read_bytes()).hexdigest() for ext in ['png','svg','pdf']},'scope':'연구자 정의의 관측 비교. 시각 점검 대상, 투자 의견 승인 아님.'}
Path(str(base)+'-manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print('Saved PNG/SVG/PDF and source/model hash manifest')
