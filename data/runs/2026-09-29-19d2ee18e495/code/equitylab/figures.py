"""Portable, snapshot-bound scientific figures for screen and print."""

import os
from .data import ROOT


def render_figures(snapshot):
    out = ROOT / "artifacts/live"
    out.mkdir(parents=True, exist_ok=True)
    prefix = snapshot["contentHash"][:12]
    experiments = [
        {**e, "figureKind": "research"}
        for e in snapshot["experiments"]
        if e["status"] == "exploratory"
    ]
    experiments.extend(
        {**e, "figureKind": "fundamental"}
        for e in snapshot.get("fundamentalExperiments", [])
        if e["status"] == "exploratory"
    )
    targets = [
        out / f"{prefix}-{e['market']}-{e['figureKind']}.svg" for e in experiments
    ]
    if targets and all(p.exists() for p in targets):
        return
    os.environ["MPLCONFIGDIR"] = str(ROOT / "data/cache/matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager, ticker
    import subprocess

    font_path = subprocess.check_output(
        ["fc-match", "-f", "%{file}", "Noto Sans CJK KR"], text=True
    )
    font_manager.fontManager.addfont(font_path)
    plt.rcParams.update(
        {
            "font.family": font_manager.FontProperties(fname=font_path).get_name(),
            "font.size": 10,
            "axes.unicode_minus": False,
            "svg.fonttype": "none",
        }
    )
    labels = {
        "equal_weight": "동일가중 기준선",
        "momentum63": "63일 모멘텀",
        "momentum_risk": "모멘텀 / 21일 위험",
        "oracle": "완전예지 상한",
        "financial_screen": "재무 조건 3개",
        "without_growth": "매출 성장 조건 제거",
        "oracle_one": "완전예지 1종목 상한",
    }
    colors = {
        "equal_weight": "#83917b",
        "momentum63": "#245d53",
        "momentum_risk": "#af5b35",
        "oracle": "#8d7caa",
        "financial_screen": "#245d53",
        "without_growth": "#af5b35",
        "oracle_one": "#8d7caa",
    }
    for e in experiments:
        fig, axes = plt.subplots(
            2,
            1,
            figsize=(9, 5.8),
            gridspec_kw={"height_ratios": [2, 1]},
            layout="constrained",
        )
        fig.set_facecolor("#fffefa")
        for ax in axes:
            ax.set_facecolor("#fffefa")
            ax.spines[["top", "right"]].set_visible(False)
            ax.spines[["left", "bottom"]].set_color("#ccd3c6")
            ax.tick_params(colors="#52685e", labelsize=9)
            ax.grid(axis="y", color="#e8ebe1", linewidth=0.6)
        for p in e["policies"]:
            axes[0].plot(
                [100, *p["path"]],
                label=labels[p["id"]],
                color=colors[p["id"]],
                linestyle="--" if p["id"].startswith("oracle") else "-",
                linewidth=1.8,
            )
        axes[0].set_yscale("log")
        axes[0].yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:g}"))
        axes[0].set_ylabel("시작 100 · 로그 눈금")
        axes[0].set_xticks(
            [0, e["windowCount"] // 2, e["windowCount"]],
            [e["start"], e["windows"][e["windowCount"] // 2 - 1]["endDate"], e["end"]],
        )
        axes[0].legend(frameon=False, ncol=2, fontsize=9, loc="upper left")
        axes[0].set_title(
            f"{e['market']} · {len(e['members'])}개 현재 기업 · {e['windowCount']}개 21일 구간 · 비용 전 탐색 결과",
            loc="left",
            fontsize=11,
            pad=12,
        )
        active = [
            p
            for p in e["policies"]
            if p["id"]
            in ["momentum63", "momentum_risk", "financial_screen", "without_growth"]
        ]
        for i, p in enumerate(active):
            center = p["meanExcess"] * 100
            interval = p.get("excessInterval", p.get("interval", []))
            if interval:
                lo, hi = [v * 100 for v in interval]
                axes[1].hlines(i, lo, hi, color=colors[p["id"]], linewidth=1.7)
            axes[1].plot(center, i, "o", color=colors[p["id"]], markersize=5)
        axes[1].set_yticks(range(len(active)), [labels[p["id"]] for p in active])
        axes[1].set_ylim(-0.7, len(active) - 0.3)
        axes[1].axvline(0, color="#8f978a", linewidth=1, linestyle="--")
        axes[1].set_xlabel(
            "21일 평균 기준선 차이 (%p) · 탐색용 95% 블록 부트스트랩 구간"
        )
        stem = out / f'{prefix}-{e["market"]}-{e["figureKind"]}'
        fig.savefig(stem.with_suffix(".svg"), facecolor=fig.get_facecolor())
        fig.savefig(stem.with_suffix(".png"), facecolor=fig.get_facecolor(), dpi=160)
        plt.close(fig)
