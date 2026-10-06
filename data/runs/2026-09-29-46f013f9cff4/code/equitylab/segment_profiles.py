"""Explicit filing contexts for operating segments and product disclosures."""

from .xbrl import select

CONSOLIDATED = ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")
US_SEGMENTS = ("ConsolidationItemsAxis", "OperatingSegmentsMember")
CORPORATE = [("ConsolidationItemsAxis", "CorporateNonSegmentMember")]
KR_SEGMENTS = ("SegmentConsolidationItemsAxis", "OperatingSegmentsMember")
KR_ADJUST = [
    CONSOLIDATED,
    ("SegmentConsolidationItemsAxis", "MaterialReconcilingItemsMember"),
]
REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"

PROFILES = {
    "NVDA": dict(
        title="계산·네트워킹과 그래픽스",
        revenueTag="Revenues",
        axis="StatementBusinessSegmentsAxis",
        segments=[
            ("ComputeAndNetworkingSegmentMember", "컴퓨트·네트워킹"),
            ("GraphicsSegmentMember", "그래픽스"),
        ],
        revenueExtra=[US_SEGMENTS],
        incomeExtra=[US_SEGMENTS],
        incomeAdjustments=[
            ("AllocatedShareBasedCompensationExpense", CORPORATE, -1),
            (
                "UnallocatedCorporateOperatingExpendituresAndOtherExpenses",
                CORPORATE,
                -1,
            ),
            ("AcquisitionRelatedAndOtherCosts", CORPORATE, -1),
        ],
        products=[
            ("DataCenterMember", "데이터센터"),
            ("EdgeComputingMember", "엣지 컴퓨팅"),
        ],
        productTag="Revenues",
        findings=[
            "보고 부문은 컴퓨트·네트워킹과 그래픽스이며 데이터센터 매출 분류와 같은 축이 아니다.",
            "부문 이익에서 공통 주식보상·미배분 비용·인수 관련 비용을 차감해 연결 영업이익과 대사한다.",
        ],
        remaining=[
            "데이터센터 매출의 가격·물량·제품 세대별 기여",
            "고객 집중·구매약정·재고와 지속 가능한 수요의 연결",
            "지분투자 손익·주식보상·자기주식 매입을 구분한 정상 주주 현금",
        ],
    ),
    "AAPL": dict(
        title="지역별 이익과 제품·서비스 매출",
        revenueTag=REVENUE,
        axis="StatementBusinessSegmentsAxis",
        segments=[
            ("AmericasSegmentMember", "미주"),
            ("EuropeSegmentMember", "유럽"),
            ("GreaterChinaSegmentMember", "중화권"),
            ("JapanSegmentMember", "일본"),
            ("RestOfAsiaPacificSegmentMember", "아시아태평양 기타"),
        ],
        revenueExtra=[US_SEGMENTS],
        incomeExtra=[US_SEGMENTS],
        incomeAdjustments=[("OperatingIncomeLoss", CORPORATE, 1)],
        products=[
            ("IPhoneMember", "iPhone"),
            ("MacMember", "Mac"),
            ("IPadMember", "iPad"),
            ("WearablesHomeandAccessoriesMember", "웨어러블·홈·액세서리"),
            ("ServiceMember", "서비스"),
        ],
        productTag=REVENUE,
        findings=[
            "지역별 영업이익에는 본사 비용이 모두 배분되지 않았다. 공시 본사 조정 후 연결 이익과 대사한다.",
            "제품·서비스 매출과 지역 영업이익을 별도 표로 읽는다. 지역 이익률을 iPhone이나 서비스의 이익률로 바꾸지 않는다.",
        ],
        remaining=[
            "서비스 매출 구성과 기기 설치기반·가격 효과",
            "중화권 매출 변화의 물량·가격·환율과 경쟁 요인 분리",
            "매입 주식·주식보상·부채 상환을 반영한 지속 가능 주주 배분",
        ],
    ),
    "GOOGL": dict(
        title="광고·구독과 클라우드의 다른 투자 구조",
        revenueTag=REVENUE,
        axis="StatementBusinessSegmentsAxis",
        segments=[
            ("GoogleServicesMember", "Google Services"),
            ("GoogleCloudMember", "Google Cloud"),
            ("AllOtherSegmentsMember", "Other Bets"),
        ],
        revenueExtra=[],
        incomeExtra=[US_SEGMENTS],
        revenueAdjustments=[("RevenueNotFromContractWithCustomer", [], 1)],
        incomeAdjustments=[("OperatingIncomeLoss", CORPORATE, 1)],
        findings=[
            "서비스·클라우드·Other Bets 합계에 공시 매출 조정과 본사 영업이익 조정을 각각 반영한다.",
            "클라우드 부문 이익은 연결 현금흐름이 아니다. 공유 설비와 AI 투자 비용의 배분을 추가 확인해야 한다.",
        ],
        remaining=[
            "광고·구독과 클라우드의 설비투자·공유 비용 배분",
            "투자자산 평가손익과 반복 영업현금의 구별",
            "A·B·C 주식 및 우선주·비지배 권리를 반영한 증권별 가치",
        ],
    ),
    "005930": dict(
        title="DS·DX·디스플레이·Harman",
        revenueTag="Revenue",
        axis="SegmentsAxis",
        segments=[
            (
                "DsSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "DS",
            ),
            (
                "DxSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "DX",
            ),
            (
                "SdcMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "SDC",
            ),
            (
                "HamanMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "Harman",
            ),
        ],
        revenueExtra=[CONSOLIDATED, KR_SEGMENTS],
        incomeExtra=[CONSOLIDATED, KR_SEGMENTS],
        revenueAdjustments=[("Revenue", KR_ADJUST, 1)],
        incomeAdjustments=[("OperatingIncomeLoss", KR_ADJUST, 1)],
        grossRevenue=True,
        findings=[
            "부문 매출은 내부거래를 포함한 공시 기준이며 연결 조정과 함께 표시한다. 외부 매출 비중으로 해석하지 않는다.",
            "DS 전체에는 메모리 외 사업도 포함된다. DS 이익률을 메모리 또는 HBM 이익률로 사용하지 않는다.",
            "부문 이익 합계와 연결 영업이익의 남은 차이는 별도로 공개한다. 공시 조정으로 설명되지 않은 잔액의 원인은 확정하지 않는다.",
        ],
        remaining=[
            "DS 내 메모리·파운드리·시스템LSI의 매출·투자 구분",
            "부문 이익과 연결 이익의 미대사 차이 구성",
            "보통주·우선주·자기주식과 비지배지분의 권리별 배분",
        ],
    ),
    "066570": dict(
        title="가전·미디어·전장·공조·이노텍",
        revenueTag="Revenue",
        axis="SegmentsAxis",
        segments=[
            (
                "HomeApplianceSolutionOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "가전",
            ),
            (
                "MediaEntertainmentSolutionOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "미디어·엔터테인먼트",
            ),
            (
                "VehicleSolutionOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "전장",
            ),
            (
                "EcoSolutionOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "공조",
            ),
            (
                "LgInnotekAndItsSubsidiariesOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "이노텍",
            ),
            ("AllOtherSegmentsMember", "기타"),
        ],
        revenueExtra=[CONSOLIDATED],
        incomeExtra=[CONSOLIDATED],
        grossRevenue=True,
        findings=[
            "영업부문 표의 매출·이익을 같은 차원에서 선택했다. 별도 매출 표와 임의로 섞지 않는다.",
            "이노텍은 연결 대상 사업부 금액이다. 연결 이익 전체를 LG전자 보통주 소유자의 현금으로 계산하지 않는다.",
        ],
        remaining=[
            "외부 매출과 내부 매출·연결 조정의 세부 연결",
            "가전 구독·전장·공조의 운전자본·재투자 구조",
            "비지배지분과 우선주를 고려한 주주별 현금 배분",
        ],
    ),
}


# Each adapter fixes the exact disclosed axis/member and retains reconciling items.
PROFILES.update(
    {
        "AMZN": dict(
            title="북미·국제 소매와 AWS의 수익 구조",
            revenueTag=REVENUE,
            axis="StatementBusinessSegmentsAxis",
            revenueExtra=[],
            incomeExtra=[],
            segments=[
                ("NorthAmericaSegmentMember", "북미"),
                ("InternationalSegmentMember", "국제"),
                ("AmazonWebServicesSegmentMember", "AWS"),
            ],
            findings=[
                "지역 소매 두 부문과 AWS를 별도 보고 부문으로 읽는다. 부문 매출·영업이익 합계를 연결 금액과 대사한다.",
                "AWS 영업이익을 클라우드 사업의 현금흐름으로 대체하지 않는다.",
            ],
            remaining=[
                "소매·AWS별 설비 투자와 공유 인프라 배분",
                "배송·서비스 구성과 수금·정산 시점의 현금 효과",
                "장비 리스·주식보상과 장기 투자 회수 조건",
            ],
        ),
        "AMD": dict(
            title="데이터센터·클라이언트 및 게이밍·임베디드",
            revenueTag=REVENUE,
            axis="StatementBusinessSegmentsAxis",
            revenueExtra=[US_SEGMENTS],
            incomeExtra=[US_SEGMENTS],
            segments=[
                ("DataCenterMember", "데이터센터"),
                ("ClientAndGamingMember", "클라이언트·게이밍"),
                ("EmbeddedMember", "임베디드"),
            ],
            incomeAdjustments=[
                (
                    "OperatingIncomeLoss",
                    CORPORATE + [("StatementBusinessSegmentsAxis", "AllOtherMember")],
                    1,
                )
            ],
            findings=[
                "클라이언트와 게이밍은 합쳐진 보고 부문이다. 별도 제품 매출과 중복 합산하지 않는다.",
                "부문 영업이익 합계에 공시 기타·본사 항목을 더해 연결 영업이익과 대사한다.",
            ],
            remaining=[
                "데이터센터 매출의 제품·고객 구성과 공급 약정",
                "공통 비용·주식보상·인수 무형자산 상각의 반복성",
                "재고·선급금과 반도체 구매 계약이 주주 현금에 주는 부담",
            ],
        ),
        "AVGO": dict(
            title="반도체 솔루션과 인프라 소프트웨어",
            revenueTag=REVENUE,
            axis="StatementBusinessSegmentsAxis",
            revenueExtra=[],
            incomeExtra=[],
            segments=[
                ("SemiconductorSolutionsMember", "반도체 솔루션"),
                ("InfrastructureSoftwareMember", "인프라 소프트웨어"),
            ],
            findings=[
                "반도체와 소프트웨어의 보고 부문 매출을 구분한다.",
                "부문 이익 합계와 연결 영업이익의 차이는 현재 미대사다. 이를 주식보상·상각 등 특정 원인으로 단정하지 않는다.",
            ],
            remaining=[
                "부문 이익에서 연결 이익으로 이어지는 공통 비용·상각의 완전 대사",
                "소프트웨어 계약·갱신과 반도체 고객 집중의 서로 다른 현금 구조",
                "인수 지출·차입 상환·주식보상을 포함한 반복 현금",
            ],
        ),
    }
)
_KR_ELIM = [
    CONSOLIDATED,
    ("SegmentConsolidationItemsAxis", "EliminationOfIntersegmentAmountsMember"),
]
for _symbol, _title, _members, _findings, _remaining in [
    (
        "207940",
        "CDMO 매출과 내부거래 조정",
        [
            (
                "CdmoMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "CDMO",
            )
        ],
        [
            "공시된 단일 보고 부문 CDMO와 연결 내부거래 차감을 분리한다. 단일 부문을 여러 사업의 분산으로 해석하지 않는다."
        ],
        [
            "공장별 가동·생산능력·매출 인식과 수금의 연결",
            "신규 공장 투자와 고객 계약의 회수 일정",
            "계약 선수금·개발비·외화 및 자회사 범위의 반복 현금 영향",
        ],
    ),
    (
        "068270",
        "바이오·케미컬 의약품과 연결 제거",
        [
            (
                "BiopharmaceuticalProductsMemberOfSegmentsDomainOfDisclosureOfOperatingSegmentsTableOfMember",
                "바이오 의약품",
            ),
            (
                "ChemicalPharmaceuticalProductsMemberOfSegmentsDomainOfDisclosureOfOperatingSegmentsTableOfMember",
                "케미컬 의약품",
            ),
            ("AllOtherSegmentsMember", "기타"),
        ],
        [
            "보고 부문에는 내부거래가 포함되므로 부문 매출 합계를 외부 매출로 사용하지 않는다.",
            "연결 제거는 매출과 이익 각각의 공시 금액을 사용한다. 반올림 이후 잔차를 그대로 남긴다.",
        ],
        [
            "제품별 외부 판매와 유통 재고·회수 조건의 연결",
            "개발·생산·판매 범위의 내부거래와 연결 제거 효과",
            "신제품 허가·가격·물량과 연구개발·증설 부담",
        ],
    ),
    (
        "329180",
        "조선·해양·엔진과 내부거래 조정",
        [
            (
                "ShipbuildingMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "조선",
            ),
            (
                "OffshoreIndustrialPlantAndEngineeringMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "해양·플랜트",
            ),
            (
                "EngineMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "엔진",
            ),
            (
                "OtherReportableSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
                "기타",
            ),
        ],
        [
            "연결 보고 부문과 별도 재무제표의 유사한 부문 태그를 구분한다.",
            "부문 합계에 공시 내부거래 제거를 반영하고 원 단위 연결 수치와의 잔차를 유지한다.",
        ],
        [
            "공정률·예정원가 변경과 계약자산·선수금의 현금 효과",
            "선종별 수주 잔액·선가와 인도 일정",
            "엔진의 내부·외부 매출과 투자·보증 부담",
        ],
    ),
]:
    PROFILES[_symbol] = dict(
        title=_title,
        revenueTag="Revenue",
        axis="SegmentsAxis",
        revenueExtra=[CONSOLIDATED, KR_SEGMENTS],
        incomeExtra=[CONSOLIDATED, KR_SEGMENTS],
        segments=_members,
        grossRevenue=True,
        revenueAdjustments=[("Revenue", _KR_ELIM, 1)],
        incomeAdjustments=[("OperatingIncomeLoss", _KR_ELIM, 1)],
        findings=_findings,
        remaining=_remaining,
    )


def build_profile(c, rows, reconcile):
    config = PROFILES[c["id"]]
    f = c["financials"]
    segments = []
    for member, label in config["segments"]:
        p = {}
        for period, start, end in [
            ("current", f["start"], f["end"]),
            ("previous", f["priorStart"], f["priorEnd"]),
        ]:
            p[period] = {
                key: select(
                    rows,
                    tag,
                    start,
                    end,
                    config[extra] + [(config["axis"], member)],
                    c["currency"],
                )
                for key, tag, extra in [
                    ("revenue", config["revenueTag"], "revenueExtra"),
                    ("operatingIncome", "OperatingIncomeLoss", "incomeExtra"),
                ]
            }
        if any(p["current"][k] is None for k in ("revenue", "operatingIncome")):
            raise ValueError(
                "Required operating-segment context missing: " + c["id"] + " " + member
            )
        segments.append(dict(id=member, label=label, **p))
    adjustments, reconciliations = {}, {}
    for key, core in [("revenue", "revenue"), ("operatingIncome", "operating_income")]:
        parts = []
        adjustment_key = (
            "incomeAdjustments" if key == "operatingIncome" else "revenueAdjustments"
        )
        for tag, dims, sign in config.get(adjustment_key, []):
            fact = select(rows, tag, f["start"], f["end"], dims, c["currency"])
            if fact is None:
                raise ValueError("Missing segment adjustment: " + tag)
            parts.append(dict(fact=fact, coefficient=sign))
        adjustments[key] = parts
        adjustment = (
            dict(
                value=sum(x["coefficient"] * x["fact"]["value"] for x in parts),
                derived=True,
                components=parts,
            )
            if parts
            else None
        )
        reconciliations[key] = reconcile(
            [s["current"][key] for s in segments], f["current"].get(core), adjustment
        )
    products = []
    for member, label in config.get("products", []):
        periods = {
            period: select(
                rows,
                config["productTag"],
                start,
                end,
                [("ProductOrServiceAxis", member)],
                c["currency"],
            )
            for period, start, end in [
                ("current", f["start"], f["end"]),
                ("previous", f["priorStart"], f["priorEnd"]),
            ]
        }
        products.append(dict(label=label, **periods))
    product_reconciliation = (
        reconcile([p["current"] for p in products], f["current"]["revenue"])
        if products
        else None
    )
    return dict(
        profile="operating_segments",
        title=config["title"],
        segments=segments,
        segmentRevenueBasis=(
            "공시 부문 매출. 내부거래·연결 조정 전 범위를 포함하며 합계 대비 비중이다."
            if config.get("grossRevenue")
            else "공시 부문 매출. 연결 매출과 공시 조정을 별도로 대사한다."
        ),
        reconciliations=reconciliations,
        adjustmentComponents=adjustments,
        products=products,
        productReconciliation=product_reconciliation,
        findings=config["findings"],
        remaining=config["remaining"],
        pricing=None,
        pricingHold="사업부 수치와 재무구조·재투자·주식 종류를 함께 검토한 뒤 정상 현금 및 가격 시나리오를 작성한다.",
    )
