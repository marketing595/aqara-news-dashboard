#Requires -Version 5.1
<#
  아카라라이프 자사 블로그(아임웹) 포스팅 — 검수용 '비공개 초안' 등록 전용
  imweb_publisher.py 의 PowerShell 판 (이 PC에는 Python이 없어 이 스크립트로 실행한다)

  안전장치: 어떤 경우에도 '공개'로 올리지 않는다. 항상 비공개(draft)로 등록하고,
            최종 발행은 아임웹 관리자 화면에서 사람이 누른다.

  사용법
    .\Publish-ImwebPost.ps1 -Check
    .\Publish-ImwebPost.ps1 -File "..\..\drafts\2026-09-27-aqara-smarthome-package.html" -DryRun
    .\Publish-ImwebPost.ps1 -File "..\..\drafts\2026-09-27-aqara-smarthome-package.html"

  설정 파일(.env) — 이 폴더 또는 상위 폴더. git에 올리지 말 것.
    IMWEB_API_MODE=legacy            # legacy(api.imweb.me/v2) 또는 oauth(openapi.imweb.me)
    IMWEB_API_KEY=...                # legacy
    IMWEB_SECRET_KEY=...             # legacy
    IMWEB_CLIENT_ID=...              # oauth
    IMWEB_CLIENT_SECRET=...          # oauth
    IMWEB_REFRESH_TOKEN=...          # oauth (Get-ImwebToken.ps1 로 발급)
    IMWEB_BOARD_CODE=...             # 글을 올릴 게시판 코드
    IMWEB_UNIT_CODE=...              # (선택)
    IMWEB_POSTS_PATH=/v2/board/posts # (선택) 엔드포인트 경로
    IMWEB_API_BASE=...               # (선택) 호스트 직접 지정
#>
param(
  [string]$File,
  [string]$Title,
  [string]$Board,
  [string]$EnvFile,
  [switch]$DryRun,
  [switch]$Check
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$LEGACY_BASE = 'https://api.imweb.me'
$OAUTH_BASE  = 'https://openapi.imweb.me'

# 아임웹이 게시판/버전마다 다른 이름을 쓰므로 비공개를 뜻하는 필드를 한 번에 채운다
$DRAFT = [ordered]@{ status = 'DRAFT'; isDraft = $true; isPublic = $false; is_notice = $false; isSecret = $true }

function Read-EnvFile($explicit) {
  $cands = if ($explicit) { @($explicit) } else {
    @((Join-Path $PSScriptRoot '.env'),
      (Join-Path (Split-Path -Parent $PSScriptRoot) '.env'),
      (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.env'))
  }
  foreach ($p in $cands) {
    if (-not (Test-Path $p)) { continue }
    foreach ($line in (Get-Content $p -Encoding UTF8)) {
      $t = $line.Trim()
      if (-not $t -or $t.StartsWith('#')) { continue }
      $i = $t.IndexOf('='); if ($i -lt 1) { continue }
      $k = $t.Substring(0, $i).Trim()
      $v = $t.Substring($i + 1).Trim().Trim('"').Trim("'")
      if ($k -and -not [Environment]::GetEnvironmentVariable($k)) { Set-Item -Path "env:$k" -Value $v }
    }
    return $p
  }
  return $null
}

function Ev($name) { $v = [Environment]::GetEnvironmentVariable($name); if ($v) { return $v.Trim() } return '' }

Write-Host ''
Write-Host '=== 아임웹 블로그 초안 등록 (비공개) ===' -ForegroundColor Yellow

$envPath = Read-EnvFile $EnvFile
$mode    = if (Ev 'IMWEB_API_MODE') { (Ev 'IMWEB_API_MODE').ToLower() } else { 'legacy' }
$board   = if ($Board) { $Board } else { Ev 'IMWEB_BOARD_CODE' }
$base    = if (Ev 'IMWEB_API_BASE') { Ev 'IMWEB_API_BASE' } elseif ($mode -eq 'oauth') { $OAUTH_BASE } else { $LEGACY_BASE }
$path    = if (Ev 'IMWEB_POSTS_PATH') { Ev 'IMWEB_POSTS_PATH' } else { '/v2/board/posts' }

$need = if ($mode -eq 'oauth') { @('IMWEB_CLIENT_ID','IMWEB_CLIENT_SECRET','IMWEB_REFRESH_TOKEN') } else { @('IMWEB_API_KEY','IMWEB_SECRET_KEY') }
$missing = @(); foreach ($k in $need) { if (-not (Ev $k)) { $missing += $k } }
if (-not $board) { $missing += 'IMWEB_BOARD_CODE' }

Write-Host ('  .env       : ' + $(if ($envPath) { $envPath } else { '(못 찾음)' })) -ForegroundColor DarkGray
Write-Host ('  방식       : ' + $mode) -ForegroundColor DarkGray
Write-Host ('  엔드포인트 : ' + $base + $path) -ForegroundColor DarkGray
Write-Host ('  게시판     : ' + $(if ($board) { $board } else { '(없음)' })) -ForegroundColor DarkGray
Write-Host ('  누락 설정  : ' + $(if ($missing.Count) { $missing -join ', ' } else { '없음' })) -ForegroundColor DarkGray

if ($Check) { exit $(if ($missing.Count) { 1 } else { 0 }) }
if ($missing.Count) { Write-Host ''; Write-Host '[중단] .env 에 위 값을 채운 뒤 다시 실행하세요.' -ForegroundColor Red; exit 1 }
if (-not $File)     { Write-Host ''; Write-Host '[중단] -File 로 원고 HTML을 지정하세요.' -ForegroundColor Red; exit 1 }
if (-not (Test-Path $File)) { Write-Host ''; Write-Host ('[중단] 파일을 찾을 수 없습니다: ' + $File) -ForegroundColor Red; exit 1 }

# ── 원고 읽기 : <h1>=제목, <body>=본문 ──
$raw = Get-Content -Raw -Path $File -Encoding UTF8
$t = ''
if ($raw -match '(?is)<h1[^>]*>(.*?)</h1>') { $t = $matches[1] }
elseif ($raw -match '(?is)<title[^>]*>(.*?)</title>') { $t = $matches[1] }
$t = ($t -replace '<[^>]+>', '').Trim()
if ($Title) { $t = $Title }

$content = $raw
if ($raw -match '(?is)<body[^>]*>(.*)</body>') { $content = $matches[1] }
$content = ([regex]'(?is)<h1[^>]*>.*?</h1>').Replace($content, '', 1).Trim()   # 제목 중복 제거

if (-not $t -or -not $content) { Write-Host '[중단] 제목 또는 본문을 읽지 못했습니다.' -ForegroundColor Red; exit 1 }

$payload = [ordered]@{ boardCode = $board; board_code = $board; title = $t; content = $content }
if (Ev 'IMWEB_CATEGORY')  { $payload['category'] = Ev 'IMWEB_CATEGORY' }
if (Ev 'IMWEB_AUTHOR')    { $payload['name']     = Ev 'IMWEB_AUTHOR' }
if (Ev 'IMWEB_UNIT_CODE') { $payload['unitCode'] = Ev 'IMWEB_UNIT_CODE' }
foreach ($k in $DRAFT.Keys) { $payload[$k] = $DRAFT[$k] }      # ★ 비공개 설정은 마지막에 덮어쓴다

Write-Host ''
Write-Host ('  제목       : ' + $t)
Write-Host ('  본문 길이  : ' + $content.Length + '자')
Write-Host ('  공개 상태  : 비공개(draft) — ' + (($DRAFT.Keys | ForEach-Object { "$_=$($DRAFT[$_])" }) -join ', ')) -ForegroundColor Cyan

if ($DryRun) {
  $preview = [ordered]@{}; foreach ($k in $payload.Keys) { $preview[$k] = $payload[$k] }
  $preview['content'] = $content.Substring(0, [Math]::Min(300, $content.Length)) + ' …(생략)'
  Write-Host ''
  Write-Host '[dry-run] 아래 내용을 전송하지 않고 종료합니다.' -ForegroundColor Yellow
  ($preview | ConvertTo-Json -Depth 5)
  exit 0
}

# ── 토큰 발급 ──
Write-Host ''
Write-Host '토큰 발급 중...' -ForegroundColor Cyan
if ($mode -eq 'oauth') {
  $tok = Invoke-RestMethod -Method Post -Uri "$base/oauth2/token" -ContentType 'application/x-www-form-urlencoded' `
    -Body @{ clientId = (Ev 'IMWEB_CLIENT_ID'); clientSecret = (Ev 'IMWEB_CLIENT_SECRET'); refreshToken = (Ev 'IMWEB_REFRESH_TOKEN'); grantType = 'refresh_token' }
  $access = $tok.data.accessToken
  if ($tok.data.refreshToken -and $tok.data.refreshToken -ne (Ev 'IMWEB_REFRESH_TOKEN')) {
    Write-Host '  ↻ refresh token이 갱신됐습니다. .env 의 IMWEB_REFRESH_TOKEN 을 바꾸세요:' -ForegroundColor Yellow
    Write-Host ('    ' + $tok.data.refreshToken) -ForegroundColor Yellow
  }
  $headers = @{ Authorization = "Bearer $access" }
} else {
  $tok = Invoke-RestMethod -Method Get -Uri ("$base/v2/auth?key=" + [uri]::EscapeDataString((Ev 'IMWEB_API_KEY')) + '&secret=' + [uri]::EscapeDataString((Ev 'IMWEB_SECRET_KEY')))
  $access = $tok.access_token
  if (-not $access -and $tok.data) { $access = $tok.data.access_token }
  $headers = @{ 'access-token' = $access }
}
if (-not $access) { Write-Host '[중단] 토큰 발급 실패.' -ForegroundColor Red; exit 1 }

# ── 등록 ──
Write-Host '게시글 등록 중...' -ForegroundColor Cyan
$json  = $payload | ConvertTo-Json -Depth 5 -Compress
$bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
try {
  $res = Invoke-RestMethod -Method Post -Uri ($base + $path) -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $bytes
} catch {
  Write-Host ''
  Write-Host ('[실패] ' + $_.Exception.Message) -ForegroundColor Red
  try {
    $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    Write-Host $sr.ReadToEnd() -ForegroundColor DarkGray
  } catch {}
  exit 1
}

function Find-Val($obj, $names) {
  foreach ($n in $names) {
    $p = $obj.PSObject.Properties[$n]
    if ($p -and $p.Value) { return [string]$p.Value }
  }
  foreach ($p in $obj.PSObject.Properties) {
    if ($p.Value -is [psobject] -and $p.Value.PSObject.Properties.Count) {
      $v = Find-Val $p.Value $names; if ($v) { return $v }
    }
  }
  return ''
}
$postId = Find-Val $res @('postId','post_id','idx','no','postNo','id')
$url    = Find-Val $res @('url','postUrl','link','permalink')

Write-Host ''
Write-Host '[완료] 비공개(draft) 상태로 등록했습니다.' -ForegroundColor Green
Write-Host ('  게시글 ID : ' + $(if ($postId) { $postId } else { '(응답에 없음)' }))
if ($url) { Write-Host ('  URL       : ' + $url) }
Write-Host ('  게시판    : ' + $board)
Write-Host ''
Write-Host '  ※ 아임웹 관리자 > 게시판에서 검수한 뒤 직접 공개로 바꿔 주세요.' -ForegroundColor Cyan
if (-not $postId -and -not $url) { Write-Host ''; ($res | ConvertTo-Json -Depth 6) }
