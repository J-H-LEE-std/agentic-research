<#
.SYNOPSIS
    Publish or Perish CLI(pop8query)로 논문을 검색하고 대시보드에 업로드합니다.

.DESCRIPTION
    pop8query를 로컬에서 실행해 CSV를 생성한 뒤, Research Agent 대시보드에
    태스크를 만들고 CSV를 업로드합니다.
    라이선스 조항에 따라 PoP 소프트웨어는 서버에 배포하지 않으며 로컬에서만 실행합니다.

.PARAMETER Topic
    연구 주제 (대시보드 태스크 이름으로도 사용)

.PARAMETER Keywords
    pop8query --keywords 로 전달할 검색어. 미지정 시 Topic을 사용.

.PARAMETER Author
    저자 검색 (--author). Keywords 대신 또는 함께 사용 가능.

.PARAMETER Source
    데이터 소스. 기본값: gscholar
    선택: gscholar, gsauthor, scopus, crossref, pubmed, openalex, lens, semscholar, wos

.PARAMETER Years
    연도 범위 (예: 2018-2025). 미지정 시 전체 기간.

.PARAMETER MaxResults
    최대 결과 수. 기본값: 100

.PARAMETER OutputDir
    CSV 저장 디렉토리. 기본값: .\pop_exports

.PARAMETER DashboardUrl
    대시보드 주소. 기본값: http://localhost:8000

.PARAMETER NoUpload
    CSV 생성만 하고 업로드는 건너뜁니다.

.EXAMPLE
    .\scripts\pop_search.ps1 -Topic "Efficient Transformer Attention" -Source gscholar

.EXAMPLE
    .\scripts\pop_search.ps1 -Topic "그래프 신경망" -Keywords "graph neural network recommendation" -Source openalex -Years 2020-2025 -MaxResults 200

.EXAMPLE
    .\scripts\pop_search.ps1 -Topic "Attention Mechanism" -Source scopus -NoUpload
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$Topic,

    [string]$Keywords    = "",
    [string]$Author      = "",

    [ValidateSet("gscholar","gsauthor","scopus","crossref","pubmed","openalex","lens","semscholar","wos","wosexpanded","wosstarter")]
    [string]$Source      = "gscholar",

    [string]$Years       = "",
    [int]$MaxResults     = 100,
    [string]$OutputDir   = ".\pop_exports",
    [string]$DashboardUrl= "http://localhost:8000",
    [switch]$NoUpload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── 1. pop8query 실행 파일 탐색 ───────────────────────────────────────────────
$PopCmd = $null

# PATH에서 먼저 찾기
if (Get-Command pop8query -ErrorAction SilentlyContinue) {
    $PopCmd = "pop8query"
} else {
    # 일반적인 Windows 설치 경로 후보
    $candidates = @(
        "$env:LOCALAPPDATA\Publish or Perish 8\pop8query.exe",
        "$env:PROGRAMFILES\Publish or Perish 8\pop8query.exe",
        "${env:PROGRAMFILES(X86)}\Publish or Perish 8\pop8query.exe",
        "$env:LOCALAPPDATA\Programs\Publish or Perish 8\pop8query.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $PopCmd = $c; break }
    }
}

if (-not $PopCmd) {
    Write-Error @"
pop8query를 찾을 수 없습니다.

해결 방법:
  1. https://harzing.com/resources/publish-or-perish 에서 PoP 8 설치
  2. 설치 후 pop8query.exe 경로를 PATH에 추가하거나
     스크립트 상단 candidates 배열에 경로를 추가하세요.
"@
    exit 1
}

Write-Host ""
Write-Host "━━━ Publish or Perish 검색 ━━━" -ForegroundColor Cyan
Write-Host "  실행 파일 : $PopCmd"
Write-Host "  소스      : $Source"
Write-Host "  주제      : $Topic"

# ── 2. 출력 파일 경로 설정 ────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$timestamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$safeTopic  = $Topic -replace '[\\/:*?"<>|]', '_'
$csvFile    = Join-Path (Resolve-Path $OutputDir) "pop_${Source}_${timestamp}.csv"

# ── 3. pop8query 인수 조립 ────────────────────────────────────────────────────
$args = @("--$Source")

$searchTerm = if ($Keywords) { $Keywords } else { $Topic }
if ($searchTerm) { $args += @("--keywords", "'$searchTerm'") }
if ($Author)     { $args += @("--author",   "'$Author'")     }
if ($Years)      { $args += @("--years",    $Years)          }
if ($MaxResults) { $args += @("--max",      $MaxResults)     }

$args += $csvFile   # 출력 파일 (확장자로 csv 자동 감지)

Write-Host "  검색어    : $searchTerm"
if ($Author) { Write-Host "  저자      : $Author" }
if ($Years)  { Write-Host "  연도      : $Years"  }
Write-Host "  최대 결과 : $MaxResults 편"
Write-Host "  출력 파일 : $csvFile"
Write-Host ""
Write-Host "  검색 중..." -ForegroundColor Yellow

# ── 4. pop8query 실행 ─────────────────────────────────────────────────────────
$proc = Start-Process -FilePath $PopCmd -ArgumentList $args -Wait -PassThru -NoNewWindow
$exitCode = $proc.ExitCode

function Show-CaptchaHelp {
    Write-Host ""
    Write-Host "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" -ForegroundColor Red
    Write-Host "  Google Scholar CAPTCHA — CLI 검색이 중단되었습니다" -ForegroundColor Red
    Write-Host "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" -ForegroundColor Red
    Write-Host ""
    Write-Host "  지금 바로 Publish or Perish GUI를 열어서" -ForegroundColor White
    Write-Host "  Google Scholar 검색을 한 번 실행하고" -ForegroundColor White
    Write-Host "  CAPTCHA를 풀어주세요." -ForegroundColor White
    Write-Host ""

    # GUI 자동 실행 시도
    $guiCandidates = @(
        "$env:LOCALAPPDATA\Publish or Perish 8\PoP8.exe",
        "$env:PROGRAMFILES\Publish or Perish 8\PoP8.exe",
        "${env:PROGRAMFILES(X86)}\Publish or Perish 8\PoP8.exe",
        "$env:LOCALAPPDATA\Programs\Publish or Perish 8\PoP8.exe"
    )
    $guiExe = $guiCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($guiExe) {
        Write-Host "  → GUI를 자동으로 실행합니다: $guiExe" -ForegroundColor Cyan
        Start-Process $guiExe
        Write-Host ""
        Write-Host "  PoP GUI에서 할 일:" -ForegroundColor Yellow
        Write-Host "    1. 상단 소스 드롭다운에서 'Google Scholar' 선택" -ForegroundColor Yellow
        Write-Host "    2. 아무 검색어로 검색 실행" -ForegroundColor Yellow
        Write-Host "    3. CAPTCHA 창이 뜨면 풀기" -ForegroundColor Yellow
        Write-Host "    4. 검색 결과가 나오면 GUI 닫기" -ForegroundColor Yellow
        Write-Host "    5. 이 스크립트 다시 실행" -ForegroundColor Yellow
    } else {
        Write-Host "  PoP GUI를 직접 실행해주세요 (시작 메뉴 → Publish or Perish)" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  PoP GUI에서 할 일:" -ForegroundColor Yellow
        Write-Host "    1. 상단 소스 드롭다운에서 'Google Scholar' 선택" -ForegroundColor Yellow
        Write-Host "    2. 아무 검색어로 검색 실행" -ForegroundColor Yellow
        Write-Host "    3. CAPTCHA 창이 뜨면 풀기" -ForegroundColor Yellow
        Write-Host "    4. 검색 결과가 나오면 GUI 닫기" -ForegroundColor Yellow
        Write-Host "    5. 이 스크립트 다시 실행" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" -ForegroundColor Red
    Write-Host ""
}

switch ($exitCode) {
    0 { Write-Host "  검색 완료!" -ForegroundColor Green }
    1 { Write-Error "pop8query 오류: 명령행 파라미터 또는 실행 오류 (exit 1)"; exit 1 }
    2 { Write-Error "pop8query 오류: 쿼리 문법 오류 (exit 2)"; exit 1 }
    3 {
        if ($Source -eq "gscholar") {
            Show-CaptchaHelp
            Write-Error "Google Scholar 검색 중단 — CAPTCHA 해결 후 재시도하세요 (exit 3)"
        } else {
            Write-Error "pop8query 오류: 데이터 소스 사용 불가 — API 키 설정이 필요할 수 있습니다 (exit 3)"
        }
        exit 1
    }
    4 { Write-Warning "검색 결과가 없습니다 (exit 4). 검색어를 확인하세요."; exit 0 }
    default { Write-Error "pop8query 알 수 없는 오류 (exit $exitCode)"; exit 1 }
}

if (-not (Test-Path $csvFile)) {
    if ($Source -eq "gscholar") {
        Show-CaptchaHelp
        Write-Error "CSV 파일이 생성되지 않았습니다. Google Scholar CAPTCHA로 인한 중단일 수 있습니다."
    } else {
        Write-Error "CSV 파일이 생성되지 않았습니다: $csvFile"
    }
    exit 1
}

# CSV가 생성됐지만 내용이 없는 경우 (CAPTCHA로 빈 결과 가능성)
$csvSize = (Get-Item $csvFile).Length
if ($csvSize -lt 10) {
    if ($Source -eq "gscholar") {
        Show-CaptchaHelp
        Write-Warning "CSV 파일이 비어 있습니다. Google Scholar CAPTCHA로 인한 중단일 수 있습니다."
    } else {
        Write-Warning "CSV 파일이 비어 있습니다: $csvFile"
    }
    exit 0
}

# ── 5. 결과 미리보기 ──────────────────────────────────────────────────────────
try {
    $rows  = Import-Csv -Path $csvFile -Encoding UTF8
    $total = $rows.Count
    Write-Host "  인식된 논문 수: $total 편"

    if ($total -gt 0) {
        Write-Host ""
        Write-Host "  [상위 5편]"
        $rows | Select-Object -First 5 | ForEach-Object {
            $t = if ($_.Title)   { $_.Title }   elseif ($_.TI) { $_.TI } else { "(제목 없음)" }
            $y = if ($_.Year)    { $_.Year }    elseif ($_.PY) { $_.PY } else { "    " }
            $c = if ($_.Cites)   { "인용:$($_.Cites)" } elseif ($_.TC) { "인용:$($_.TC)" } else { "" }
            Write-Host "  · [$y] $($t.Substring(0, [math]::Min(68, $t.Length)))  $c" -ForegroundColor White
        }
    }
} catch {
    Write-Warning "미리보기 파싱 실패 (업로드는 계속 진행): $_"
}

if ($NoUpload) {
    Write-Host ""
    Write-Host "  [NoUpload] 업로드를 건너뜁니다." -ForegroundColor Yellow
    Write-Host "  파일: $csvFile"
    exit 0
}

# ── 6. 대시보드 연결 확인 ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "  대시보드 연결 확인 중... ($DashboardUrl)"
try {
    $null = Invoke-WebRequest -Uri "$DashboardUrl/" -UseBasicParsing -TimeoutSec 5
} catch {
    Write-Error "대시보드에 연결할 수 없습니다.`n대시보드가 실행 중인지 확인하세요 (.\startup.ps1)"
    exit 1
}

# ── 7. 태스크 생성 ────────────────────────────────────────────────────────────
Write-Host "  태스크 생성 중..."
$body = @{ topic = $Topic; note_md = "" } | ConvertTo-Json -Compress
$taskRes = Invoke-RestMethod -Uri "$DashboardUrl/api/tasks" `
    -Method POST `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
    -TimeoutSec 15
$taskId = $taskRes.id
Write-Host "  태스크 생성 완료: ID=$taskId" -ForegroundColor Green

# ── 8. PoP CSV 업로드 (multipart/form-data) ───────────────────────────────────
Write-Host "  PoP CSV 업로드 중..."
$boundary  = [System.Guid]::NewGuid().ToString("N")
$fileBytes = [System.IO.File]::ReadAllBytes($csvFile)
$fileName  = [System.IO.Path]::GetFileName($csvFile)

$headerBytes = [System.Text.Encoding]::UTF8.GetBytes(
    "--$boundary`r`nContent-Disposition: form-data; name=`"file`"; filename=`"$fileName`"`r`nContent-Type: text/csv`r`n`r`n"
)
$footerBytes = [System.Text.Encoding]::UTF8.GetBytes("`r`n--$boundary--`r`n")
$multipart   = $headerBytes + $fileBytes + $footerBytes

$popRes = Invoke-RestMethod -Uri "$DashboardUrl/api/tasks/$taskId/pop" `
    -Method POST `
    -ContentType "multipart/form-data; boundary=$boundary" `
    -Body $multipart `
    -TimeoutSec 30
Write-Host "  PoP CSV 업로드 완료: $($popRes.papers_found)편 인식" -ForegroundColor Green

# ── 9. 완료 안내 ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  완료!" -ForegroundColor Green
Write-Host "  태스크 ID : $taskId  |  소스: $Source  |  논문: $($popRes.papers_found)편"
Write-Host "  대시보드  : $DashboardUrl"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
