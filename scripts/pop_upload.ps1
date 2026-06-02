<#
.SYNOPSIS
    Publish or Perish 검색 결과 CSV를 Research Agent 대시보드에 업로드합니다.

.DESCRIPTION
    워크플로:
      1. Publish or Perish GUI에서 원하는 소스(Google Scholar, Web of Science 등)로 검색
      2. File → Export → CSV로 내보내기
      3. 이 스크립트에 CSV 경로와 연구 주제를 지정해서 실행
      4. 스크립트가 대시보드에 태스크 생성 + CSV 업로드를 자동 처리

    지원 소스 (PoP GUI에서 선택):
      - Google Scholar
      - Web of Science
      - Scopus
      - PubMed
      - CrossRef
      - Microsoft Academic
      - Lens.org
      - 기타 PoP 지원 소스

.EXAMPLE
    .\scripts\pop_upload.ps1 -CsvPath "C:\Downloads\pop_results.csv" -Topic "Efficient Transformer Attention"

.EXAMPLE
    .\scripts\pop_upload.ps1 -CsvPath ".\pop_results.csv" -Topic "그래프 신경망 추천 시스템" -DashboardUrl "http://localhost:8000"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$CsvPath,

    [Parameter(Mandatory=$true)]
    [string]$Topic,

    [string]$DashboardUrl = "http://localhost:8000",

    [switch]$Preview   # 업로드 없이 파싱 결과만 미리보기
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── 1. CSV 파일 검증 ──────────────────────────────────────────────────────────
if (-not (Test-Path $CsvPath)) {
    Write-Error "파일을 찾을 수 없습니다: $CsvPath"
    exit 1
}

$file = Get-Item $CsvPath
Write-Host ""
Write-Host "━━━ Publish or Perish CSV 업로드 ━━━" -ForegroundColor Cyan
Write-Host "  파일: $($file.FullName)"
Write-Host "  크기: $([math]::Round($file.Length / 1KB, 1)) KB"
Write-Host "  주제: $Topic"
Write-Host ""

# ── 2. CSV 미리보기 (첫 5행) ──────────────────────────────────────────────────
try {
    $rows = Import-Csv -Path $CsvPath -Encoding UTF8 | Select-Object -First 5
    $total = (Import-Csv -Path $CsvPath -Encoding UTF8 | Measure-Object).Count
    Write-Host "  파싱된 논문 수: $total 편" -ForegroundColor Green

    if ($rows.Count -gt 0) {
        Write-Host ""
        Write-Host "  [미리보기 — 상위 5편]"
        $i = 1
        foreach ($row in $rows) {
            $title   = if ($row.Title)   { $row.Title }   elseif ($row.TI) { $row.TI } else { "(제목 없음)" }
            $authors = if ($row.Authors) { $row.Authors } elseif ($row.AU) { $row.AU } else { "" }
            $year    = if ($row.Year)    { $row.Year }    elseif ($row.PY) { $row.PY } else { "" }
            $cites   = if ($row.Cites)   { $row.Cites }   elseif ($row.TC) { $row.TC } else { "" }
            Write-Host "  $i. $($title.Substring(0, [math]::Min(70, $title.Length)))..." -ForegroundColor White
            Write-Host "     $year  |  인용: $cites  |  $($authors.Substring(0, [math]::Min(50, $authors.Length)))" -ForegroundColor DarkGray
            $i++
        }
    }
} catch {
    Write-Warning "CSV 미리보기 실패 (업로드는 계속 진행): $_"
}

if ($Preview) {
    Write-Host ""
    Write-Host "  [미리보기 모드] 업로드를 건너뜁니다." -ForegroundColor Yellow
    exit 0
}

# ── 3. 대시보드 연결 확인 ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "  대시보드 연결 확인 중... ($DashboardUrl)"
try {
    $null = Invoke-WebRequest -Uri "$DashboardUrl/" -UseBasicParsing -TimeoutSec 5
} catch {
    Write-Error "대시보드에 연결할 수 없습니다: $DashboardUrl`n대시보드가 실행 중인지 확인하세요 (.\startup.ps1)"
    exit 1
}

# ── 4. 태스크 생성 ────────────────────────────────────────────────────────────
Write-Host "  태스크 생성 중..."
$body = @{ topic = $Topic; note_md = "" } | ConvertTo-Json -Compress
try {
    $taskRes = Invoke-RestMethod -Uri "$DashboardUrl/api/tasks" `
        -Method POST `
        -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
        -TimeoutSec 15
} catch {
    Write-Error "태스크 생성 실패: $_"
    exit 1
}

$taskId = $taskRes.id
Write-Host "  태스크 생성 완료: ID=$taskId" -ForegroundColor Green

# ── 5. PoP CSV 업로드 ─────────────────────────────────────────────────────────
Write-Host "  PoP CSV 업로드 중..."

# PowerShell 5.1은 multipart/form-data를 기본 지원하지 않아 직접 구성
$boundary = [System.Guid]::NewGuid().ToString("N")
$fileBytes = [System.IO.File]::ReadAllBytes($file.FullName)
$fileName  = $file.Name

$bodyParts = [System.Text.Encoding]::UTF8.GetBytes(
    "--$boundary`r`nContent-Disposition: form-data; name=`"file`"; filename=`"$fileName`"`r`nContent-Type: text/csv`r`n`r`n"
)
$bodyEnd = [System.Text.Encoding]::UTF8.GetBytes("`r`n--$boundary--`r`n")

$multipartBody = $bodyParts + $fileBytes + $bodyEnd

try {
    $popRes = Invoke-RestMethod -Uri "$DashboardUrl/api/tasks/$taskId/pop" `
        -Method POST `
        -ContentType "multipart/form-data; boundary=$boundary" `
        -Body $multipartBody `
        -TimeoutSec 30
    Write-Host "  PoP CSV 업로드 완료: $($popRes.papers_found)편 인식" -ForegroundColor Green
} catch {
    Write-Warning "PoP CSV 업로드 실패 (태스크는 자동 검색으로 진행됩니다): $_"
}

# ── 6. 완료 안내 ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  완료! 대시보드에서 진행 상황을 확인하세요:" -ForegroundColor Green
Write-Host "  $DashboardUrl" -ForegroundColor White
Write-Host ""
Write-Host "  태스크 ID : $taskId"
Write-Host "  주제      : $Topic"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
