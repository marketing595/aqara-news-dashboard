#Requires -Version 5.1
<#
  아임웹 Open API 연동 토큰 발급 도구 (아카라 뉴스 대시보드 · 홈페이지 문의 탭)

  하는 일
   1) 아임웹 인증 페이지를 열어 '인증 코드'를 받고
   2) 그 코드로 refresh token(90일)을 발급받아 화면에 표시하고
   3) 원하면 지금 바로 문의 데이터를 받아 web/homepage.json을 만들어 준다.

  준비물 : 아임웹 개발자센터(https://developers.imweb.me)에서 만든 앱의 Client ID / Client Secret
           앱의 redirect URI에 아래 주소가 등록돼 있어야 한다.
           https://aqara-news-dashboard.vercel.app/imweb-auth.html

  ── Client ID / Secret 을 넣는 방법 (셋 중 아무거나) ──────────────────────
   A. 설정 파일 (권장 · 한 번만 해두면 끝)
        crawler\imweb-config.txt 에 아래처럼 저장
          CLIENT_ID=여기에_아이디
          CLIENT_SECRET=여기에_시크릿
          SITE_CODE=S202509250f66ad55637e1
        파일이 없으면 이 스크립트가 서식을 만들어 메모장으로 열어준다.
        (이 파일은 .gitignore 에 있어 GitHub에 올라가지 않는다)
   B. 실행 인자
        imweb-token.bat -ClientId "아이디" -ClientSecret "시크릿"
   C. 환경변수  IMWEB_CLIENT_ID / IMWEB_CLIENT_SECRET

  ※ 예전처럼 콘솔에 직접 붙여넣지 않는다 — 프롬프트가 뜨기 전에 붙여넣기가 먹혀
     값이 잘리고 30098(클라이언트 정보 불일치) 오류가 나던 문제를 없앴다.
#>
param(
  [string]$ClientId,
  [string]$ClientSecret,
  [string]$SiteCode,
  [string]$Code                      # 인증 코드까지 미리 알고 있으면 여기에
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$BASE        = 'https://openapi.imweb.me'
$REDIRECT    = 'https://aqara-news-dashboard.vercel.app/imweb-auth.html'
$SCOPE       = 'community:read site-info:read site-info:write'   # write는 '연동완료 처리'용(1회)
$DEFAULT_SITE = 'S202509250f66ad55637e1'   # 아카라라이프 아임웹 사이트 코드(자동 확인값)
$WEB_DIR     = Split-Path -Parent $PSScriptRoot
$OUT_JSON    = Join-Path $WEB_DIR 'homepage.json'

$CONF = Join-Path $PSScriptRoot 'imweb-config.txt'

# 프롬프트가 뜨기 전에 눌린 키·붙여넣기를 버린다(입력이 윗줄로 튀는 문제 방지)
function Ask($label, $default) {
  try { $Host.UI.RawUI.FlushInputBuffer() } catch {}
  Start-Sleep -Milliseconds 150
  try { $Host.UI.RawUI.FlushInputBuffer() } catch {}
  if ($default) { $v = Read-Host "$label [$default]"; if ([string]::IsNullOrWhiteSpace($v)) { return $default }; return $v.Trim() }
  do { $v = Read-Host $label } while ([string]::IsNullOrWhiteSpace($v))
  return $v.Trim()
}

# imweb-config.txt 읽기 (KEY=VALUE · # 주석 허용)
function Read-Conf($path) {
  $h = @{}
  if (-not (Test-Path $path)) { return $h }
  foreach ($line in (Get-Content $path -Encoding UTF8)) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith('#')) { continue }
    $k = $t.IndexOf('=')
    if ($k -lt 1) { continue }
    $h[$t.Substring(0, $k).Trim().ToUpper()] = $t.Substring($k + 1).Trim().Trim('"').Trim("'")
  }
  return $h
}

Write-Host ''
Write-Host '=== 아임웹 홈페이지 문의 연동 · 토큰 발급 ===' -ForegroundColor Yellow
Write-Host ''

$conf = Read-Conf $CONF

# 우선순위: 실행 인자 > 설정 파일 > 환경변수
if (-not $ClientId)     { $ClientId     = $conf['CLIENT_ID'] }
if (-not $ClientId)     { $ClientId     = $env:IMWEB_CLIENT_ID }
if (-not $ClientSecret) { $ClientSecret = $conf['CLIENT_SECRET'] }
if (-not $ClientSecret) { $ClientSecret = $env:IMWEB_CLIENT_SECRET }
if (-not $SiteCode)     { $SiteCode     = $conf['SITE_CODE'] }
if (-not $SiteCode)     { $SiteCode     = $env:IMWEB_SITE_CODE }
if (-not $SiteCode)     { $SiteCode     = $DEFAULT_SITE }

# 값이 없으면 서식 파일을 만들어 메모장으로 열어주고 종료 (콘솔 입력을 아예 안 받는다)
if ([string]::IsNullOrWhiteSpace($ClientId) -or [string]::IsNullOrWhiteSpace($ClientSecret)) {
  if (-not (Test-Path $CONF)) {
    $tpl = @"
# 아임웹 개발자센터(https://developers.imweb.me)에서 만든 앱의 값을 = 뒤에 붙여넣고 저장하세요.
# 저장한 뒤 imweb-token.bat 을 다시 실행하면 됩니다.
# 이 파일은 GitHub에 올라가지 않습니다(.gitignore).

CLIENT_ID=
CLIENT_SECRET=
SITE_CODE=$DEFAULT_SITE
"@
    [System.IO.File]::WriteAllText($CONF, $tpl, (New-Object System.Text.UTF8Encoding($true)))
    Write-Host '설정 파일을 새로 만들었습니다:' -ForegroundColor Cyan
  } else {
    Write-Host '설정 파일에 Client ID / Secret 이 비어 있습니다:' -ForegroundColor Red
  }
  Write-Host ('  ' + $CONF) -ForegroundColor Yellow
  Write-Host ''
  Write-Host '메모장이 열리면 CLIENT_ID= 와 CLIENT_SECRET= 뒤에 값을 붙여넣고 저장(Ctrl+S)한 다음,' -ForegroundColor Cyan
  Write-Host 'imweb-token.bat 을 다시 실행하세요.' -ForegroundColor Cyan
  Start-Process notepad.exe $CONF
  Write-Host ''
  Read-Host '엔터로 종료'
  exit 0
}

$clientId     = $ClientId.Trim()
$clientSecret = $ClientSecret.Trim()
$siteCode     = $SiteCode.Trim()

# 붙여넣기 사고 조기 발견 — 값이 이상하면 여기서 잡는다
Write-Host ('Client ID     : ' + $clientId.Substring(0, [Math]::Min(6, $clientId.Length)) + '…  (' + $clientId.Length + '자)') -ForegroundColor DarkGray
Write-Host ('Client Secret : ' + $clientSecret.Substring(0, [Math]::Min(4, $clientSecret.Length)) + '…  (' + $clientSecret.Length + '자)') -ForegroundColor DarkGray
Write-Host ('사이트 코드   : ' + $siteCode) -ForegroundColor DarkGray
if ($clientId -match '\s' -or $clientSecret -match '\s') {
  Write-Host '⚠ 값 안에 공백/줄바꿈이 섞여 있습니다. imweb-config.txt 를 다시 확인하세요.' -ForegroundColor Red
}

$state = [guid]::NewGuid().ToString('N').Substring(0, 12)
$authUrl = "$BASE/oauth2/authorize?responseType=code" +
           "&clientId=$([uri]::EscapeDataString($clientId))" +
           "&redirectUri=$([uri]::EscapeDataString($REDIRECT))" +
           "&scope=$([uri]::EscapeDataString($SCOPE))" +
           "&state=$state&siteCode=$([uri]::EscapeDataString($siteCode))"

Write-Host ''
Write-Host '브라우저에서 아임웹 인증 페이지를 엽니다. 로그인 후 [허용]을 누르세요.' -ForegroundColor Cyan
Write-Host $authUrl -ForegroundColor DarkGray
Start-Process $authUrl
Write-Host ''
Write-Host '허용하면 대시보드의 인증 코드 페이지로 이동합니다. 화면에 뜬 코드를 복사해'
Write-Host '아래 프롬프트가 나타난 뒤에 붙여넣고 엔터를 누르세요.' -ForegroundColor Cyan
if ($Code) { $code = $Code.Trim(); Write-Host ('4) 인증 코드(code): ' + $code) }
else { $code = Ask '4) 인증 코드(code)' $null }

Write-Host ''
Write-Host '토큰 발급 중...' -ForegroundColor Cyan
$tok = Invoke-RestMethod -Method Post -Uri "$BASE/oauth2/token" `
  -ContentType 'application/x-www-form-urlencoded' `
  -Body @{ clientId = $clientId; clientSecret = $clientSecret; redirectUri = $REDIRECT; code = $code; grantType = 'authorization_code' }

$access  = $tok.data.accessToken
$refresh = $tok.data.refreshToken
if (-not $access) { Write-Host '토큰 발급 실패. 코드가 만료됐을 수 있습니다(처음부터 다시).' -ForegroundColor Red; Read-Host '엔터로 종료'; exit 1 }

Write-Host ''
Write-Host '발급 완료! 아래 3개를 GitHub 저장소 Settings > Secrets and variables > Actions 에 등록하세요.' -ForegroundColor Green
Write-Host ''
Write-Host ('  IMWEB_CLIENT_ID      = ' + $clientId)
Write-Host ('  IMWEB_CLIENT_SECRET  = ' + $clientSecret)
Write-Host '  IMWEB_REFRESH_TOKEN  = (아래 값)'
Write-Host ''
Write-Host $refresh -ForegroundColor Yellow
Write-Host ''
try { Set-Clipboard -Value $refresh; Write-Host '(refresh token을 클립보드에 복사했습니다)' -ForegroundColor DarkGray } catch {}

# ---- 연동완료 처리 (아임웹 앱 상태를 '연동중' → '연동완료'로 바꿔야 API가 정상 동작) ----
$hdr = @{ Authorization = "Bearer $access" }
try {
  Invoke-RestMethod -Method Patch -Uri "$BASE/site-info/integration-complete" -Headers $hdr `
    -ContentType 'application/json' -Body '{}' | Out-Null
  Write-Host '연동완료 처리 OK' -ForegroundColor DarkGray
} catch {
  Write-Host ('연동완료 처리 건너뜀 (이미 완료 상태일 수 있음): ' + $_.Exception.Message) -ForegroundColor DarkGray
}

# ---- 유닛 코드 확인 ----
$unit = ''
try {
  $site = Invoke-RestMethod -Method Get -Uri "$BASE/site-info" -Headers $hdr
  $unit = $site.data.unitList[0].unitCode
  Write-Host ('사이트 유닛 코드 : ' + $unit + '  (' + $site.data.unitList[0].name + ')') -ForegroundColor DarkGray
} catch { Write-Host '유닛 코드 조회 실패(site-info:read 권한 확인)' -ForegroundColor Red }

Write-Host ''
$go = Read-Host '지금 바로 문의 데이터를 받아 homepage.json을 만들까요? (Y/N)'
if ($go -notmatch '^[Yy]') { Read-Host '엔터로 종료'; exit 0 }
if (-not $unit) { Write-Host '유닛 코드가 없어 중단합니다.' -ForegroundColor Red; Read-Host '엔터로 종료'; exit 1 }

function Get-AllPages($path, $extra) {
  $rows = @(); $page = 1
  while ($page -le 200) {
    $q = "$BASE$path" + "?page=$page&limit=100&unitCode=$unit" + $extra
    $r = Invoke-RestMethod -Method Get -Uri $q -Headers $hdr
    if ($r.data.list) { $rows += $r.data.list }
    if (-not $r.data.totalPage -or $page -ge $r.data.totalPage) { break }
    $page++
  }
  return $rows
}

Write-Host '입력폼 목록 조회 중...' -ForegroundColor Cyan
$forms = Get-AllPages '/community/forms' ''
Write-Host ('  입력폼 ' + $forms.Count + '개') -ForegroundColor DarkGray

Write-Host '문의(제출) 목록 조회 중...' -ForegroundColor Cyan
$subs = Get-AllPages '/community/form-submissions' ''
Write-Host ('  제출 ' + $subs.Count + '건') -ForegroundColor DarkGray

$PII = @('이름','성함','성명','연락처','전화','휴대','핸드폰','메일','mail','주소','내용','상세','요청사항','회사명','상호','생년','카톡','아이디')
$CHOICE = @('select','radio','checkbox','check','dropdown','agree')

$rows = @()
foreach ($s in $subs) {
  $w = [string]$s.wtime
  $dt = $null
  if ($w -match '^\d+$') { $dt = ([datetime]'1970-01-01').AddSeconds([double]$w).AddHours(9) }
  elseif ($w) { try { $dt = [datetime]::Parse($w); if ($w -match 'Z$') { $dt = $dt.ToUniversalTime().AddHours(9) } } catch {} }
  if (-not $dt) { continue }
  $tags = @{}
  foreach ($it in $s.item) {
    $subj = [string]$it.itemSubject; $type = ([string]$it.itemType).ToLower()
    if (-not $subj) { continue }
    $skip = $false; foreach ($p in $PII) { if ($subj.ToLower().Contains($p)) { $skip = $true } }
    if ($skip) { continue }
    $isChoice = $false; foreach ($c in $CHOICE) { if ($type.Contains($c)) { $isChoice = $true } }
    if (-not $isChoice) { continue }
    $val = ([string]$it.value).Trim()
    if (-not $val -and $it.valueList) { $val = ($it.valueList -join ', ') }
    if ($val -and $val.Length -le 40) { $tags[$subj] = $val }
  }
  $rows += [pscustomobject]@{
    d = $dt.ToString('yyyy-MM-dd'); h = $dt.Hour
    form = [string]$s.formName
    tags = $tags
  }
}
$rows = $rows | Sort-Object d, h

$monthly = @{}
foreach ($r in $rows) {
  $m = $r.d.Substring(0, 7)
  if (-not $monthly.ContainsKey($m)) { $monthly[$m] = @{} }
  $f = $r.form; if (-not $f) { $f = '문의' }
  if ($monthly[$m].ContainsKey($f)) { $monthly[$m][$f] = $monthly[$m][$f] + 1 } else { $monthly[$m][$f] = 1 }
}

$out = [ordered]@{
  generatedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  source      = 'imweb-api'
  site        = 'www.aqaralife.kr'
  unitCode    = $unit
  totalCount  = $rows.Count
  forms       = @($forms | ForEach-Object { [ordered]@{ formNo = $_.formNo; boardCode = $_.boardCode; name = [string]$_.formName } })
  monthly     = $monthly
  submissions = $rows
}
$json = $out | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($OUT_JSON, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ''
Write-Host ('homepage.json 생성 완료 : ' + $OUT_JSON) -ForegroundColor Green
Write-Host ('  문의 ' + $rows.Count + '건 · ' + $monthly.Keys.Count + '개월치') -ForegroundColor Green
Write-Host ''
Write-Host '이 파일을 GitHub에 올리면 대시보드 [홈페이지] 탭에 바로 표시됩니다.' -ForegroundColor Cyan
Write-Host '(git 자동 반영을 원하면 아래 명령을 web 폴더에서 실행)' -ForegroundColor DarkGray
Write-Host '  git add homepage.json; git commit -m "홈페이지 문의 데이터"; git push' -ForegroundColor DarkGray
Read-Host '엔터로 종료'
