from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[3];STAGE=Path(__file__).resolve().parent
assert json.loads((ROOT/'artifacts/local/runs/20261002T043944903765Z/run.json').read_text())['status']=='artifacts_verified'
p=ROOT/'scripts/check-live.mjs';s=p.read_text();assert 'await pdf(\'oracle.pdf\');' in s;s=s.replace("    await pdf('oracle.pdf');",(STAGE/'browser-checks.txt').read_text()+"    await pdf('oracle.pdf');",1)
s=s.replace("    await go('compare/retail-repeat');",(STAGE/'pair-checks.txt').read_text()+"    await go('compare/retail-repeat');",1);p.write_text(s)
p=ROOT/'scripts/check-artifacts.py';s=p.read_text().replace('    "comparison-enterprise",','    "comparison-enterprise",\n    "comparison-infrastructure",',1)
anchor='    if name == "netflix":';assert anchor in s
addition='''    if name == "oracle":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["고객의선급금융과설비자금소요", "11.363", "11.740", "75.660", "0.552", "0.357", "0.195", "288.000", "200%", "원금대용", "미배분비용"]:
            if term not in all_text:
                raise ValueError("Oracle financing evidence missing: " + term)
    if name == "comparison-infrastructure":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["정부소유", "우선주", "전환사채", "150%", "선택한사업가정"]:
            if term not in all_text:
                raise ValueError("Infrastructure comparison evidence missing: " + term)
'''
s=s.replace(anchor,addition+anchor,1);p.write_text(s)
