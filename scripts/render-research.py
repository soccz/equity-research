"""Render portable research figures from the imported source excerpt."""
from pathlib import Path
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR', '/home/soccz/22tb/tmp/equity-research-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

font_path = subprocess.check_output(['fc-match', '-f', '%{file}', 'Noto Sans CJK KR'], text=True)
font_manager.fontManager.addfont(font_path)
plt.rcParams.update({'font.family': font_manager.FontProperties(fname=font_path).get_name(),
                     'axes.unicode_minus': False, 'svg.fonttype': 'none',
                     'font.size': 11, 'axes.edgecolor': '#d0d8c9',
                     'axes.labelcolor': '#667370', 'text.color': '#182e2c',
                     'xtick.color': '#667370', 'ytick.color': '#182e2c'})
data = json.loads((ROOT / 'evidence/wml-variance-20260929.json').read_text())
out = ROOT / 'artifacts'
out.mkdir(exist_ok=True)
for mobile in [False, True]:
    for metric in ['loss', 'performance']:
        fig, ax = plt.subplots(figsize=(4.5, 3.5) if mobile else (9, 3.15))
        fig.patch.set_facecolor('#fffefa')
        ax.set_facecolor('#fffefa')
        if metric == 'loss':
            rows = data['rows']
            for i, row in enumerate(rows):
                ax.barh(i, row['loss'], height=.46, color='#245d53' if i == 2 else '#92a784', zorder=3)
                if row['loss'] == 0:
                    ax.plot(0, i, 'o', color='#667370', markersize=4, zorder=4)
                ax.text(row['loss'] - .8, i, f"{row['loss']:.1f}%", va='center', ha='right', fontsize=10)
            ax.set_xlim(-50, 4)
            ax.set_xticks([-40, -30, -20, -10, 0])
            ax.set_xlabel('RW126 대비 QLIKE 변화 (%)', labelpad=10)
        else:
            rows = data['rows'][1:]
            for i, row in enumerate(rows):
                lo, hi = row['ci']
                ax.errorbar(row['delta'], i, xerr=[[row['delta']-lo], [hi-row['delta']]],
                            fmt='o', markersize=6, capsize=5, linewidth=2,
                            color='#245d53', zorder=3)
            ax.set_xlim(-.185, .13)
            ax.set_xticks([-.15, -.10, -.05, 0, .05, .10])
            ax.set_xlabel('RW126 대비 Sharpe 차이 · 95% 구간', labelpad=10)
        ax.axvline(0, color='#af5b35', linewidth=1.15, linestyle=(0, (4, 4)), zorder=2)
        ax.set_yticks(range(len(rows)), [row['label'] for row in rows])
        ax.set_ylim(len(rows)-.55, -.55)
        ax.grid(axis='x', color='#e6eadf', linewidth=.7, zorder=0)
        ax.tick_params(axis='y', length=0, pad=10, labelsize=10)
        ax.tick_params(axis='x', length=0, pad=8, labelsize=9)
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.subplots_adjust(left=.29 if mobile else .16, right=.97, bottom=.23, top=.95)
        stem = f"research-{metric}{'-mobile' if mobile else ''}"
        fig.savefig(out / f'{stem}.svg', facecolor=fig.get_facecolor())
        if not mobile:
            fig.savefig(out / f'{stem}.png', dpi=180, facecolor=fig.get_facecolor())
        plt.close(fig)
print('PASS: research figures rendered for desktop and mobile.')
