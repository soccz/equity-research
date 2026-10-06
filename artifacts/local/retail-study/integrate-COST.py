from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
STAGE = Path(__file__).resolve().parent
if (ROOT / "equitylab/costco_operating.py").exists():
    raise RuntimeError("Do not repeat Costco integration")
pending = {}


def edit(name, old, new):
    p = ROOT / name
    text = pending.get(p, p.read_text())
    if text.count(old) != 1:
        raise ValueError(f"Ambiguous anchor {name}: {old[:60]}")
    pending[p] = text.replace(old, new)


edit("equitylab/operating_model.py", "def build(c, as_of):\n", 'def build(c, as_of):\n    if c["id"] == "COST":\n        from .costco_operating import build as costco\n\n        return costco(c, as_of)\n')
edit("app/operating-model.js", "  function confectioneryEvidence(m){", (STAGE / "costco-renderer.js").read_text() + "  function confectioneryEvidence(m){")
edit("app/operating-model.js", "${confectioneryEvidence(m)}", "${confectioneryEvidence(m)}${warehouseEvidence(m)}")
p = ROOT / "app/styles.css"
pending[p] = p.read_text() + "\n.operating-warehouse-evidence{margin:24px 0}.warehouse-chart-scroll{overflow-x:auto}.warehouse-chart-scroll svg{display:block;width:100%;min-width:760px}.operating-warehouse-evidence h3,.operating-warehouse-evidence h4{break-after:avoid}@media print{.warehouse-chart-scroll{overflow:visible}.warehouse-chart-scroll svg{min-width:0}.warehouse-membership-group,.warehouse-renewal-group,.warehouse-lease-group{break-inside:avoid}}\n"
browser = '''    await go('company/COST');
    await expect('Costco membership stays in real segments and uses matched 36-week periods', 'document.querySelectorAll(".warehouse-membership-chart g[data-membership]").length===2 && Number(document.querySelector(".warehouse-membership-chart g").dataset.membership)===4057000000 && document.querySelector(".warehouse-fees").textContent.includes("2025-05-11")');
    await expect('Costco historical renewal and lease proxies remain explicit', 'document.querySelector(".warehouse-renewal-group").textContent.includes("7~18개월") && document.querySelector(".warehouse-working").textContent.includes("-2.352") && document.querySelector(".warehouse-lease-group").textContent.includes("자료 미확인")');
    const costcoBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=3;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),costcoBefore);checks.push('Costco warehouse reinvestment changes the business cash path');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Costco restores assumptions without changing observed membership revenue', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.03 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="COST").operatingModel.retailEvidence.membership.value===5781000000');
    await js('localStorage.removeItem("equity-operating-path-v1-COST")');await click('#operating-reset');
    await viewport(390);await expect('Costco source chart remains usable on mobile', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".warehouse-chart-scroll").scrollWidth>document.querySelector(".warehouse-chart-scroll").clientWidth');await screenshotRegion('mobile-costco-operating.png','.operating-warehouse-evidence');await viewport(1440);
    await screenshotRegion('desktop-costco-operating.png','.operating-warehouse-evidence');await pdf('costco.pdf');
'''
edit("scripts/check-live.mjs", "    await go('company/271560');", browser + "    await go('company/271560');")
for prefix in ["\n    ", "\n        "]:
    edit("scripts/check-artifacts.py", prefix + '"orion",\n', prefix + '"costco",' + prefix + '"orion",\n')
check = '''    if name == "costco":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["회원비는이미사업손익에포함된기간수익", "7~18개월", "-2.352", "3.157", "금융리스", "자료미확인", "재보험", "0.102"]:
            if term not in all_text:
                raise ValueError("Costco membership/lease scope missing: " + term)
'''
edit("scripts/check-artifacts.py", '    if name == "orion":', check + '    if name == "orion":')
for name in ["README.md", "docs/product-design.md", "docs/local-runtime.md"]:
    p = ROOT / name
    pending[p] = p.read_text().replace("모델30개", "모델31개").replace("모델은 30개", "모델은 31개")
note = "Costco는 31번째 현금 모델이다. 미국·캐나다·기타 국제의 손익과 회원비 포함 매출, 연간52주·동기36주의 현금을 대사한다. 회원비를 무비용 이익으로 다시 더하지 않고, 과거 갱신 창과 미래 확률을 구분한다. 혼합 수취채권·재고·매입채무·이연 회원비의 자금 대용을 표시한다. 마지막 연간 금융리스 상각의 미래 대용과 최근52주 실제 금액 미확인, 영업리스 비용·지급 시차를 보존한다.\n\n"
edit("docs/product-design.md", "## 전체 목표와 남은 실질 산출물", note + "## 전체 목표와 남은 실질 산출물")
copies = [(STAGE / "costco_operating.py", ROOT / "equitylab/costco_operating.py"), (STAGE / "test_costco_operating.py", ROOT / "tests/test_costco_operating.py")]
copies += [(p, ROOT / "data/sources" / p.name) for p in (STAGE / "data/sources").glob("filing-0000909832-25-000101*")]
for src, dst in copies:
    if dst.exists() and src.read_bytes() != dst.read_bytes():
        raise ValueError("Source conflict " + str(dst))
for src, dst in copies:
    shutil.copy2(src, dst)
for p, text in pending.items():
    p.write_text(text)
print("Integrated Costco31; full analysis and current PDF verification remain required.")
