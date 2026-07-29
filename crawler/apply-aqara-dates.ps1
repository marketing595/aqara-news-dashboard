# 아카라 카페 작성일·조회수(aqara_dates.json) → repo 반영 + 커밋/푸시
# 브라우저 콘솔 스니펫으로 내려받은 aqara_dates.json 을 찾아 web\ 에 넣고 GitHub에 올립니다.
$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.Encoding]::UTF8
$web = Split-Path -Parent $PSScriptRoot   # ...\web

Write-Host '=== 아카라 카페 작성일·조회수 반영 ===' -ForegroundColor Cyan

# 1) 다운로드된 aqara_dates.json 찾기 (인자 > 다운로드폴더 > 크롤러폴더)
$cands = @()
if ($args.Count -ge 1) { $cands += $args[0] }
$cands += (Join-Path $env:USERPROFILE 'Downloads\aqara_dates.json')
$cands += (Join-Path $PSScriptRoot 'aqara_dates.json')
$file = $cands | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $file) {
    Write-Host "`n[X] aqara_dates.json 을 찾지 못했습니다." -ForegroundColor Red
    Write-Host '    먼저 크롬 cafe.naver.com/aqara 에서 콘솔 스니펫을 실행해 파일을 내려받으세요.'
    Read-Host "`nEnter 키를 누르면 닫힙니다"; exit 1
}
Write-Host "찾은 파일: $file"

# 2) 검증
try { $j = Get-Content -Raw -Encoding UTF8 $file | ConvertFrom-Json }
catch { Write-Host '[X] 올바른 JSON이 아닙니다.' -ForegroundColor Red; Read-Host 'Enter'; exit 1 }
$cnt = ($j.dates.PSObject.Properties | Measure-Object).Count
if ($cnt -lt 1) { Write-Host '[X] 수집된 글이 0건입니다.' -ForegroundColor Red; Read-Host 'Enter'; exit 1 }
Write-Host "수집 건수: $cnt 건" -ForegroundColor Green

# 3) web\ 로 복사
$dest = Join-Path $web 'aqara_dates.json'
Copy-Item $file $dest -Force
Write-Host "복사 완료 → $dest"

# 4) git 커밋 + 푸시
Set-Location $web
git add aqara_dates.json | Out-Null
$status = git status --porcelain aqara_dates.json
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "`n변경 사항 없음(직전과 동일). 대시보드는 이미 최신입니다." -ForegroundColor Yellow
    Read-Host "`nEnter 키를 누르면 닫힙니다"; exit 0
}
git commit -m "aqara 카페 작성일·조회수 갱신 ($cnt건)" | Out-Null
try { git pull --rebase origin main | Out-Null } catch { }
git push origin main
if ($?) {
    Write-Host "`n[OK] 반영 완료! 1~2분 뒤 대시보드 카페 글에 실제 작성일·조회수가 표시됩니다." -ForegroundColor Green
} else {
    Write-Host "`n[!] 푸시 실패. 인터넷/깃 로그인 상태를 확인하세요." -ForegroundColor Red
}
Read-Host "`nEnter 키를 누르면 닫힙니다"
