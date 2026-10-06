from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parents[3]
STAGE = Path(__file__).resolve().parent
if (ROOT / "equitylab/orion_operating.py").exists():
    raise RuntimeError("Do not repeat Orion integration")
pending = {}


def edit(name, old, new):
    p = ROOT / name
    s = pending.get(p, p.read_text())
    if s.count(old) != 1:
        raise ValueError(f"Ambiguous anchor {name}: {old[:70]}")
    pending[p] = s.replace(old, new)


edit("equitylab/operating_model.py", "def build(c, as_of):\n", 'def build(c, as_of):\n    if c["id"] == "271560":\n        from .orion_operating import build as orion\n\n        return orion(c, as_of)\n')
edit("app/operating-model.js", "  function analogEvidence(m){", (STAGE / "orion-renderer.js").read_text() + "  function analogEvidence(m){")
edit("app/operating-model.js", "${analogEvidence(m)}", "${analogEvidence(m)}${confectioneryEvidence(m)}")
p = ROOT / "app/styles.css"
pending[p] = p.read_text() + "\n.operating-confectionery-evidence{margin:24px 0}.confectionery-chart-scroll{overflow-x:auto}.confectionery-chart-scroll svg{display:block;width:100%;min-width:780px}.operating-confectionery-evidence h3,.operating-confectionery-evidence h4{break-after:avoid}@media print{.confectionery-chart-scroll{overflow:visible}.confectionery-chart-scroll svg{min-width:0}.confectionery-geography-group,.confectionery-acquisition-scope,.confectionery-investment-group{break-inside:avoid}}\n"
browser = '''    await go('company/271560');
    await expect('Orion geographic sales use matched half years without independent margins', 'document.querySelectorAll(".confectionery-market-chart g[data-current]").length===3 && [...document.querySelectorAll(".confectionery-market-chart g[data-current]")].reduce((s,e)=>s+Number(e.dataset.current),0)===1823941014000 && document.querySelector(".confectionery-geography-group").textContent.includes("134원")');
    await expect('Orion retains acquisition arithmetic, July capital and price hold', 'document.querySelector(".confectionery-acquisition-scope").textContent.includes("-174,000") && document.querySelector(".confectionery-investments").textContent.includes("2026-07-24") && document.querySelector(".confectionery-post-balance").textContent.includes("주당·역산은 보류") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="271560").operatingModel.initial.price===null');
    const orionBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),orionBefore);checks.push('Orion independent reinvestment assumption recomputes cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Orion restores cash assumption and keeps source-bound price hold', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.12 && document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector("#operating-result").textContent.includes("보류") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="271560").operatingModel.bridge.reportedCfo===667317383300');
    await js('localStorage.removeItem("equity-operating-path-v1-271560")');await click('#operating-reset');
    await viewport(390);await expect('Orion country chart scrolls within mobile width', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".confectionery-chart-scroll").scrollWidth>document.querySelector(".confectionery-chart-scroll").clientWidth');await screenshotRegion('mobile-orion-operating.png','.operating-confectionery-evidence');await viewport(1440);
    await screenshotRegion('desktop-orion-operating.png','.operating-confectionery-evidence');await pdf('orion.pdf');
'''
edit("scripts/check-live.mjs", "    await go('company/ADI');", browser + "    await go('company/ADI');")
for prefix in ["\n    ", "\n        "]:
    edit("scripts/check-artifacts.py", prefix + '"analog-devices",\n', prefix + '"orion",' + prefix + '"analog-devices",\n')
check = '''    if name == "orion":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["같은반기의지역매출과연결이익을구분", "134원", "272원", "-174,000", "인수현금174,000원", "2026-07-24", "전환우선주", "전환사채", "주당·역산은보류", "0.685"]:
            if term not in all_text:
                raise ValueError("Orion business/capital scope missing: " + term)
'''
edit("scripts/check-artifacts.py", '    if name == "analog-devices":', check + '    if name == "analog-devices":')
for name in ["README.md", "docs/product-design.md", "docs/local-runtime.md"]:
    p = ROOT / name
    pending[p] = p.read_text().replace("모델29개", "모델30개").replace("모델은 29개", "모델은 30개")
note = "오리온은 30번째 현금 모델이다. 연결 제과 이익·세 기간 현금을 대사하며, 같은 반기 지역별 외부 매출을 내부거래 포함 법인 합계와 구분한다. 연간 사업결합 순지급과 반기 총취득대가의 차이를 인수 현금으로 대사하고, 같은 총대가 기준 최근1년 취득과 연간 비율을 쓰는 미래 가정을 구분한다. 관계·공동기업 장부금액과 지분법 손익·수취 배당, 결산 후 리가켐 전환우선주·전환사채 취득을 분리한다. 자금·자산 배분 대사 전 전체 주당·역산은 보류한다.\n\n"
edit("docs/product-design.md", "## 전체 목표와 남은 실질 산출물", note + "## 전체 목표와 남은 실질 산출물")
p = ROOT / "data/business-insights.json"
d = json.loads(p.read_text())
case = next(c for c in d["cases"] if c["company"] == "271560")
case["passageIds"] += ["7052f6237b08df04c00e", "e248b3acb06314f6bc59", "a63e94da9604c64a48f2", "d971f057969240f00c88", "05fc56cd07bf337633f7", "a043b6896b068f667fba"]
case["priceImplication"] += " 연결 제과의 영업현금과 바이오 투자 자금은 나누어 본다. 결산 후 전환우선주·전환사채 취득을 과거 반기 현금이나 미래 반복 지출로 중복 반영하지 않으며, 관계기업 장부금액을 순투자 가치로 바로 더하지 않는다."
case["changeCondition"] += " 바이오 취득 후 현금·투자 권리와 비지배 귀속, 본사 이전 리스 지급 및 인수 지출의 기간 범위도 대사한다."
pending[p] = json.dumps(d, ensure_ascii=False, indent=2) + "\n"
copies = [(STAGE / "orion_operating.py", ROOT / "equitylab/orion_operating.py"), (STAGE / "test_orion_operating.py", ROOT / "tests/test_orion_operating.py")]
copies += [(p, ROOT / "data/sources" / p.name) for p in (STAGE / "data/sources").glob("dart-document-20260318001320*")]
for source, dest in copies:
    if dest.exists() and source.read_bytes() != dest.read_bytes():
        raise ValueError("Source conflict " + str(dest))
for source, dest in copies:
    shutil.copy2(source, dest)
for p, text in pending.items():
    p.write_text(text)
print("Integrated Orion30. Full calculation, local records, replay, browser and PDF verification still required.")
