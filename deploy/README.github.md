# Equity Research · 미국·한국 주식 연구실

공시와 가격에서 조사할 기업을 찾고, 기업 가설을 정량 규칙으로 시험하며, 판단 조건을 다음 관측까지 추적하는 독립 연구 시스템입니다. 보고서는 이 과정의 출력입니다.

**[연구실 열기](https://soccz.github.io/equity-research/)** · [GitHub 저장소](https://github.com/soccz/equity-research) · [개인 홈페이지](https://soccz.github.io/)

GitHub Pages에 공개되어 있으며 홈페이지 Project 목록에서도 들어갈 수 있습니다.

## 화면과 연구

- 미국 Micron·NVIDIA·Alphabet·Apple, 한국 SK하이닉스·삼성전자·NAVER·LG전자
- 실제 SEC·OpenDART 공시와 Yahoo Finance 가격, 기간·연결 범위·발표일·원문 해시 보존
- 재무 조건별 선별, 기업 가설과 반론, 현금 시나리오, 가격 경로와 위험
- 가격 규칙과 당시 공시에 의한 재무 규칙의 별도 평가, 기준선·완전예지 상한·조건 제거 실험
- 과거 판단일별 입력과 선택 조회, 최초 판단 조건과 후속 관측의 이력
- 웹 화면과 PDF, 오프라인 재계산 검증

현재 8개 기업은 사후 선택한 개발 표본입니다. 비용 전 탐색 결과를 전체 시장 알파나 투자 성과 인증으로 읽지 않습니다. 기업별 정상 현금흐름·증권가치 검토가 남아 있어 투자 가격 판단은 보류합니다. 화면의 자료 기준일을 먼저 확인하세요.

## GitHub에서 운영

사이트는 `site/`의 정적 파일만 사용합니다. 개인 PC나 별도 웹 서버를 켜둘 필요가 없습니다. `.github/workflows/research-pages.yml`의 모든 작업은 GitHub가 제공하는 `ubuntu-24.04`에서 실행합니다.

1. 저장소 Pages 설정의 배포 소스를 **GitHub Actions**로 지정합니다.
2. `site/` 변경을 `main`에 푸시하면 보존된 검증본을 배포합니다. 이 경로에는 공시 키가 필요 없습니다.
3. 새 분석이 필요하면 Actions → **Research and Pages** → **Run workflow**에서 `refresh`를 선택합니다. 기준일을 비우면 UTC 전날을 사용합니다.
4. 새 자료 수집에는 저장소 Secret `DART_API_KEY`와 Variable `SEC_USER_AGENT`가 필요합니다. 후자는 SEC의 요청 식별자이며 프로젝트명과 연락 가능한 이메일을 설정합니다. 키를 코드나 사이트 파일에 넣지 않습니다.
5. 원문 수집·계산·회귀 검사·오프라인 재현·브라우저/PDF 검사가 끝나면 사이트와 판단 이력을 Git에 기록하고 배포합니다. 실패하면 이전 공개본이 유지됩니다.

예약 실행은 설정하지 않았습니다. 자료 갱신은 위 수동 워크플로로 요청합니다. 2026-09-30 GitHub-hosted 실행에서 SEC·DART·가격 수집, 25개 계산/발행 검사, 오프라인 재현, Chrome44개 검사, PDF6개 검사를 통과했습니다. [전체 실행 기록](https://github.com/soccz/equity-research/actions/runs/36682085869)을 확인할 수 있습니다.

원문과 실행별 코드·입력은 Actions의 `research-evidence-…` 아티팩트에 90일 보존하도록 설정했습니다. 장기 보존본은 만료 전에 내려받아 별도로 보관해야 합니다. 원문 캐시는 재수집을 줄이는 용도이며 판단 이력은 Git에 영구 기록합니다.

## 코드 구조

| 경로 | 역할 |
| --- | --- |
| `equitylab/` | 공시·가격 추출, 계산, 실험, 원장, 정적 발행 |
| `app/` | 분석 화면 원본 |
| `site/` | 검증된 공개 화면·그림·PDF |
| `data/universe.json` | 현재 기업과 증권 식별자 |
| `data/ledger/conditions.jsonl` | 수정하지 않고 추가하는 판단 이력 |
| `tests/` | 시점·기간·무결성·실패 처리·공개본 검사 |
| `scripts/cloud-refresh.py` | GitHub Actions의 자료 수집·계산 진입점 |

공개 화면은 제공기관 원문으로 연결됩니다. 계산에 사용한 원본 해시는 남기되 내부 파일 경로와 원자료 저장소 전체를 웹에 공개하지 않습니다. `site/site-manifest.json`은 공개 파일의 해시와 분석 버전을 기록합니다.

## 검증 명령

```sh
python -m unittest discover -s tests -v
python scripts/check-replay.py
node scripts/check-live.mjs
python scripts/check-artifacts.py
python -m equitylab build-site
python scripts/check-site.py
```

전체 연구 검사는 원문을 확보한 실행 환경에서 수행합니다. 초기 배포용 정적 파일 검사는 Python 표준 라이브러리만으로 가능합니다. 브라우저 검사는 Chrome에서 HTML 파일을 직접 열며 웹 서버를 시작하지 않습니다. Python 3.12, Node 24, NumPy·Matplotlib, PyMuPDF, Noto CJK 글꼴을 사용합니다.

[연구 화면](site/app/index.html) · [연구 범위](site/app/about.html) · [GitHub Pages 배포 방식](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
