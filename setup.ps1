# setup.ps1 — Research Agent 로컬 설치 및 실행 스크립트
# 사용법: .\setup.ps1
# PowerShell 5.1 이상 필요 (Windows 10/11 기본 탑재)

$ErrorActionPreference = "Stop"
$ComposeFile = "docker/docker-compose.yml"

# ── 색상 출력 헬퍼 ────────────────────────────────────────────────────────────
function Write-Banner($msg) {
    Write-Host ""
    Write-Host "━━━ $msg ━━━" -ForegroundColor Cyan -BackgroundColor Black
}
function Write-Ok($msg)   { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  ⚠  $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  ✗  $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "  → $msg" -ForegroundColor Blue }

# ── .env 파일 파싱 ────────────────────────────────────────────────────────────
function Get-EnvValue($key) {
    if (-not (Test-Path .env)) { return "" }
    $line = Get-Content .env | Where-Object { $_ -match "^$key=" } | Select-Object -First 1
    if ($line) { return ($line -split "=", 2)[1].Trim('"').Trim("'") }
    return ""
}

function Set-EnvValue($key, $value) {
    $content = if (Test-Path .env) { Get-Content .env -Raw } else { "" }
    if ($content -match "(?m)^$key=") {
        $content = $content -replace "(?m)^$key=.*", "$key=$value"
    } else {
        $content = $content.TrimEnd() + "`n$key=$value`n"
    }
    Set-Content .env $content -NoNewline -Encoding utf8
}

# ── URL 응답 대기 ─────────────────────────────────────────────────────────────
function Wait-Url($url, $name, $maxWait = 180) {
    $elapsed = 0
    Write-Host -NoNewline ("  {0,-30}" -f "$name 응답 대기 중")
    while ($elapsed -lt $maxWait) {
        try {
            $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($r.StatusCode -lt 400) {
                Write-Host " ✓" -ForegroundColor Green
                return $true
            }
        } catch {}
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 3
        $elapsed += 3
    }
    Write-Host " 타임아웃 (${maxWait}s)" -ForegroundColor Yellow
    return $false
}

# ── docker compose ps에서 "healthy" 대기 ─────────────────────────────────────
function Wait-ServiceHealthy($service, $maxWait = 600) {
    $elapsed = 0
    Write-Host -NoNewline ("  {0,-30}" -f "$service 준비 대기 중")
    while ($elapsed -lt $maxWait) {
        $ps = docker compose -f $ComposeFile ps $service | Out-String
        if ($ps -match "healthy" -and $ps -notmatch "starting|unhealthy") {
            Write-Host " ✓" -ForegroundColor Green
            return $true
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 5
        $elapsed += 5
    }
    Write-Host " 타임아웃 (${maxWait}s)" -ForegroundColor Yellow
    return $false
}

# ═════════════════════════════════════════════════════════════════════════════
Write-Banner "사전 요구사항 확인"

# Docker 실행 확인
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Err "Docker가 실행 중이지 않습니다."
    Write-Err "Docker Desktop을 시작한 후 다시 실행하세요."
    exit 1
}
Write-Ok "Docker 실행 중"

# docker compose v2 확인
$composeVer = docker compose version
if (-not $?) {
    Write-Err "docker compose (v2)를 찾을 수 없습니다."
    Write-Err "Docker Desktop을 최신 버전으로 업데이트하세요."
    exit 1
}
Write-Ok "docker compose 확인 ($composeVer)"

# ═════════════════════════════════════════════════════════════════════════════
Write-Banner ".env 설정"

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Ok ".env.example → .env 복사 완료"
} else {
    Write-Ok ".env 파일 존재"
}

# OpenRouter API 키 확인
$apiKey = Get-EnvValue "OPENROUTER_API_KEY"
if ([string]::IsNullOrWhiteSpace($apiKey) -or $apiKey -eq "your_openrouter_api_key_here") {
    Write-Host ""
    Write-Warn "OPENROUTER_API_KEY가 설정되지 않았습니다."
    Write-Info "https://openrouter.ai/keys 에서 발급 가능"
    $inputKey = Read-Host "  API 키를 입력하세요 (sk-or-...)"
    if ([string]::IsNullOrWhiteSpace($inputKey)) {
        Write-Err "API 키 없이는 실행할 수 없습니다. .env에 OPENROUTER_API_KEY를 입력 후 다시 실행하세요."
        exit 1
    }
    Set-EnvValue "OPENROUTER_API_KEY" $inputKey
    Write-Ok "OPENROUTER_API_KEY 저장 완료"
} else {
    Write-Ok "OPENROUTER_API_KEY 확인 ($($apiKey.Substring(0, [Math]::Min(12,$apiKey.Length)))...)"
}

# ntfy 설정값 읽기 (기본값 fallback)
$ntfyPass  = if (Get-EnvValue "NTFY_PASS")  { Get-EnvValue "NTFY_PASS" }  else { "changeme" }
$ntfyUser  = if (Get-EnvValue "NTFY_USER")  { Get-EnvValue "NTFY_USER" }  else { "admin" }
$ntfyTopic = if (Get-EnvValue "NTFY_TOPIC") { Get-EnvValue "NTFY_TOPIC" } else { "research-agent" }

if ($ntfyPass -eq "changeme") {
    Write-Warn "NTFY_PASS가 기본값(changeme)입니다. .env에서 변경을 권장합니다."
}

# ═════════════════════════════════════════════════════════════════════════════
Write-Banner "로컬 Python 환경 설정"

if (-not (Test-Path "tools")) {
    python -m venv tools
    Write-Ok "tools 가상환경 생성 완료"
} else {
    Write-Ok "tools 가상환경 존재"
}

.\tools\Scripts\pip.exe install --quiet -r requirements.txt
Write-Ok "패키지 설치 완료 (tools 가상환경)"

# ═════════════════════════════════════════════════════════════════════════════
Write-Banner "Step 1/4 — ntfy 서버 시작"

docker compose -f $ComposeFile up -d ntfy
Wait-Url "http://localhost:8080/v1/health" "ntfy" | Out-Null

# ═════════════════════════════════════════════════════════════════════════════
Write-Banner "Step 2/4 — ntfy 유저 설정"

# user add는 이미 존재하면 오류를 내므로 결과와 무관하게 access까지 실행
# (재실행 시에도 안전: 이미 존재하면 user add만 실패하고 나머지 진행)
Write-Info "ntfy 유저 '$ntfyUser' 확인/생성 중..."
$initCmd = "printf '%s\n%s\n' '$ntfyPass' '$ntfyPass' | ntfy user add --role=admin '$ntfyUser' 2>/dev/null; ntfy access '$ntfyUser' '$ntfyTopic' rw 2>/dev/null; true"
docker compose -f $ComposeFile exec -T ntfy sh -c $initCmd | Out-Null
Write-Ok "ntfy 유저 설정 완료"

# ═════════════════════════════════════════════════════════════════════════════
Write-Banner "Step 3/4 — 전체 서비스 빌드 및 시작"

Write-Host ""
Write-Info "이미지 빌드 예상 시간:"
Write-Info "  dashboard  : ~2분"
Write-Info "  latex      : ~5분 (xelatex + 한국어 폰트)"
Write-Info "  mcp 서버들 : ~1분"
Write-Host ""

docker compose -f $ComposeFile up -d --build

# ═════════════════════════════════════════════════════════════════════════════
Write-Banner "Step 4/4 — 서비스 준비 대기"

Write-Host ""
Write-Info "latex 서비스는 xelatex 패키지 설치로 인해 처음 빌드 시 오래 걸립니다."
Write-Host ""

Wait-ServiceHealthy "latex" 600  | Out-Null
Wait-Url "http://localhost:8000" "dashboard" 120 | Out-Null

# ═════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  설치 완료!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
Write-Host "  대시보드   " -NoNewline; Write-Host "http://localhost:8000" -ForegroundColor Cyan
Write-Host "  ntfy UI    " -NoNewline; Write-Host "http://localhost:8080" -ForegroundColor Cyan
Write-Host ""
Write-Host "  서비스 확인 : " -NoNewline
Write-Host "docker compose -f docker/docker-compose.yml ps" -ForegroundColor Blue
Write-Host "  로그 보기   : " -NoNewline
Write-Host "docker compose -f docker/docker-compose.yml logs -f" -ForegroundColor Blue
Write-Host "  종료        : " -NoNewline
Write-Host "docker compose -f docker/docker-compose.yml down" -ForegroundColor Blue
Write-Host ""

# 브라우저 자동 열기
Start-Process "http://localhost:8000"
