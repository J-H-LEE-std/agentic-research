# shutdown.ps1 — Research Agent 서비스 종료 스크립트
# 사용법: .\shutdown.ps1 [-Volumes]
#   -Volumes  컨테이너와 함께 볼륨(데이터)도 삭제
param(
    [switch]$Volumes
)

$ErrorActionPreference = "Stop"
$ComposeFile = "docker/docker-compose.yml"

function Write-Banner($msg) {
    Write-Host ""
    Write-Host "━━━ $msg ━━━" -ForegroundColor Cyan -BackgroundColor Black
}
function Write-Ok($msg)   { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  ⚠  $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  ✗  $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "  → $msg" -ForegroundColor Blue }

# ── Docker 확인 ───────────────────────────────────────────────────────────────
Write-Banner "서비스 종료"

try {
    docker info 2>$null | Out-Null
} catch {
    Write-Err "Docker가 실행 중이지 않습니다. 서비스가 이미 꺼져 있을 수 있습니다."
    exit 1
}

# 실행 중인 서비스 확인
$running = docker compose -f $ComposeFile ps --services --filter "status=running" 2>$null
if ([string]::IsNullOrWhiteSpace($running)) {
    Write-Warn "실행 중인 서비스가 없습니다."
    exit 0
}

Write-Info "종료할 서비스:"
$running -split "`n" | Where-Object { $_ -ne "" } | ForEach-Object {
    Write-Host "    - $_"
}
Write-Host ""

if ($Volumes) {
    Write-Warn "볼륨 포함 삭제 (-Volumes): ntfy 유저 데이터 등이 함께 삭제됩니다."
    docker compose -f $ComposeFile down --volumes
} else {
    docker compose -f $ComposeFile down
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  종료 완료!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
if ($Volumes) {
    Write-Ok "컨테이너 및 볼륨 삭제 완료"
} else {
    Write-Ok "컨테이너 종료 완료 (데이터 보존)"
    Write-Info "데이터까지 삭제하려면: .\shutdown.ps1 -Volumes"
}
Write-Host ""
