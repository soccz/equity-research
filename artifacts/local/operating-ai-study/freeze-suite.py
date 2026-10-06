from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parent
cases=[]
def add(ident,role,text,expected,accept,split):
 cases.append(dict(id=ident,company=ident.split('_')[0],role=role,text=text,expected=expected,accept=accept,split=split))
add('TXN_credit_in_cfo','observation','제시된 영업현금에는 투자세액공제가 줄인 납부 세금의 효과가 이미 포함돼 있다.','supported',True,'development')
add('TXN_double_count','observation','영업현금에 세금 감소와 투자활동 지원금의 합계를 더하면 혜택을 중복 없이 반영한다.','contradicted',False,'development')
add('ADI_market_profit','observation','산업과 자동차 시장의 공시 영업이익률을 독립적으로 비교할 수 있다.','contradicted',False,'development')
add('ADI_market_gap','missing','입력에서는 최종시장별 독립 영업이익률을 확인할 수 없다.','supported',True,'development')
add('ADBE_positive_release','observation','현금 경로가 양수이므로 취득 지출의 기간 범위 대사 없이 주당 가치를 확정할 수 있다.','contradicted',False,'development')
add('ADBE_contract_gap','missing','입력에서는 현재 계약 취득비 상각과 현금 지급의 상세 대사를 확인할 수 없다.','supported',True,'development')
add('CRM_lease_label','observation','현금표의 금융의무 원금 전액은 이미 금융리스 원금으로 확인됐다.','contradicted',False,'development')
add('CRM_scope_gap','missing','입력에서는 넓은 금융의무 지급과 금융리스 주석의 차이를 모두 설명하는 세부 계약을 확인할 수 없다.','supported',True,'development')
add('TXN_forecast_fact','observation','미래 신규 지원금이 전혀 없다는 사실이 현재 공시로 확정됐다.','contradicted',False,'separate_examples')
add('TXN_capacity_test','distinguish','향후 공장별 가동률과 주문 이력을 확보해 주문 증가에 따른 가동 개선이면 수요 회복 설명을, 주문 변화 없이 가동이 개선되면 생산 배치 조정 설명을 각각 지지할 수 있다.','conditional',True,'separate_examples')
add('ADI_purchase_free','observation','인수 지출을 가정에서 제외하면 동일한 기술과 매출 성장을 유지할 수 있다는 사실이 입증된다.','unsupported',False,'separate_examples')
add('ADI_wc_aggregate','observation','누적기간의 영업자산·부채 현금 변화는 제공된 합계로 남기며 개별 채권 효과로 임의 배분하지 않는다.','supported',True,'separate_examples')
add('ADBE_arithmetic_return','observation','취득액의 기간 연결에서 음수가 나왔으므로 실제 투자 회수 현금이 확인됐다.','contradicted',False,'separate_examples')
add('ADBE_source_test','distinguish','추가 자산 취득 내역과 재분류 주석을 확보해 같은 자산의 지급 감소가 확인되면 투자 축소 설명을, 자산 범주 이동이 확인되면 표시 범위 변경 설명을 각각 지지할 수 있다.','conditional',True,'separate_examples')
add('CRM_assumed_cause','hypothesis','확인된 고객 선급금 증가의 유일한 원인은 계약 협상력 개선일 수 있다.','unsupported',False,'separate_examples')
add('CRM_cash_held','observation','초기 현금 가정을 바꾸어도 금융의무 범위가 미대사인 동안 모델의 주당 계산 보류는 유지된다.','supported',True,'separate_examples')
r=dict(version='operating-assumptions-cases-v1',scope='실행 전 고정한 작성자 개발8개·별도 예문8개. 독립 금융 검토나 기업/미사용 표본 정확도 평가가 아니다. 결과를 보고 예문·규칙을 바꾸면 새버전으로 보존한다.',gate=dict(maxFalseAccepts=0,maxFalseRejects=1,maxInvalidResponses=0),cases=cases)
p=ROOT/'suite.json'
if p.exists():raise RuntimeError('Do not overwrite frozen evaluation')
p.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(hashlib.sha256(p.read_bytes()).hexdigest())
