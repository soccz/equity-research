"""Source-read additions; idempotent upsert, never change the forward cohort."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from equitylab.pipeline import load_latest
from equitylab.narrative import load

companies = {c['id']: c for c in load_latest()['companies']}
cases = [
    dict(company='AMAT', title='첨단 공정 투자와 서비스의 반복 수익 범위를 나눈다',
         passageIds=['aaffe7fc9d8c86b0fe31','02b420325bdfc3a94f0f','240ae2d5ea22aefb728c','4160cf4e9332d1fcd747','06b5d0e2f1e5630061b9','4ece70d9c96eb685978f','5832b58e7c288cb8c456'],
         observation='회사는 9개월 장비 매출 증가에 첨단 로직·파운드리와 DRAM 기술 전환 투자가 기여했고, 구형 로직 수요 감소가 일부 상쇄했다고 설명한다. AGS 성장은 장기 서비스 계약과 부품 매출에서 나왔다. 누적기간에는 수출통제 준수 사안의 합의 비용 2.53억 달러를 인식했다.',
         interpretation='AGS에는 한 시점에 인식하는 부품·장비와 기간에 걸쳐 인식하는 서비스가 함께 있다. 전체 AGS를 구독 매출로 놓으면 장비 가동률·부품 수요의 변동을 빠뜨린다. 장비 마진 개선은 가격·원가·연구개발 및 합의 비용을 나눠 읽어야 한다.',
         countercase='설치 기반과 장기 계약 확대는 실제로 반복 매출을 강화할 수 있다. 모든 서비스 매출이 구독은 아니라는 사실이 계약 기반 개선을 부정하지는 않는다. 규제 비용을 제거한 이익에도 향후 수출 제한의 사업 영향은 남는다.',
         priceImplication='첨단·구형 공정 수요와 서비스 계약·부품의 성장 경로를 구분한다. 합의 비용의 향후 반복 여부와 지급 시점을 별도로 검토하고, 보고 영업현금에 같은 금액을 무조건 더하지 않는다. 정상 마진 가정에는 지속 연구개발과 수출 가능 범위를 반영한다.',
         comparison='Lam의 고객지원에는 구형 공정용 Reliant 장비도 포함된다. Applied의 9개월과 Lam의 연간 증가율을 그대로 순위화하거나 두 서비스 범주를 같은 구독 사업으로 취급하지 않는다.',
         changeCondition='후속 동일 기간의 첨단·구형 공정 주문과 인도, DRAM 전환 투자, 장기 계약·부품 구성 및 합의 비용의 지급을 확인한다. 설치 기반 확대에도 계약·부품 현금이 따라오지 않으면 반복 수익 개선 논지를 낮춘다.'),
    dict(company='LRCX', title='고객지원 성장과 장비 수요의 노출을 함께 읽는다',
         passageIds=['8722d26f723f7e8be695','ddf6ea27d1d8d32cf4f5','96ca2aeb10fc403a0dba','2734f5afdaeec3b9b66f','6e320349f0d2d9d49b54','04e2d6ba29a128eabb1f'],
         observation='회사는 2026 회계연도 시스템 매출 29.5%, 고객지원 관련 매출 20.2% 증가를 공시했다. 후자의 증가에는 부품과 구형 공정용 장비가 기여했다. 장비·업그레이드 매출의 파운드리 비중은 9%p 높아지고 메모리 비중은 3%p 낮아졌다. 이연매출 감소에는 고객 선급금 감소가 기여했다.',
         interpretation='고객지원 매출 전체를 유지보수 계약의 반복 매출로 볼 수 없다. 메모리 비중 하락은 절대 메모리 매출 감소율이 아니며, 해당 구성표의 분모는 장비·업그레이드 매출이다. 보고 성장과 고객 선급금 흐름도 분리해야 한다.',
         countercase='증가한 설치 기반·공정 복잡성이 부품과 업그레이드 수요를 장기간 지지할 수 있다. 선급금 감소만으로 고객 신용 악화나 장비 수요 감소를 단정할 수 없고 인도·매출 인식 시점도 확인해야 한다.',
         priceImplication='신규 장비와 고객지원의 성장·마진을 구분하되 고객지원 안의 장비 노출을 유지한다. 고객 구성의 총이익률 효과와 금속 관세·연구개발 비용을 따로 가정하고, 선급금 감소가 현금 전환에 미치는 기간 효과를 확인한다.',
         comparison='Applied Materials와는 공정·고객 노출 및 부품·장비·서비스 범위를 먼저 맞춘다. 한 회사의 연간과 다른 회사의 9개월을 동일 기간 성과로 보지 않는다.',
         changeCondition='다음 같은 기간의 파운드리·메모리 장비와 고객지원 내 부품·Reliant 장비 수요, 가동률, 인도 및 고객 선급금을 확인한다. 고객지원 성장의 대부분이 장비 인도에 치우치면 반복 계약 프리미엄 가정을 낮춘다.'),
    dict(company='QCOM', title='자동차 다변화의 기여와 휴대폰 출하 압박을 따로 본다',
         passageIds=['a746ad37313de37e4646','f4d4959b417d224656db','2041ca02f3d687de621c','29c52ba32006ab8f5e70','8001d58dfcc9d9f4c495','b3dde640b8066a361cc9','795ef3cfbfdb35b9d69b','a94b250eb5e20a14c774','54291e386800cab6043b'],
         observation='회사는 3분기 휴대폰 칩 출하 감소를 주요 고객의 생산·재고 조정과 메모리 공급·가격 압박으로 설명한다. 자동차 매출 증가의 분해는 가격·구성 효과 3.81억 달러와 출하 효과 2.23억 달러다. 9개월 자동차 분해는 각각 5.60억·5.51억 달러로 별개다. QCT 세전이익률은 제품 원가 부담 등으로 하락했다.',
         interpretation='자동차 매출 다변화와 휴대폰 사업의 압박은 동시에 존재한다. 가격·구성에 따른 매출 기여 금액을 칩 한 개의 판매가격으로 오독하지 않는다. 회사가 설명한 메모리 제약과 휴대폰 칩 출하의 연결은 독립 인과 검증과 구분한다.',
         countercase='새 차종의 디지털 콕핏·ADAS 탑재가 장기 고객 관계와 매출 기반을 키울 수 있고, 휴대폰의 고객 재고 조정은 일시적일 수 있다. 현재 연결 성장 둔화만으로 자동차 확장의 가치를 영으로 둘 수는 없다.',
         priceImplication='휴대폰·자동차·IoT의 매출 경로와 QCT 비용을 나누고 QTL 라이선스 수익 구조를 별도로 검토한다. QCT EBT를 영업이익으로 대체하거나 자동차 매출 기여를 같은 금액의 현금 증가로 넣지 않는다.',
         comparison='메모리 가격 상승은 공급 기업과 휴대폰 칩 수요에 반대 방향으로 작용할 수 있다. 메모리 기업의 성장률을 Qualcomm 수요의 동반 개선 증거로 쓰지 않으며 AMD·NVIDIA와도 제품 범위를 맞춘다.',
         changeCondition='다음 분기의 휴대폰 출하·고객 재고와 메모리 조달 설명, 자동차 신규 차종 및 가격·구성·출하 분해, QCT 원가·세전이익률을 확인한다. 다변화가 이어져도 전체 현금 수익성이 회복되지 않으면 성장의 이익 전환 가정을 낮춘다.'),
    dict(company='INTC', title='파운드리 적자 축소에서 비용 기저와 제품 수익을 분해한다',
         passageIds=['51638c38ce3c183a7d0b','cf367454e2c8f7d9447a','63100509960a1bead134','d6774a40398e8eb8e10f','79e1f12b2bd591286d1c','dba54600730f26426b08','44ab5e1e2e33bfcb959b','64bcc81719b989f7494f'],
         observation='Intel Foundry의 반기 영업손실은 전년 54.88억 달러에서 45.26억 달러로 줄었다. 회사는 기간 비용 감소 약 18억 달러의 개선과 제품 수익 8.30억 달러 감소의 상쇄를 설명한다. 파운드리 외부 매출 증가에는 Altera의 연결 제외 후 외부 고객 전환이 크게 기여했다.',
         interpretation='적자 축소 전체를 첨단 공정의 원가 경쟁력 개선으로 읽기 어렵다. 회사 설명상 높은 원가의 18A 웨이퍼 구성은 제품 수익에 부담을 줬다. 연결 전체의 제품 수익 증가와 Foundry 부문의 제품 수익 감소는 서로 다른 범위이므로 혼동하지 않는다.',
         countercase='Intel 3·4의 원가 하락과 높은 매출은 개선 요인이다. 초기 18A의 원가 부담이 가동·수율 개선으로 완화될 가능성도 있다. 전년 비용의 부재가 개선에 기여했다는 이유만으로 공정 투자의 모든 성과를 부정하지 않는다.',
         priceImplication='제품 사업과 내부 제조 중심 Foundry의 이익을 연결 제거와 함께 대사한다. Altera의 외부 분류 전환을 신규 외부 수주의 순증으로 가정하지 않는다. 비현금 손상 제거와 실제 설비·개발·구조조정 지급을 분리한 현금 모델이 필요하다.',
         comparison='AMD·NVIDIA의 설계 사업과 Intel의 제조 투자·내부 거래는 자본 부담이 다르다. Foundry 외부 매출의 증감을 독립 파운드리 경쟁력 순위로 바꾸기 전에 재분류와 고객 구성을 조정한다.',
         changeCondition='다음 같은 반기의 공정별 원가·제품 구성, 기간 비용 및 재고 평가, Altera를 구분한 외부 고객 인도와 설비 현금을 확인한다. 전년 비용 기저가 사라진 후에도 제품 수익이 나아지고 투자 이후 현금이 회복되는지가 판단을 바꾼다.')
]
path=ROOT/'data/business-insights.json'
data=json.loads(path.read_text())
backup=ROOT/'artifacts/local/business-insights-before-semiconductor.json'
if not backup.exists(): backup.write_bytes(path.read_bytes())
for r in cases:
    c=companies[r['company']];meta=c['narrative']
    available={p['id'] for p in load(c)['passages']}
    assert len(set(r['passageIds']))==len(r['passageIds']) and set(r['passageIds'])<=available
    r.update(accession=meta['accession'],corpusHash=meta['evidenceHash'],authorship='개발 중 원문 대조로 작성한 연구 초안',reviewStatus='source_reading_draft')
    data['cases']=[old for old in data['cases'] if old['company']!=r['company']]+[r]
path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

path=ROOT/'data/peer-studies.json';data=json.loads(path.read_text())
backup=ROOT/'artifacts/local/peer-studies-before-semiconductor.json'
if not backup.exists(): backup.write_bytes(path.read_bytes())
sides=[]
for cid,reading in [
    ('AMAT','9개월 첨단 로직·파운드리와 DRAM 전환 투자가 장비 수요를 뒷받침했다. AGS는 서비스 계약과 부품 매출이 함께 늘었으며 전부 구독 매출은 아니다. 장비 마진에는 수출통제 준수 합의 비용이 반영됐다.'),
    ('LRCX','연간 고객지원 성장은 부품과 구형 공정용 장비가 기여했다. 장비·업그레이드의 파운드리 비중 상승에는 성숙·첨단 공정이 함께 기여했다. 메모리 비중 하락을 절대 매출 감소로 읽지 않는다.')]:
    c=companies[cid];case=next(r for r in cases if r['company']==cid)
    sides.append(dict(company=cid,name=c['name'],market=c['market'],accession=case['accession'],corpusHash=case['corpusHash'],passageIds=case['passageIds'],reading=reading))
study=dict(id='semiconductor-equipment',title='장비·서비스 매출의 범위와 투자 주기를 비교한다',shared='반도체 고객의 공정 전환과 설비 가동에 노출되지만 상품·서비스 범위가 다르다.',sides=sides,
    tradeoff='Applied의 9개월과 Lam의 연간은 기간이 다르다. 양쪽 모두 설치 기반에서 반복 수요를 얻지만, 부품·장비·기간 서비스의 구성은 같지 않다. 서비스라는 명칭만으로 반복 매출 비중이나 적정 배수의 우열을 정할 수 없다.',
    countercase='첨단 공정 전환과 복잡성 증가는 장비뿐 아니라 서비스·부품 수요도 강화할 수 있다. 고객지원 내 장비 매출이 있다는 이유만으로 설치 기반의 경제적 가치를 제거하지 않는다.',
    discriminator='기간을 맞춘 신규 장비·업그레이드·부품·장기 서비스 매출과 마진, 설치 기반·가동률, 고객 선급금 및 인도 추이를 확인한다. 같은 고객 투자가 양쪽 주문에 반영되는 공정별 경로와 수출 제한을 대조한다.',
    priceImplication='성장·현금 지속성을 신규 장비와 설치 기반 지원으로 분리하되 장비가 포함된 고객지원의 경기 민감도를 유지한다. 합의 비용·관세·연구개발과 선급금 효과는 각각의 회사 현금 가정에 반영해야 한다.',
    authorship='개발 중 원문 대조로 작성한 비교 연구 초안',preference='상대 선호 미확정')
data['studies']=[r for r in data['studies'] if r['id']!=study['id']]+[study]
path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print('Business readings: 17; source pairs: 8; new financial approval: none')
