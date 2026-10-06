"""One business margin at a time, against the selected cash-path market proxy."""

import copy
import math
from .operating_model import calculate

VERSION = 'single-segment-margin-inverse-v1'


def margins(model, assumptions):
    # Validate the entire scenario before using it as a baseline for inversion.
    calculate(model, assumptions)
    market = model['security'].get('marketCapProxy')
    eligible = model['security'].get('status') == 'available' and isinstance(market, (int, float)) and math.isfinite(market) and market > 0
    rows = []
    for i, segment in enumerate(model['segments']):
        low = segment.get('minMargin', -.5)
        high = 1. if model.get('grossProfitPath') else .9
        row = dict(segment=segment['id'], label=segment['label'], lower=low, upper=high,
                   currentAssumption=assumptions['segments'][i]['marginEnd'],
                   requiredMargin=None, change=None, relativeMarketResidual=None,
                   terminalCash=None, status='security_unresolved')
        if not eligible:
            rows.append(row)
            continue

        def evaluate(value):
            a = copy.deepcopy(assumptions)
            a['segments'][i]['marginEnd'] = value
            r = calculate(model, a)
            # Signed extension is used only to locate a root, never shown as a
            # price when terminal cash is nonpositive. Recheck eligibility below.
            signed = r['explicitPv'] + r['terminal']['cash'] / (a['discount']-a['terminal']) / (1+a['discount'])**5
            return signed-market, r

        fl, left = evaluate(low)
        fh, right = evaluate(high)
        tolerance = max(1., market * 1e-10)
        if abs(fh-fl) <= tolerance:
            row['status'] = 'no_margin_identification'
        elif fh < fl:
            row['status'] = 'nonmonotone_review'
        elif fl > tolerance:
            row['status'] = 'below_supported_range'
        elif fh < -tolerance:
            row['status'] = 'above_supported_range'
        else:
            lo, hi = low, high
            for _ in range(70):
                mid = (lo+hi)/2
                fm, r = evaluate(mid)
                if fm < 0: lo = mid
                else: hi = mid
            margin = (lo+hi)/2
            residual, result = evaluate(margin)
            if result['terminal']['cash'] <= 0 or result['equityValue'] is None:
                row['status'] = 'nonpositive_terminal'
            elif abs(residual) > tolerance:
                row['status'] = 'residual_review'
            else:
                row.update(status='solved', requiredMargin=margin,
                           change=margin-row['currentAssumption'],
                           relativeMarketResidual=residual/market, terminalCash=result['terminal']['cash'])
        rows.append(row)
    return dict(version=VERSION, rows=rows,
                scope='다른 선택 가정을 고정하고 각 사업부의 5년차 마진만 하나씩 바꾼 별도 역산이다. 행들을 동시에 적용하지 않는다. 본업 현금 경로 밖의 자산·계약 손실과 정상화 공백은 별도이며 실제 마진 전망·컨센서스·목표가가 아니다.')
