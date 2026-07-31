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
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$BASE        = 'https://openapi.imweb.me'
$REDIRECT    = 'https://aqara-news-dashboard.vercel.app/imweb-auth.html'
$SCOPE       = 'community:read site-info:read'
$DEFAULT_SITE = 'S202509250f66ad55637e1'   # 아카라라이프 아임웹 사이트 코드(자동 확인값)
$WEB_DIR     = Split-Path -Parent $PSScriptRoot
$OUT_JSON    = Join-Path $WEB_DIR 'homepage.json'

function Ask($label, $default) {
  if ($default) { $v = Read-Host "$label [$default]"; if ([string]::IsNullOrWhiteSpace($v)) { return $default }; return $v.Trim() }
  do { $v = Read-Host $label } while ([string]::IsNullOrWhiteSpace($v))
  return $v.Trim()
}

Write-Host ''
Write-Host '=== 아임웹 홈페이지 문의 연동 · 토큰 발급 ===' -ForegroundColor Yellow
Write-Host ''

$clientId     = Ask '1) Client ID' $null
$clientSecret = Ask '2) Client Secret' $null
$siteCode     = Ask '3) 사이트 코드' $DEFAULT_SITE

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
Write-Host '허용하면 대시보드의 인증 코드 페이지로 이동합니다. 화면에 뜬 코드를 복사해 붙여넣으세요.'
$code = Ask '4) 인증 코드(code)' $null

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

# ---- 유닛 코드 확인 ----
$hdr = @{ Authorization = "Bearer $access" }
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
