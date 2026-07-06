# 아카라 뉴스 크롤러 (GitHub Actions · 매시간 무료 실행)

```
[GitHub Actions cron 1시간] → 네이버 API + 다음/네이트 크롤링 → Apps Script 웹앱(doPost) → 구글 시트 → Vercel 대시보드
```

- **네이버**: 공식 검색 API(안정적). 원문 링크 + 네이버뉴스(n.news.naver.com) 링크 → `(네이버뉴스)` 태깅
- **다음/네이트**: 뉴스 검색 크롤링 → `v.daum.net` / `news.nate.com` 링크 → `(다음뉴스)`/`(네이트뉴스)` 태깅
- 중복은 서버(Apps Script)에서 **기사명+매체** 기준으로 제거 → 같은 헤드라인의 포털별 행은 각각 보존

## 설정 (1회)

### 1) 네이버 검색 API 키 발급 (무료)
1. https://developers.naver.com/apps/#/register 접속 → 로그인
2. 애플리케이션 이름 입력, **사용 API = "검색"** 선택, 환경 = "WEB 설정"(URL 아무거나, 예 http://localhost)
3. 등록 후 **Client ID / Client Secret** 확인

### 2) GitHub 저장소 시크릿 등록
저장소 → **Settings ▸ Secrets and variables ▸ Actions ▸ New repository secret** 로 4개 등록:
| 이름 | 값 |
|---|---|
| `WEBAPP_URL` | Apps Script 웹앱 `/exec` URL |
| `WEBAPP_TOKEN` | 웹앱 TOKEN (예: aqaramonitor2026) |
| `NAVER_ID` | 네이버 Client ID |
| `NAVER_SECRET` | 네이버 Client Secret |

### 3) 실행
- 저장소를 GitHub에 push하면 워크플로우가 자동 등록됩니다.
- **Actions 탭 → Aqara News Crawler → Run workflow** 로 즉시 1회 테스트.
- 이후 **매시간 자동** 실행됩니다. 로그는 Actions 탭에서 확인.

## 참고 / 한계
- **네이버**는 API라 안정적입니다. **다음·네이트**는 무료 API가 없어 HTML 크롤링이며, 사이트 마크업 변경 시 수집 0건이 될 수 있습니다. 그 경우 Actions 로그(`[daum] 수집 0행` 등)를 공유해 주시면 선택자를 보정합니다.
- 수집 항목: 게재일·매체·기사명·링크·채널 (종류/구분/앵글 등은 시트에서 수동 검수).
- 로컬 PowerShell 수집기나 Apps Script 트리거는 **사용하지 마세요**(이중 수집 방지). 크롤러가 유일한 자동 수집원입니다.
- 키워드/기간 조정: `.github/workflows/crawl.yml` 의 `KEYWORDS`, `DAYS` env.
