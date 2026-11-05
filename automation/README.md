# Mac 조회수 자동 갱신 (2026-11-05 전환)

- Mac 시스템 시간대 Asia/Seoul에서 한국 평일 09:00에 Mac LaunchAgent `com.dongjae.viral-refresh`가 실행합니다. 주말 및 기존 검토된 한국 공휴일은 제외합니다.
- 실제 실행 파일: `~/Library/Application Support/viral-sync/refresh_mac.py`. 두 저장소의 `automation/refresh_mac.py`는 설치본의 추적 가능한 사본입니다.
- 원본 작업 폴더는 깨끗한 main, 지정된 origin, 원격 main 일치 상태여야 합니다. 임시 복제본에서 공식 달력 검사, 공개 수집, 90% 확인 기준, 데이터 구조 검사 및 빌드/구문 검사를 통과한 경우에만 허용 파일을 일반 commit/push합니다. 사용자 수정, staged/untracked 파일, Git 작업 또는 분기가 있으면 중단합니다. reset/stash/rebase/force-push는 하지 않습니다.
- 공개 응답만 수집하며 쿠키나 로그인 세션을 사용하지 않습니다. Git에는 기존 osxkeychain 인증을 사용하고 새 인증키를 만들지 않습니다.
- 변경이 없으면 커밋하지 않습니다. 성공한 날짜는 `refresh-state.json`에 기록해 같은 날 반복 실행을 막습니다. 실패는 로그에 남고 다음 예약/로그인 실행에서 재시도할 수 있습니다.
- `refresh.log`와 `refresh-error.log`는 같은 Application Support 폴더에 있습니다. 수동 검증은 `python3 automation/refresh_mac.py` (원본/원격 쓰기 없는 임시 복제본 검증), 실제 실행은 `--apply`입니다.
- 잠자는 동안 놓친 실행은 깨어난 후 합쳐서 실행됩니다. 종료된 Mac은 동작하지 않으며 재부팅 후 사용자 로그인이 필요합니다. 로그인 후 09:00 이후라면 당일 미완료 작업을 실행합니다. 실행 중 유휴 잠자기만 caffeinate로 막으며 강제 깨우기나 전원 설정 변경은 하지 않았습니다.
- 공휴일 검토는 2026-12-31까지 유효합니다. 2027년 달력을 별도로 검토해야 하며, 공식 출처 불일치/접속 불가 및 유효기간 초과는 안전하게 중단합니다.
- 기존 `com.dongjae.viral-sync`는 검증된 데이터 커밋만 내려받는 안전한 동기화 작업으로 유지합니다. 조회수를 수집하거나 push하지 않으므로 중복 게시하지 않습니다.
- GitHub의 조회수 예약 수집은 Mac 실수집·커밋·push 검증 후 제거했습니다. report의 Pages 재빌드 기능은 별도 `pages.yml`로 유지합니다.

아래는 이전 서버 방식의 구현 기록입니다. 현재 일정과 실행 방식은 위 내용을 따릅니다.

---

# 조회수 자동화 구현 상태

2026-10-12 기준 구현과 로컬 검증을 진행 중입니다. 서버 workflow와 Mac launchd를 설치했으며 `collector_ready`는 true입니다. 기존 데이터는 이 구현 작업으로 변경하지 않았습니다.

## 수집 및 검증

- Python 표준 라이브러리만 사용합니다. 공개 HTTP 응답만 읽으며 쿠키, 로그인 세션, API 키, 인증 파일을 읽거나 전달하지 않습니다.
- 네이버 카페 공개 페이지에서 cafe/article ID를 확인한 뒤 공개 article 응답의 동일 ID와 정수 readCount를 검증합니다. 축약된 화면 숫자를 추정하지 않습니다.
- 에펨코리아, MLBPARK, 보배드림 모바일, 블라인드, 호갱노노의 정확한 게시글별 공개 정수도 지원합니다.
- 저장된 실수집 결과: 직접 게시글 151개 중 145개, 확산 사례 39개 중 15개 확인. 나머지 30개는 이전 값 또는 공개 수치 없음 상태를 유지합니다. 두 저장소 모두 URL 190개가 고유합니다.
- 감소, 비정상 급증, 글 ID 불일치, 접근 오류, 비공개 및 모호한 수치는 보존합니다. 직접 게시글의 90% 미만 확인이면 전체 적용을 중단합니다.
- 변경이 없으면 시각만 바꾸지 않습니다. 변경이 있으면 성공 항목에 확인 시각을 표시하며 미확인 항목은 보존합니다. 리포트의 직접 게시글 합계, 정렬, 순위와 막대를 다시 계산합니다.
- 적용 계획에서 URL 및 값 보존을 검증합니다. publish.py는 허용 파일만 커밋하고 일반 push 뒤 원격 SHA를 확인합니다. force/reset/rebase는 사용하지 않습니다.

## 실행 및 비용

- 한국 평일 09:00/15:00: UTC cron `0 0,6 * * 1-5`. GitHub 예약 실행은 지연될 수 있습니다.
- 한국 공식 공휴일 검토 범위는 2026-10-12부터 2026-12-31까지이며 이 범위의 공휴일은 12월25일입니다. 범위 밖, 새 연도, 공식 공지 변경 또는 인식하지 못한 응답이면 중단합니다. 일시적인 연결 실패 때만 검토일로부터 최대 7일(현재 2026-10-19까지) 확인된 날짜를 사용합니다. 이 기간 이후 연결 실패 시 중단하며, 공식 자료가 기존 검토 내용과 일치하면 연도 유효 범위 안에서 실행할 수 있습니다. 2027년 달력은 별도 검토가 필요합니다.
- 2026-10-12 09:07 KST Chrome https://github.com/settings/billing/budgets 에서 계정 DongJae-Go-FE 전체 Actions 예산 $0, 사용액 $0, Stop usage Yes를 직접 재확인했습니다. 예산을 새로 만들거나 결제 설정을 변경하지 않았습니다. 이 확인 이후 읽기 전용 Linux 검증을 시작했습니다.
- 일반 ubuntu-latest, 15분 제한, 저장소별 단일 실행입니다. 캐시와 아티팩트 업로드는 없습니다. 시간 제한 자체는 비용 보장이 아닙니다.
- 해당 작업의 contents: write는 승인되었습니다. 새 PAT, secret, API 키는 없습니다.
- viral-report 기존 Pages 재빌드를 위한 pages: write는 승인되었으며 report 재빌드 작업에만 적용합니다. id-token 또는 Pages 설정 변경은 계획하지 않습니다.

## 파일 및 허용 변경

- refresh.py: 수집, 공휴일 검사, 적용 계획, 데이터 적용
- publish.py: 데이터 검증, 제한된 커밋, push, 원격 검증
- sync_local.py: Mac의 안전한 fast-forward 동기화
- refresh.workflow.yml.disabled / local-sync.plist.disabled: 설치 템플릿. 실제 workflow는 .github/workflows/refresh.yml이며 쓰기는 collector_ready로 차단합니다.
- guide 허용 파일: src/data/posts.ts, src/data/shares.ts, src/content/overview.mdx, src/content/results.mdx
- report 허용 파일: index.html

검증 명령:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s automation -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 automation/refresh.py
```

두 저장소의 로컬 통합 테스트, Linux 실수집 및 guide 빌드가 통과하여 collector_ready를 활성화했습니다. 전체 수집 후 검증·커밋·push·Pages 및 Mac 동기화를 최종 확인 중입니다.

## 안전한 Mac 동기화

09:20/09:40 및 15:20/15:40에만 시도합니다. 한국 주말, 공휴일, 달력 범위 밖은 건너뜁니다. 깨끗한 main과 지정 remote만 허용하고 진행 중 Git 작업, 로컬 수정, 분기, 완료 표식 누락, 무관한 파일 변경은 건너뜁니다. 서버 커밋은 1시간 이내여야 하며 확인한 정확한 SHA만 --ff-only로 반영합니다. fetch 후 로컬 상태를 다시 검사합니다. 기존 Git 인증만 사용합니다.

Mac 시간대 Asia/Seoul 및 /opt/homebrew/bin/python3를 확인하고 ~/Library/LaunchAgents/com.dongjae.viral-sync.plist를 등록했습니다. 서버 준비 플래그가 false이면 fetch/merge하지 않습니다. IDE 편집 자체를 감지할 수는 없으므로 Git 상태 검사와 덮어쓰기 방지에 의존합니다.

공식 출처 URL 및 검토 범위는 calendar.json에 기록되어 있습니다.

Linux 1차 검증: 두 저장소 안전 테스트 15개 통과 (이후 보강한 로컬 테스트는 17개 통과). report는 공식 공휴일 출처 연결 시간 초과로 쓰기를 하지 않고 중단했습니다. 진단을 분리하여 재검증 중입니다. 갱신 예정 데이터의 guide 로컬 lint/build와 report JavaScript 구문 검사는 통과했습니다.

Pages 최소 권한 근거: https://docs.github.com/en/rest/pages/pages#request-a-github-pages-build 에서 Pages write를 요구합니다. contents write만으로는 부족합니다. report에만 pages write를 가진 별도 작업을 추가하는 것이 승인되어 report 재빌드 작업에만 추가합니다.

스케줄은 활성 상태이며 자동화 코드 push에 따른 진단 트리거는 제거했습니다. 수동 workflow_dispatch는 apply=false가 기본입니다. report Pages 재빌드는 별도 작업의 contents read / pages write만 사용합니다.
