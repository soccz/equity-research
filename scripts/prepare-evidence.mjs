import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, 'prototype/data.js'), 'utf8'), context);
const research = context.window.RESEARCH_PREVIEW.research;
const source = fs.readFileSync(research.source);
const actualHash = crypto.createHash('sha256').update(source).digest('hex');
if (actualHash !== research.sha256) throw new Error('Source changed: review the evidence before importing it again.');
const original = source.toString('utf8');
for (const row of research.rows.slice(1)) {
  const line = original.split('\n').find(line => line.startsWith(`| ${row.key} |`));
  if (!line) throw new Error(`Missing original row ${row.key}`);
  const cells = line.split('|').slice(1, -1).map(cell => cell.replace(/\*|\s/g, '').replaceAll('−', '-'));
  if (!cells[1].startsWith(`${row.loss}%`) || Number(cells[3]) !== row.sharpe) throw new Error(`Value mismatch ${row.key}`);
  const parsed = cells[4].match(/^([+-]?[\d.]+)\[([+-]?[\d.]+),([+-]?[\d.]+)\],p₂=([\d.]+)$/);
  if (!parsed || Number(parsed[1]) !== row.delta || Number(parsed[2]) !== row.ci[0]
    || Number(parsed[3]) !== row.ci[1] || Number(parsed[4]) !== row.p) throw new Error(`Interval mismatch ${row.key}`);
}
const e = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
fs.mkdirSync(path.join(root, 'evidence'), { recursive: true });
fs.mkdirSync(path.join(root, 'artifacts'), { recursive: true });
fs.writeFileSync(path.join(root, 'evidence/wml-variance-20260929.json'), JSON.stringify(research, null, 2) + '\n');
const rows = research.rows.map(row => `<tr><td>${e(row.label)}</td><td>${row.loss}%</td><td>${row.sharpe.toFixed(3)}</td><td>${row.ci ? row.delta.toFixed(3) : '기준선'}</td><td>${row.ci ? row.ci.join(', ') : '—'}</td><td>${row.p ?? '—'}</td></tr>`).join('');
fs.writeFileSync(path.join(root, 'evidence/wml-variance-20260929.html'), `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WML 분산 예측 연구의 보존 근거</title><style>body{font-family:"Noto Sans CJK KR",sans-serif;background:#f6f5f0;color:#182e2c;line-height:1.9;margin:0}main{max-width:900px;margin:auto;padding:40px 24px}h1{font-size:27px;font-weight:500}p{font-size:14px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:left;border-bottom:1px solid #ccd4c7;padding:12px}th{background:#e9eee2}.table{overflow-x:auto}code{word-break:break-all;font-size:11px}a{color:#245d53}details{margin-top:25px}.note{padding:18px;background:#e6edde;border-left:3px solid #245d53}small{color:#667370}@media print{main{padding:0}body{background:white}}</style></head>
<body><main><small>LOCAL RESEARCH · SOURCE EXCERPT</small><h1>WML 포트폴리오 분산 예측의 손실과 성과</h1><p>${research.date} 원 판정서 E2에서 기준선과 샤프 차이 신뢰구간이 제시된 세 대안을 발췌했습니다. 새로운 실험을 실행하거나 원 판정서의 독립 재현 절차를 이 프로젝트에서 반복한 것은 아닙니다.</p><div class="note">분석 단위는 <strong>WML 포트폴리오 분산</strong>입니다. 종목 수준 모형의 예측을 합산했지만 개별 종목의 표본외 예측 정확도를 평가한 결과로 사용할 수 없습니다.</div><p>${research.scope}. 평가 ${research.period}, ${research.months}개월. 이미 본 표본의 탐색 결과이며 확인적 주장이 아닙니다.</p><div class="table"><table><thead><tr><th>모형</th><th>QLIKE 상대 변화</th><th>Sharpe</th><th>Sharpe 차이</th><th>차이의 95% 구간</th><th>차이 p값</th></tr></thead><tbody>${rows}</tbody></table></div><p>p값은 샤프비율 차이의 양측 검정입니다. QLIKE 차이의 DM 검정은 별도이며 모형 전체에 대한 다중검정 보정은 하지 않았습니다. 원문의 반올림 값을 유지했으므로 표시된 수준끼리 뺀 값과 보고된 차이가 일부 다를 수 있습니다.</p><p>월별 재구성한 KOSPI P30_EW WML에 a1 가중을 적용했습니다. a1은 예측 분산의 역제곱근과 사후 연 12% 정규화 상수를 사용합니다. 이 상수는 상한 없는 가중의 Sharpe에 영향을 주지 않습니다. 현재 수치를 거래비용 차감 성과로 취급하지 않습니다. 부트스트랩은 순환 블록 6개월, 5,000회이며 원 판정서의 방법을 요약한 것입니다.</p><details><summary>원문 위치와 무결성 정보</summary><p><code>${e(research.source)}</code></p><p>SHA-256<br><code>${research.sha256}</code></p><p>생성 스크립트는 원문 해시와 세 대안의 손실·Sharpe·차이·신뢰구간·p값을 직접 대조합니다.</p><a href="wml-variance-20260929.json">보존한 구조화 수치</a></details><p><a href="../prototype/index.html#research">연구 보고서로 돌아가기</a></p></main></body></html>`);
console.log('PASS: source hash and 3 empirical rows matched; portable evidence saved.');
