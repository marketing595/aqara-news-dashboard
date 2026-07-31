#Requires -Version 5.1
<#
  아임웹 관리자 엑셀 → web/homepage.json  (API 연동 없이 쓰는 수동 방법)

  사용법
   1) 아임웹 관리자 > 게시판(입력폼) > 문의하기 / 소비자 인테리어 문의 에서 [엑셀 다운로드]
   2) 받은 .xlsx 파일들을 한 폴더에 모아둔다 (파일 이름이 대시보드에 '문의 폼 이름'으로 표시됨)
   3) 이 스크립트 실행 → 폴더 경로 입력 → homepage.json 생성

  ※ 개인정보(이름·연락처·내용)는 읽지 않고, '접수 날짜'만 세어서 건수로 집계한다.
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$WEB_DIR  = Split-Path -Parent $PSScriptRoot
$OUT_JSON = Join-Path $WEB_DIR 'homepage.json'
$DATE_HINTS = @('작성일', '등록일', '제출일', '접수일', '신청일', '날짜', '일시', 'date', 'time')

Write-Host ''
Write-Host '=== 아임웹 엑셀 → 홈페이지 문의 집계 ===' -ForegroundColor Yellow
Write-Host ''

$dir = Read-Host ('엑셀(.xlsx) 폴더 경로 [' + [Environment]::GetFolderPath('UserProfile') + '\Downloads]')
if ([string]::IsNullOrWhiteSpace($dir)) { $dir = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Downloads' }
if (-not (Test-Path $dir)) { Write-Host '폴더를 찾을 수 없습니다.' -ForegroundColor Red; Read-Host '엔터로 종료'; exit 1 }

$files = @(Get-ChildItem -Path $dir -Filter *.xls* -File | Where-Object { $_.Name -notlike '~$*' })
if ($files.Count -eq 0) { Write-Host '엑셀 파일이 없습니다.' -ForegroundColor Red; Read-Host '엔터로 종료'; exit 1 }
Write-Host ('엑셀 ' + $files.Count + '개 발견') -ForegroundColor Cyan

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$rows = @()

try {
  foreach ($f in $files) {
    Write-Host ('  읽는 중: ' + $f.Name) -ForegroundColor DarkGray
    $formName = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
    $wb = $excel.Workbooks.Open($f.FullName, 0, $true)
    $ws = $wb.Worksheets.Item(1)
    $used = $ws.UsedRange
    $nRow = $used.Rows.Count; $nCol = $used.Columns.Count
    if ($nRow -lt 2) { $wb.Close($false); continue }

    # 헤더에서 날짜 컬럼 찾기
    $dateCol = 0
    for ($c = 1; $c -le $nCol; $c++) {
      $h = [string]$ws.Cells.Item(1, $c).Text
      foreach ($hint in $DATE_HINTS) { if ($h -and $h.ToLower().Contains($hint)) { $dateCol = $c; break } }
      if ($dateCol) { break }
    }
    if (-not $dateCol) {
      # 헤더로 못 찾으면 2행에서 날짜처럼 보이는 첫 컬럼
      for ($c = 1; $c -le $nCol; $c++) {
        $v = [string]$ws.Cells.Item(2, $c).Text
        if ($v -match '\d{4}[-./]\d{1,2}[-./]\d{1,2}') { $dateCol = $c; break }
      }
    }
    if (-not $dateCol) { Write-Host ('    → 날짜 열을 찾지 못해 건너뜁니다: ' + $f.Name) -ForegroundColor Red; $wb.Close($false); continue }

    $cnt = 0
    for ($r = 2; $r -le $nRow; $r++) {
      $raw = [string]$ws.Cells.Item($r, $dateCol).Text
      if (-not $raw) { continue }
      $d = $null; $h = $null
      if ($raw -match '(\d{4})[-./](\d{1,2})[-./](\d{1,2})') {
        $d = '{0:0000}-{1:00}-{2:00}' -f [int]$matches[1], [int]$matches[2], [int]$matches[3]
        if ($raw -match '(\d{1,2}):(\d{2})') { $h = [int]$matches[1] }
      }
      if (-not $d) { continue }
      $rows += [pscustomobject]@{ d = $d; h = $h; form = $formName; tags = @{} }
      $cnt++
    }
    Write-Host ('    → ' + $cnt + '건') -ForegroundColor DarkGray
    $wb.Close($false)
  }
} finally {
  $excel.Quit()
  [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
}

if ($rows.Count -eq 0) { Write-Host '집계된 문의가 없습니다.' -ForegroundColor Red; Read-Host '엔터로 종료'; exit 1 }
$rows = $rows | Sort-Object d, h

$monthly = @{}
foreach ($r in $rows) {
  $m = $r.d.Substring(0, 7)
  if (-not $monthly.ContainsKey($m)) { $monthly[$m] = @{} }
  if ($monthly[$m].ContainsKey($r.form)) { $monthly[$m][$r.form] = $monthly[$m][$r.form] + 1 } else { $monthly[$m][$r.form] = 1 }
}
$formNames = @($rows | Select-Object -ExpandProperty form -Unique)

$out = [ordered]@{
  generatedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  source      = 'excel'
  site        = 'www.aqaralife.kr'
  totalCount  = $rows.Count
  forms       = @($formNames | ForEach-Object { [ordered]@{ formNo = $null; boardCode = ''; name = $_ } })
  monthly     = $monthly
  submissions = $rows
}
$json = $out | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($OUT_JSON, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ''
Write-Host ('homepage.json 생성 완료 : ' + $OUT_JSON) -ForegroundColor Green
Write-Host ('  문의 ' + $rows.Count + '건 · ' + $monthly.Keys.Count + '개월치 · 폼 ' + $formNames.Count + '개') -ForegroundColor Green
Write-Host ''
$push = Read-Host 'GitHub에 바로 반영할까요? (Y/N)'
if ($push -match '^[Yy]') {
  Push-Location $WEB_DIR
  git add homepage.json
  git commit -m "홈페이지 문의 데이터 갱신(엑셀)"
  git push
  Pop-Location
  Write-Host '푸시 완료 — 잠시 후 대시보드에 반영됩니다.' -ForegroundColor Green
}
Read-Host '엔터로 종료'
