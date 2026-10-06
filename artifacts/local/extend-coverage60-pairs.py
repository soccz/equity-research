import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
auth = {c['company']: c for c in json.loads((root/'data/business-insights.json').read_text())['cases']}
universe = json.loads((root/'data/coverage-universe.json').read_text()) if (root/'data/coverage-universe.json').exists() else None
from equitylab.pipeline import load_latest
companies = {c['id']: c for c in load_latest()['companies']}
rows = [
('retail-repeat','회원 수익·광고와 상품 판매 현금을 구별한다','COST','WMT',
 '소비자의 반복 구매와 대규모 유통·재고 운영에 노출된다.',
 'Costco의 회원 갱신은 과거 만료 코호트와 시차가 있고, Walmart의 기존점·거래·전자상거래 기여는 사업 범위가 다르다. 주유 가격의 매출 분모 효과와 관세 환급을 나누어야 반복 마진을 비교할 수 있다.',
 '같은 기간·지역의 거래·객단가, 연료 제외 기존점, 회원 수익·광고 이익, 관세 환급과 재고·매입채무 현금을 대조한다.',
 '상품·회원·광고의 이익 기여와 매장 배송·설비·재고 부담을 구분한다. 과거 갱신율과 현금의 증가율을 미래 매출·마진 하나로 바꾸지 않는다.',
 '회원 기반과 광고·배송의 결합이 가격 경쟁 속에서도 반복 수익을 지지할 수 있다. 낮은 상품 마진만으로 양쪽의 주주 현금을 판단하지 않는다.'),
('software-contracts','ARR·RPO를 같은 성장 지표로 읽지 않는다','CRM','ADBE',
 '기업·전문가 소프트웨어의 구독과 AI 기능 수익화에 노출된다.',
 'Salesforce의 계약 잔액과 Adobe의 연환산 ARR는 정의·계약기간·인수 범위가 다르다. 양쪽의 AI 제공 원가와 갱신·사용량을 확인하기 전 지표 성장률만으로 선호를 정할 수 없다.',
 '같은 사업 범위의 기간 매출·현금 수금, 인수 제외 계약·ARR, 갱신·사용량과 호스팅·추론 원가를 대조한다.',
 'AI 매출 가정과 서비스 원가·판매수수료·주식보상·인수 상각을 함께 조정한다. 계약 잔액 전액이나 ARR를 해당 연도의 현금으로 넣지 않는다.',
 '기존 제품과 AI의 결합이 고객 유지와 확장 판매를 강화할 수 있다. 초기 원가 증가가 영구적인 마진 악화를 의미하지는 않는다.'),
('enterprise-delivery','소프트웨어 구독과 구축·운영·인프라를 나눈다','NOW','018260',
 '기업 업무의 디지털화와 AI 도입 지출을 서로 다른 방식으로 수익화한다.',
 'ServiceNow의 구독에도 선인식 self-hosted 라이선스가 있고 삼성SDS는 IT 구축·운영·직접 인프라·물류가 섞여 있다. 삼성SDS 연결 성장과 ServiceNow 구독 성장을 같은 SaaS 수요로 비교하기 어렵다.',
 '기업 업무 서비스의 동일 고객·매출 범위, 계약 인식·수취, 사용량 원가와 소유 인프라·인수 현금, 관계회사 거래를 구분해 확보한다.',
 '구독 라이선스와 구축·운영·물류를 따로 계산하고, 인수·데이터센터·GPU 및 선행 투자를 반영한다. 미국 소프트웨어 배수를 한국 연결 전체에 바로 적용하지 않는다.',
 '직접 인프라와 구축 역량이 고객 요구를 충족하는 강점일 수 있고 구독 모델은 반복성을 제공할 수 있다. 어느 방식이 더 적은 자본으로 현금을 내는지는 계약과 투자 후 현금으로 확인한다.'),
('telecom-cash','성숙 통신의 성장 사업과 금융 현금을 분리한다','017670','030200',
 '국내 이동·유선통신과 기업 통신·데이터센터의 수요에 노출된다.',
 'SK텔레콤의 미디어·기업 통신과 KT의 카드·대출·부동산을 연결 비율 하나로 비교할 수 없다. 신규 요금제와 데이터센터 투자도 해당 공시 기간에 실현한 수익과 구별한다.',
 '통신 범위의 가입자당 수익·해지·기업 매출, 망·주파수·리스·데이터센터 현금을 맞추고 금융 자회사 자본·대출과 투자부동산을 별도 대사한다.',
 '안정 통신의 반복 현금과 신규 가동의 투자 회수를 나눈다. KT의 카드·대출 현금 분리가 끝나기 전 연결 전체로 주당 가격 우열을 계산하지 않는다.',
 '신규 기업 통신·데이터센터가 성숙 통신의 성장 제약을 완충할 수 있다. 투자 부담이 크다는 사실만으로 계획의 경제적 가치가 없다고 보지 않는다.'),
('camera-substrates','카메라·기판 노출과 고객 집중을 비교한다','009150','011070',
 '고사양 카메라와 반도체 패키지 기판 수요에 공통 노출이 있다.',
 '삼성전기에는 MLCC, LG이노텍에는 모빌리티가 포함되며 고객 집중과 제품 구성이 다르다. 평균가격·연결 성장 차이를 동일 카메라 단가나 시장 점유율의 변화로 읽지 않는다.',
 '동일 제품·고객군·기간의 출하·제품 구성·가격과 수율·가동, 신규 기판 고객·투자 및 현금 회수를 확보한다.',
 '카메라·기판의 마진과 증설을 나누고, 다른 부품·모빌리티 및 중단영업·우선주 권리를 보존한다. 계획 단계의 AI 기판 물량을 확정 매출로 넣지 않는다.',
 '고객 집중이 규모·설계 관계의 강점일 수 있고 다변화에는 선행 투자가 들 수 있다. 고객 수만으로 현금 안정성을 정하지 않는다.'),
('game-platforms','게임·광고 구성과 플랫폼 분류 변경을 구별한다','259960','251270',
 '게임 IP의 출시·운영과 사용자 과금으로 수익을 창출한다.',
 '크래프톤에는 광고 사업이 있고 넷마블은 당반기 상품 분류를 바꿨다. 반기와 전년 연간 플랫폼 비중 또는 초기 신작 판매만으로 지속 성과를 순위화할 수 없다.',
 '동일 분류의 전년 반기 게임별 순매출·유저·과금·스토어 비용과 개발·마케팅 현금, 광고 사업의 이익·인수 범위를 대조한다.',
 '기존 IP의 반복 현금과 신작의 출시·유지 비용, 광고·인수 부담을 나눈다. AI 효율 계획을 입증된 절감액으로 추가하지 않는다.',
 '신작·플랫폼과 광고의 다변화가 개별 IP 수명 위험을 줄일 수 있다. 분류의 제약은 성장이나 투자 성과가 없다는 증거가 아니다.'),
('analog-manufacturing','아날로그 회복과 제조 증설·지원 현금을 비교한다','TXN','ADI',
 '산업·자동차·통신 등의 아날로그 반도체 수요와 제조 가동률에 노출된다.',
 'TXN의 생산능력 확장·정부 지원과 ADI의 제품 구성·가동·인수는 이익과 현금을 다르게 움직인다. 연구개발 비용률 하락도 비용 금액 감소와 구별한다.',
 '같은 최종시장·기간의 매출·가동·제품 마진, 총 설비 지급·인센티브·현금 세액공제와 인수·영업자금을 구분한다.',
 '고정비 흡수와 신규 공장 비용, 총 투자 및 지원 수취를 따로 가정한다. 지원 후 현금의 상승을 지원 없는 장기 정상 마진으로 바꾸지 않는다.',
 '선행 증설이 장기 원가·공급 안정에 도움이 될 수 있고 제품 구성 개선이 높은 마진을 지지할 수 있다. 현재 투자 크기만으로 장기 상대 매력을 확정하지 않는다.'),
('memory-price-volume','가격·출하와 투자 이후 현금을 같은 기간으로 본다','MU','000660',
 'DRAM·NAND 수요와 고부가 메모리 제품·공정 투자에 노출된다.',
 'Micron 누적 전년 대비와 SK하이닉스 전분기 변화는 비교 기준이 다르다. 전체 제품과 개별 사업부의 가격·비트 출하 방향도 같지 않아 연결 성장으로 HBM 우열을 판단할 수 없다.',
 '공통 달력 기간에 맞춘 DRAM·NAND 가격·비트 출하·HBM 구성, 현금 설비·리스·패키징 투자와 실제 채권 회수를 대조한다.',
 '가격·물량·제품 구성과 공정·공급 확대를 별도 경로로 둔다. 현재 높은 마진을 고정한 가격 역산은 가정임을 표시하고 공급 증가·가격 안정 상황을 함께 계산한다.',
 '고부가 메모리와 공급 제약이 높은 현금을 오래 지지할 수 있다. 과거 사이클 평균만으로 제품 변화의 효과를 전부 없애지 않는다.'),
]
path=root/'data/peer-studies.json';obj=json.loads(path.read_text())
backup=root/'artifacts/local/coverage60-before-peer-studies.json'
if not backup.exists():backup.write_bytes(path.read_bytes())
for id,title,left,right,shared,tradeoff,discriminator,priceImplication,countercase in rows:
    sides=[]
    for symbol in [left,right]:
        a=auth[symbol];c=companies[symbol]
        sides.append(dict(company=symbol,name=c['name'],market=c['market'],accession=a['accession'],corpusHash=a['corpusHash'],passageIds=a['passageIds'],reading=a['observation']))
    row=dict(id=id,title=title,shared=shared,sides=sides,tradeoff=tradeoff,discriminator=discriminator,priceImplication=priceImplication,countercase=countercase,authorship='개발 중 원문 대조로 작성한 비교 연구 초안',preference='상대 선호 미확정')
    obj['studies']=[x for x in obj['studies'] if x['id']!=id]+[row]
path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
print('Source paired studies',len(obj['studies']))
