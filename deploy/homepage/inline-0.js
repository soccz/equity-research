
const CATEGORIES = {
  research: {
    label: 'Research',
    desc: '논문을 코드로, 가설을 검증으로 — 재현하고 확장하는 연구 기록',
    color: 'research',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 4h16v16H4z"/><path d="M8 8h8M8 12h6M8 16h4"/></svg>`,
    match: ['momentum-tail-insurance','momentum-literature','FF3','tactical-factor-allocation','worldquant-alpha','economic-time-transformer','VME_paper','papers']
  },
  project: {
    label: 'Project',
    desc: '직접 설계하고 만드는 진행형 프로젝트',
    color: 'finance',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 3v18h18"/><path d="M7 16l4-6 4 4 5-8"/></svg>`,
    match: ['equity-research','EcoGuard','CBAM','boundarybench','market-impact-analysis','Chrono-Trader-v2','HIGAN','xsec_alpha','prelude']
  },
  data: {
    label: 'Data & ML',
    desc: '수집하고, 학습시키고, 예측하는 데이터 파이프라인',
    color: 'data',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6"/><path d="M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/></svg>`,
    match: ['naverAPI','review_chatbot','son_data','NeuroTraffic-DT','fomc','bit_sector','bit_test','finance_semiconductor','RCNN_test','K_E_R']
  },
  side: {
    label: 'Side Project',
    desc: '직접 만들고, 실험하고, 개선하는 사이드 프로젝트',
    color: 'side',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>`,
    match: ['gaehwa-aac','AI_poker','night-shift-escape','self_exercise','kaggle_test','young-and-home','MC_order','forjp']
  },
  note: {
    label: 'Notes & Daily',
    desc: '오늘 배운 것, 내일 할 것 — 매일의 기록',
    color: 'note',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`,
    match: ['Daily-report','finance-note','fin-momentum','asset-management-guide','CFA-notes']
  },
  edu: {
    label: 'Education',
    desc: '"왜"에서 시작해서 "어떻게"로 끝나는 — 아무것도 모르는 상태에서 체화까지',
    color: 'edu',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>`,
    match: ['python-why','bigdata-analyst-notes','M_C_P','AP_CSA','FIN_AI_book']
  }
};

const LANG_COLORS = {
  'Python':'#3572A5','JavaScript':'#f1e05a','TypeScript':'#3178c6',
  'Jupyter Notebook':'#DA5B0B','HTML':'#e34c26','CSS':'#563d7c',
  'C++':'#f34b7d','Java':'#b07219','Go':'#00ADD8','Rust':'#dea584'
};

const DESCS = {
  'equity-research': '미국·한국 주식 연구실 — 실제 공시와 가격으로 기업을 선별하고, 가설·기준선·판단 이력을 연결하는 독립 연구 시스템. 현재 8개 기업의 탐색 연구',
  'EcoGuard': '2026 하나 청년 금융인재 양성 프로젝트 대상 · EcoGuard — 비정형 수출 데이터를 추적 가능한 증빙으로 정규화하고 EU 조문 검색·CBAM 기술 인벤토리·가격 민감도·산림 변화 근거를 연결한 3인 팀의 ESG 무역금융 PoC',
  'gaehwa-aac': '개화 · Gaehwa AAC — 모델 선택·캘리브레이션부터 화행 정책, 실시간 후보 스트리밍과 평가까지 직접 만든 AI 사이드 프로젝트 케이스 스터디',
  'momentum-tail-insurance': '졸업논문 프로젝트 — "위험 예측이 좋아지면 무엇이 좋아지는가?" 한국 모멘텀 35년, 39번의 실험(실패·철회 포함 전부 공개)으로 답한 기록. 답: 수익률이 아니라 꼬리(최악의 달)가 좋아진다',
  'momentum-literature': '모멘텀 위험관리 문헌 32편과 기초 논문 2편 전수검수 — 상황별 읽기 경로 11개, 방법 여권, 근거 locator, 한국 WML 변환기와 주장 방화벽을 한곳에서 탐색',
  'M_C_P': 'Claude Thinking \u2014 클로드 코드 완벽 가이드. 7 Parts 30 Chapters 한국어 교재 + 발표자료',
  'VME_paper': 'Value and Momentum Everywhere (AMP 2013) \u2014 논문 완전 해체. 8개 시장 \u00D7 두 팩터 재현 + 한국 모멘텀 검증',
  'AP_CSA': 'AP Computer Science A 한국어 가이드 \u2014 CSAwesome2 기반, Unit \u00B7 FRQ \u00B7 Mock \u00B7 Level \u00B7 Topical 통합',
  'fin_final': 'AI 기반 크립토 분석 시스템 \u2014 베이지안 추론 + 칼만 필터로 179개 암호화폐 자동 분석',
  'enhanced-fin-gan-final': 'Enhanced Fin-GAN 자율 학습 시스템',
  'fin_gan_train': 'Fin-GAN 모델 학습 파이프라인',
  'coin': '암호화폐 데이터 분석',
  'worldquant-alpha': 'Alpha Research Journal \u2014 퀀트 알파 연구의 사고 과정, 실패, 발견을 기록한 21챕터 연구 저널',
  'xsec_alpha': 'Cross-Sectional Crypto Ranking \u2014 gan_t 실패에서 시작해 운영 원장·비용·동시성 감사를 거친 전체 기록. SHORT 수동 판단 신호 + LONG KILL / 조건부 WATCH\u22641, prospective shadow 대시보드',
  'prelude': '저하방·고상방 후보를 찾는 수동매매 보조 레이더 — R1 08:50/09:05 알림. 모델 비교의 실패, 측정·전달 수리, 새 체결정보 실험까지 이어지는 개발일지. v2 종료 · Top10은 비발송 기록시험, 추천 우위 미검증',
  'economic-time-transformer': 'Economic Time in Financial Transformers \u2014 Clark(1973)의 경제적 시간을 Transformer에 구현하려다 배운 것들. 논문 4편 + ~400 실험',
  'Chrono-Trader': '시계열 기반 트레이딩 시스템 v1',
  'Chrono-Trader-v2': 'AETHER \u2014 Transformer+CNN 하이브리드 암호화폐 예측 시스템',
  'fomc': 'FOMC 회의 데이터 분석',
  'bit_sector': '비트코인 섹터별 상관관계 분석',
  'bit_test': '비트코인 시계열 분석 실험',
  'finance_semiconductor': '반도체 산업 금융 데이터 분석',
  'K_E_R': 'Korea Equity Reports — DART 기반 코스피 24종목 자동 종합진단. 출처 검증 + 추론 명시 + XBRL ground truth, 분기 단위 누적',
  'HIGAN': '개입 설명을 언제 믿을 수 있을까 — 가까운 관측과 설명 보류를 새 기준점 64개에서 검증. 채택 56.50%·채택 중 오판 2.43%, 효과와 한계를 코드·데이터로 공개한 방법론 연구',
  'finance-note': '금융 학습 노트 모음',
  'CFA-notes': 'CFA Level 1 Complete Study Guide \u2014 93 Readings 한국어 Deep Dive (아무것도 모르는 사람부터 전공자까지)',
  'FF3': '한국 주식시장 Fama-French 3-Factor 모델 \u2014 KRX 전 종목 일별 데이터 기반',
  'CBAM': 'Convolutional Block Attention Module 구현 실험',
  'MAE': 'Masked Autoencoder 사전학습 모델 구현',
  'RCNN_test': 'R-CNN 객체탐지 모델 테스트',
  'kaggle_test': 'Kaggle 대회 데이터 분석 실습',
  'market-impact-analysis': '3–8월 정책 뉴스 분석 개발기. 수집·판독·배치 추론·시장 비교·보고·검수의 구현 지도와 실제 코드로 읽는 네 가지 사례.',
  'boundarybench': '500문항 메타인지 벤치마크 — 4개 frontier 모델에서 false certainty 96%→6% gradient 발견 (Kaggle AGI Hackathon)',
  'fin-momentum': '모멘텀 투자 연구 스터디 가이드 — 9챕터 + 부록',
  'tactical-factor-allocation': '2022 AEL 논문 재현 — 멀티팩터 포트폴리오 전술적 배분',
  'asset-management-guide': '비전공자를 위한 자산운용 학습 시리즈 — 12챕터 완성',
  'MC_order': '주문 관리 웹 애플리케이션',
  'night-shift-escape': '솔로 호러-디펜스 브라우저 게임 \u2014 방 점유, 감염자 대응, 탈출',
  'AI_poker': 'Private Holdem GTO Practice — 8인 텍사스 홀덤 연습 테이블. 프로/GTO 성향 AI 7명, 심리 멘트, 패배 분석, 리플레이 복기, 하루 2회 뱅크롤 제한을 넣은 솔로 트레이닝 게임',
  'demo': 'MediaPipe Vision 기반 데모 프로젝트',
  'forjp': 'COUPLE \u2014 한국형 대중교통 기반 데이트 코스 플래너',
  'self_exercise': '개인 운동 기록 & 분석 앱',
  'Ptravel': '졸업작품 \u2014 여행 플랫폼',
  'naverAPI': '네이버 API 활용 데이터 수집',
  'review_chatbot': '리뷰 분석 AI 챗봇',
  'son_data': '손흥민 경기 데이터 분석',
  'NeuroTraffic-DT': '지능형 교통 관제 디지털 트윈 \u2014 Deep LSTM 기반 혼잡도 예측',
  'Daily-report': '일일 리포트 & 회고 기록',
  'young-and-home': '청년 안심 주거 코디네이터 \u2014 서강대 AI 해커톤 5개 에이전트 시스템',
  'python-why': 'PyWhy \u2014 컴퓨터가 어떻게 생각하는가. 4레벨 15주 본 강의 + 30주 알고리즘 심화 커리큘럼',
  'bigdata-analyst-notes': '빅데이터 분석기사 필기 완벽 가이드 \u2014 4과목 14,000줄 Deep Dive. 전공 제로에서 합격까지',
  'papers': 'Paper Deconstructions \u2014 \ub9e4\uc8fc \uc6d4/\uc218/\uae08 \ud55c \ud3b8\uc529, Source Lock \ud1b5\uacfc \ub17c\ubb38\uc744 11\uac1c \uc139\uc158\uc73c\ub85c \ud574\uccb4. KaTeX \uc218\uc2dd + \uc778\ud130\ub799\ud2f0\ube0c viz (grokking \uacf1\uc120 / attention motif / phase transition)',
  'FIN_AI_book': '금융 AI 6대 영역 한국어 정리 — 6장 38절. 1차 자료 인용 + 인라인 SVG + 한국 핀테크 사례 보강'
};

// Synthetic entry for the (private) papers repo \u2014 surfaced as a research project card
const STATIC_PROJECTS = [{
  name: 'equity-research',
  title: '미국·한국 주식 연구실',
  description: DESCS['equity-research'],
  language: 'Python',
  pushed_at: '2026-09-30T07:00:00Z',
  github_url: 'https://github.com/soccz/equity-research',
  __static: true
},{
  name: 'market-impact-analysis',
  title: '정책 뉴스 분석의 기반을 만들다',
  description: DESCS['market-impact-analysis'],
  language: 'Python',
  pushed_at: '2026-09-29T00:00:00Z',
  github_url: 'https://github.com/soccz/market-impact-analysis',
  __static: true
},{
  name: 'momentum-literature',
  title: '모멘텀 논문 활용 가이드',
  description: DESCS['momentum-literature'],
  language: 'HTML',
  pushed_at: '2026-08-16T00:00:00Z',
  github_url: 'https://github.com/soccz/momentum-literature-guide',
  __static: true
},{
  name: 'EcoGuard',
  description: DESCS['EcoGuard'],
  language: 'Python',
  pushed_at: '2026-08-11T03:00:00Z',
  github_url: 'https://github.com/soccz/EcoGuard',
  __static: true
},{
  name: 'papers',
  description: DESCS['papers'],
  language: 'Markdown',
  pushed_at: new Date().toISOString(),
  __static: true
},{
  name: 'FIN_AI_book',
  description: DESCS['FIN_AI_book'],
  language: 'Markdown',
  pushed_at: new Date().toISOString(),
  __static: true
},{
  name: 'AI_poker',
  description: DESCS['AI_poker'],
  language: 'HTML',
  pushed_at: new Date().toISOString(),
  __static: true
},{
  name: 'gaehwa-aac',
  title: '개화 · Gaehwa AAC',
  description: DESCS['gaehwa-aac'],
  language: 'Python',
  pushed_at: '2026-07-25T12:00:00Z',
  github_url: 'https://github.com/Tech4GoodHACKERTHON/AI_model',
  __static: true
}];

let allRepos = [];
let currentCat = null;

function getCat(name) {
  for (const [k, c] of Object.entries(CATEGORIES)) {
    if (c.match.includes(name)) return k;
  }
  return null;
}

function fmtDate(s) {
  const d = new Date(s);
  const diff = Math.floor((new Date() - d) / 86400000);
  if (diff === 0) return '오늘';
  if (diff === 1) return '어제';
  if (diff < 7) return diff + '일 전';
  if (diff < 30) return Math.floor(diff / 7) + '주 전';
  if (diff < 365) return Math.floor(diff / 30) + '개월 전';
  return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'short', day: 'numeric' });
}

const HTML_ESCAPE = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => HTML_ESCAPE[char]);
}

const escapeAttr = escapeHtml;

function projectTitle(project) {
  return project.title || project.name || '';
}

function projectGithubUrl(project) {
  const fallback = `https://github.com/soccz/${encodeURIComponent(project.name || '')}`;
  if (!project.github_url) return fallback;

  try {
    const url = new URL(project.github_url);
    const isTrustedGithubUrl =
      url.protocol === 'https:' &&
      url.hostname === 'github.com' &&
      !url.username &&
      !url.password &&
      !url.port;
    return isTrustedGithubUrl ? url.href : fallback;
  } catch {
    return fallback;
  }
}

function showPage(page) {
  document.querySelectorAll('.page').forEach(p => {
    p.classList.remove('active');
    p.style.display = 'none';
  });
  const target = document.getElementById('page-' + page);
  target.style.display = 'flex';
  requestAnimationFrame(() => {
    target.classList.add('active');
  });
  document.querySelectorAll('.nav-links a:not(.gh-link)').forEach(a => a.classList.remove('active'));
  document.getElementById('nav-' + page).classList.add('active');
  if (page === 'blog') renderSidebar(currentCat);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* renderFeatured removed */

function renderCatGrid() {
  const grid = document.getElementById('catGrid');
  const counts = {};
  for (const k of Object.keys(CATEGORIES)) counts[k] = 0;
  allRepos.forEach(r => { const c = getCat(r.name); if (c) counts[c]++; });

  grid.innerHTML = Object.entries(CATEGORIES).map(([k, cat], idx) => {
    const repos = allRepos.filter(r => getCat(r.name) === k).slice(0, 4);
    return `<div class="cat-card ${k}-card fade-in" style="animation-delay:${idx * 0.07}s" onclick="currentCat='${k}';showPage('blog')">
      <div class="cat-card-header">
        <div class="cat-card-icon ${cat.color}">${cat.icon}</div>
        <div>
          <div class="cat-card-title">${cat.label}</div>
          <div class="cat-card-count">${counts[k]}개 프로젝트</div>
        </div>
      </div>
      <div class="cat-card-desc">${cat.desc}</div>
      <div class="cat-card-repos">
        ${repos.map(r => `<span class="cat-card-repo">${escapeHtml(projectTitle(r))}</span>`).join('')}
        ${counts[k] > 4 ? `<span class="cat-card-repo">+${counts[k] - 4}</span>` : ''}
      </div>
    </div>`;
  }).join('');
}

function renderSidebar(catKey) {
  currentCat = catKey;
  const list = document.getElementById('sidebarList');
  const counts = {};
  let total = 0;
  for (const k of Object.keys(CATEGORIES)) counts[k] = 0;
  allRepos.forEach(r => { const c = getCat(r.name); if (c) { counts[c]++; total++; } });

  let html = `<li class="sidebar-item ${!catKey ? 'active' : ''}" onclick="renderSidebar(null)">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
    All <span class="sb-count">${total}</span></li>`;
  for (const [k, cat] of Object.entries(CATEGORIES)) {
    if (!counts[k]) continue;
    html += `<li class="sidebar-item ${catKey === k ? 'active' : ''}" onclick="renderSidebar('${k}')">
      ${cat.icon} ${cat.label} <span class="sb-count">${counts[k]}</span></li>`;
  }
  list.innerHTML = html;
  renderPosts(catKey);
}

function renderPosts(catKey) {
  const el = document.getElementById('posts');
  const t = document.getElementById('blogTitle');
  const d = document.getElementById('blogDesc');
  if (catKey && CATEGORIES[catKey]) {
    t.textContent = CATEGORIES[catKey].label;
    d.textContent = CATEGORIES[catKey].desc;
  } else {
    t.textContent = 'All Posts';
    d.textContent = '모든 프로젝트와 연구 기록';
  }

  const dateKey = allRepos[0]?.pushed_at ? 'pushed_at' : 'pushedAt';
  const list = allRepos
    .filter(r => { const c = getCat(r.name); return c && (catKey ? c === catKey : true); })
    .sort((a, b) => new Date(b[dateKey]) - new Date(a[dateKey]));

  if (!list.length) {
    el.innerHTML = '<div style="text-align:center;padding:80px 0;color:var(--text-muted);font-size:14px">프로젝트가 없습니다.</div>';
    return;
  }

  el.innerHTML = list.map((r, i) => {
    const cat = getCat(r.name);
    const lang = r.language || r.primaryLanguage?.name;
    const lc = LANG_COLORS[lang] || '#ccc';
    const PROJECT_PAGES = {
      'equity-research': '/equity-research/',
      'momentum-literature': '/projects/momentum-literature/',
      'EcoGuard': '/projects/ecoguard/',
      'gaehwa-aac': '/projects/gaehwa/',
      'momentum-tail-insurance': '/projects/momentum-journey/',
      'market-impact-analysis': '/projects/market-impact-v2/',
      'boundarybench': '/projects/boundarybench/',
      'asset-management-guide': '/projects/asset-management/',
      'fin-momentum': '/projects/fin-momentum/',
      'tactical-factor-allocation': '/projects/tactical-factor-allocation/',
      'CBAM': '/projects/cbam/',
      'Chrono-Trader-v2': '/projects/chrono-trader-v2/',
      'fomc': '/projects/fomc/',
      'bit_sector': '/projects/bit-sector/',
      'bit_test': '/projects/bit-test/',
      'finance_semiconductor': '/projects/finance-semiconductor/',
      'K_E_R': '/projects/k-e-r/',
      'HIGAN': '/projects/higan-interaction/',
      'finance-note': '/projects/finance-note/',
      'CFA-notes': '/projects/cfa-notes/',
      'bigdata-analyst-notes': '/projects/bigdata-analyst-notes/',
      'FF3': '/projects/ff3/',
      'RCNN_test': '/projects/rcnn-test/',
      'MC_order': '/projects/mc-order/',
      'forjp': '/projects/forjp/',
      'M_C_P': 'https://soccz.github.io/M_C_P/',
      'AP_CSA': 'https://soccz.github.io/AP_CSA/',
      'VME_paper': 'https://soccz.github.io/VME_paper/',
      'naverAPI': '/projects/naverapi/',
      'review_chatbot': '/projects/review-chatbot/',
      'son_data': '/projects/son-data/',
      'NeuroTraffic-DT': '/projects/neurotraffic-dt/',
      'night-shift-escape': '/projects/night-shift-escape/',
      'AI_poker': '/projects/ai-poker/',
      'self_exercise': '/projects/self-exercise/',
      'kaggle_test': '/projects/kaggle-test/',
      'Daily-report': '/projects/daily-report/',
      'young-and-home': '/projects/young-and-home/',
      'economic-time-transformer': '/projects/economic-time-transformer/',
      'worldquant-alpha': '/projects/worldquant-alpha/',
      'xsec_alpha': '/projects/xsec-alpha/',
      'prelude': '/projects/prelude/',
      'python-why': 'https://soccz.github.io/python-why/',
      'papers': '/projects/papers/',
      'FIN_AI_book': '/projects/fin-ai-book-notes/'
    };
    const page = PROJECT_PAGES[r.name];
    const url = page || projectGithubUrl(r);
    const desc = r.description || DESCS[r.name] || '';
    const openInNewTab = !page;
    const githubUrl = projectGithubUrl(r);
    const title = projectTitle(r);
    return `<div class="post-card ${cat}-post fade-in" role="link" tabindex="0" data-url="${escapeAttr(url)}" data-new-tab="${openInNewTab}" onclick="openPost(this.dataset.url, this.dataset.newTab === 'true')" onkeydown="handlePostKey(event, this.dataset.url, this.dataset.newTab === 'true')" style="animation-delay:${i * 0.04}s">
      <div class="post-top">
        <span class="post-badge ${cat}">${CATEGORIES[cat]?.label || ''}</span>
        <span class="post-date">${fmtDate(r[dateKey])}</span>
      </div>
      <div class="post-title">${escapeHtml(title)}</div>
      <div class="post-desc">${escapeHtml(desc)}</div>
      <div class="post-bottom"><span class="post-gh" role="link" tabindex="0" data-url="${escapeAttr(githubUrl)}" onclick="event.stopPropagation();openPost(this.dataset.url, true)" onkeydown="handleExternalKey(event, this.dataset.url)"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>GitHub</span></div>
    </div>`;
  }).join('');
}

function openPost(url, openInNewTab) {
  if (openInNewTab) {
    window.open(url, '_blank', 'noopener');
    return;
  }
  window.location.href = url;
}

function handlePostKey(event, url, openInNewTab) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  openPost(url, openInNewTab);
}

function handleExternalKey(event, url) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  event.stopPropagation();
  openPost(url, true);
}

function mergeStaticProjects(repos) {
  const merged = Array.isArray(repos) ? repos.slice() : [];
  if (typeof STATIC_PROJECTS === 'undefined') return merged;
  const existing = new Set(merged.map(r => r.name));
  for (const sp of STATIC_PROJECTS) {
    if (!existing.has(sp.name)) merged.unshift(sp);
  }
  return merged;
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebarOverlay').classList.toggle('open');
}

// Header scroll effect
let lastScroll = 0;
window.addEventListener('scroll', () => {
  const header = document.querySelector('header');
  if (window.scrollY > 20) header.classList.add('scrolled');
  else header.classList.remove('scrolled');
  lastScroll = window.scrollY;
});

// Scroll-triggered fade-in for home page elements
function initScrollObserver() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('.fade-up').forEach(el => observer.observe(el));
}

// Close sidebar on resize
window.addEventListener('resize', () => {
  if (window.innerWidth > 768) {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebarOverlay').classList.remove('open');
  }
});

async function init() {
  initScrollObserver();
  allRepos = mergeStaticProjects([]);
  renderCatGrid();

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch('https://api.github.com/users/soccz/repos?per_page=100&sort=pushed', {
      signal: controller.signal
    });
    if (!res.ok) throw new Error('API error');
    allRepos = mergeStaticProjects(await res.json());
  } catch (e) {
    allRepos = mergeStaticProjects([]);
  } finally {
    clearTimeout(timeout);
  }

  renderCatGrid();
  if (!allRepos.length) {
    document.getElementById('catGrid').innerHTML = '<div style="text-align:center;padding:40px 0;color:var(--text-muted);font-size:14px;grid-column:1/-1">GitHub API에서 데이터를 불러오지 못했습니다.</div>';
  }
}

// Initial fade-up for hero
document.body.classList.add('anim-ready');
requestAnimationFrame(() => {
  document.querySelectorAll('.fade-up').forEach((el, i) => {
    el.style.transitionDelay = (i * 0.1) + 's';
  });
});

init();

// PIN logic — PBKDF2(SHA-256, 300k iters, salted) + lockout
let pinValue = '';
const PIN_HASH = '18a8e3cd1a2fcc3f36b20359ef349fad60f28324d343f563ab91c1f6582330f3';
const PIN_SALT = 'soccz-pin-v2-2026';
const PIN_ITERS = 300000;
const PIN_MAX_ATTEMPTS = 5;
const PIN_LOCKOUT_MS = 60000;

async function pinDerive(pin) {
  const enc = new TextEncoder();
  const keyMat = await crypto.subtle.importKey(
    'raw', enc.encode(pin), { name: 'PBKDF2' }, false, ['deriveBits']
  );
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: enc.encode(PIN_SALT), iterations: PIN_ITERS, hash: 'SHA-256' },
    keyMat, 256
  );
  return Array.from(new Uint8Array(bits)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function pinLockoutRemaining() {
  const until = parseInt(sessionStorage.getItem('pinLockUntil') || '0', 10);
  return Math.max(0, until - Date.now());
}
function pinRegisterFail() {
  const fails = parseInt(sessionStorage.getItem('pinFails') || '0', 10) + 1;
  sessionStorage.setItem('pinFails', String(fails));
  if (fails >= PIN_MAX_ATTEMPTS) {
    sessionStorage.setItem('pinLockUntil', String(Date.now() + PIN_LOCKOUT_MS));
    sessionStorage.setItem('pinFails', '0');
  }
  return fails;
}
function pinResetFails() {
  sessionStorage.removeItem('pinFails');
  sessionStorage.removeItem('pinLockUntil');
}

const PIN_TARGET = 'https://soccz.github.io/python-why/';
const PIN_TARGETS = new Set([
  PIN_TARGET,
  '/projects/cfa-notes/',
  '/projects/fin-momentum/',
  '/projects/asset-management/',
  '/projects/bigdata-analyst-notes/',
  '/projects/fin-ai-book-notes/',
  'https://soccz.github.io/AP_CSA/',
  'https://soccz.github.io/M_C_P/'
]);
const PIN_NAMES = {
  [PIN_TARGET]: 'PyWhy',
  '/projects/cfa-notes/': 'CFA Notes',
  '/projects/fin-momentum/': 'Momentum Study',
  '/projects/asset-management/': 'Asset Management',
  '/projects/bigdata-analyst-notes/': 'BDA Notes',
  '/projects/fin-ai-book-notes/': 'Financial AI Deep Dive',
  'https://soccz.github.io/AP_CSA/': 'AP CSA',
  'https://soccz.github.io/M_C_P/': 'MCP Guide'
};
let pinPendingUrl = null;
let pinBusy = false;

function pinOpen(url) {
  pinPendingUrl = url;
  pinValue = '';
  pinRender();
  const err = document.getElementById('pinError');
  err.textContent = '';
  document.getElementById('pinTitle').textContent = PIN_NAMES[url] || 'Protected';
  document.getElementById('pinOverlay').classList.add('show');
  const remain = pinLockoutRemaining();
  if (remain > 0) err.textContent = `잠금됨 — ${Math.ceil(remain / 1000)}초 후 재시도`;
}
function pinClose() {
  document.getElementById('pinOverlay').classList.remove('show');
  pinValue = '';
  pinRender();
  document.getElementById('pinError').textContent = '';
}
async function pinInput(d) {
  if (pinBusy) return;
  if (pinLockoutRemaining() > 0) {
    document.getElementById('pinError').textContent = `잠금됨 — ${Math.ceil(pinLockoutRemaining() / 1000)}초 후 재시도`;
    return;
  }
  if (pinValue.length >= 4) return;
  pinValue += d;
  pinRender();
  if (pinValue.length === 4) {
    pinBusy = true;
    document.getElementById('pinError').textContent = '확인 중…';
    try {
      const h = await pinDerive(pinValue);
      if (h === PIN_HASH) {
        pinResetFails();
        // Master token: PIN-게이트가 있는 자식 페이지가 자동 통과할 수 있도록
        try { sessionStorage.setItem('soccz-pin-master', h); } catch(e) {}
        const dest = pinPendingUrl;
        pinClose();
        window.location.href = dest;
      } else {
        const fails = pinRegisterFail();
        const remain = pinLockoutRemaining();
        document.getElementById('pinError').textContent = remain > 0
          ? `잠금됨 — ${Math.ceil(remain / 1000)}초 후 재시도`
          : `번호가 틀렸습니다 (${fails}/${PIN_MAX_ATTEMPTS})`;
        setTimeout(() => {
          pinValue = '';
          pinRender();
          if (pinLockoutRemaining() === 0) document.getElementById('pinError').textContent = '';
        }, 600);
      }
    } finally {
      pinBusy = false;
    }
  }
}
function pinClear() {
  pinValue = pinValue.slice(0, -1);
  pinRender();
}
function pinRender() {
  document.querySelectorAll('.pin-dot').forEach((d, i) => {
    d.classList.toggle('filled', i < pinValue.length);
  });
}
// ESC to close
document.addEventListener('keydown', e => {
  if (!document.getElementById('pinOverlay').classList.contains('show')) return;
  if (e.key === 'Escape') { pinClose(); return; }
  if (e.key === 'Backspace') { pinClear(); return; }
  if (/^[0-9]$/.test(e.key)) pinInput(e.key);
});
// Override openPost for PIN-protected pages
const _origOpenPost = openPost;
window.openPost = function(url, openInNewTab) {
  if (PIN_TARGETS.has(url)) { pinOpen(url); return; }
  _origOpenPost(url, openInNewTab);
};
