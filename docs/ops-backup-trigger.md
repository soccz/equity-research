# 정기 실행 보조 트리거 (Google Apps Script)

ratings-v1의 무인 운영은 GitHub Actions(`.github/workflows/ratings.yml`)가 맡는다. 그런데 GitHub의 정기 실행(cron)은 이 계정에서 2026-08-31부터 5~7시간씩 늦게 생성된다. 그래서 다음 기한은 제때 오는 실행이 따로 필요하다.

- SSGA 보유종목을 받을 수 있는 하루 창
- 2026-10-19/20 계산 가능률 점검
- 매월 등록 기한

PC가 있는 동안에는 PC의 사용자 타이머(`ratings-dispatch.timer`, 2026-11-10까지)가 이 일을 한다. 아래는 PC를 처분한 뒤에도 같은 일을 하도록 소유자의 Google 계정에 거는 방법이다(약 15분). 실행이 겹쳐도 괜찮다. 드라이버는 몇 번을 돌아도 결과가 같고, 겹친 실행은 동시 실행 그룹에서 대기하거나 취소된다.

## 1. GitHub 토큰 만들기 (이 저장소의 Actions만)

1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. 이름: `ratings-dispatch`. 만료: 1년(달력에 갱신 알림을 적어 둔다).
3. Repository access: **Only select repositories** → `soccz/equity-research`
4. Permissions → Repository permissions → **Actions: Read and write**. 나머지는 건드리지 않는다(Metadata 읽기는 자동).
5. Generate → 토큰을 복사한다. 토큰은 다른 곳에 붙여 넣거나 저장하지 않는다.

이 토큰으로는 워크플로를 실행·취소·비활성화할 수 있지만, 코드와 원장은 바꿀 수 없다.

## 2. Apps Script 만들기

1. https://script.google.com → 새 프로젝트를 만들고 아래 코드를 그대로 붙여 넣는다.
2. 프로젝트 설정(톱니) → 스크립트 속성 → 속성 추가에서 이름 `GH_TOKEN`, 값에 위 토큰을 넣는다.
3. 편집기에서 함수 `install`을 골라 한 번 실행하고, 권한(외부 요청·트리거)을 허용한다.
4. 트리거 메뉴에서 `tick`이 매시간으로 걸렸는지 확인한다. 실패 알림은 "즉시"로 둔다(실패하면 메일이 온다).

```javascript
// soccz/equity-research "Ratings operation" 보조 트리거. 스크립트 속성 GH_TOKEN =
// 이 저장소 전용 fine-grained 토큰(Actions: Read and write).
const URL_ = 'https://api.github.com/repos/soccz/equity-research/actions/workflows/ratings.yml/dispatches';

function tick() {  // 매시간 실행; 시각은 모두 UTC
  const t = new Date(), d = t.getUTCDate(), h = t.getUTCHours(), wd = t.getUTCDay();
  const gate = t.getUTCFullYear() === 2026 && t.getUTCMonth() === 9 && d >= 19 && d <= 23;
  if (wd === 6 && h === 3) return dispatch_({mode: 'operate', evaluate: 'yes'});        // 토요일 공식 평가
  if ((d <= 10 || gate) && h >= 1 && h <= 14) return dispatch_({mode: 'operate'});  // 매시 KST 10~23시
  if (wd === 3 && h === 3) return dispatch_({mode: 'operate'});                          // 수요일: 캐시 유지
}

function dispatch_(inputs) {
  const r = UrlFetchApp.fetch(URL_, {
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    headers: {
      Authorization: 'Bearer ' + PropertiesService.getScriptProperties().getProperty('GH_TOKEN'),
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify({ref: 'main', inputs: inputs}),
  });
  const code = r.getResponseCode();
  if (code !== 204) throw new Error('dispatch ' + code + ': ' + r.getContentText().slice(0, 300));
}

function install() {
  ScriptApp.getProjectTriggers().forEach(function (x) { ScriptApp.deleteTrigger(x); });
  ScriptApp.newTrigger('tick').timeBased().everyHours(1).create();
}
```

## 3. 확인

- 설치 다음 정시대(UTC 01~14시, KST 10~23시)에 GitHub 저장소 Actions 탭에 `workflow_dispatch` 실행이 생기는지 본다. 한국 종목군은 평일 20:15 KST 이후에만 만들어지므로 저녁 시간대가 중요하다.
- 점검일 전에는 실행 결과가 "waiting"(할 일 없음)으로 끝나는 것이 정상이다.
- Apps Script 매시간 트리거는 그 시간 안의 임의의 분에 돈다. 같은 시간 안에서는 한 번만 보낸다.

## 4. 그만두기

Apps Script 트리거를 지우고, GitHub에서 토큰을 삭제한다(Settings → Developer settings → Fine-grained tokens → 삭제).
