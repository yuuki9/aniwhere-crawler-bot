#Requires -Version 5.1
<#
  MySQL이 프라이빗 서브넷에 있을 때: 베스천을 경유해 로컬 포트로 포워딩합니다.

  (대안) 애플리케이션 내장 터널: .env 에 MYSQL_USE_SSH_TUNNEL=true 등 설정 시
  파이프라인/FastAPI가 sshtunnel 로 직접 띄웁니다. 이 스크립트는 수동 터널용입니다.

  흐름: 127.0.0.1:LocalPort → (SSH) → 베스천 → PrivateDbHost:PrivateDbPort

  사용 전 scripts\mysql-bastion-tunnel.ps1 안의 기본값을 실제 값으로 바꾸거나,
  아래처럼 매개변수로 넘기세요.

  예:
    .\scripts\mysql-bastion-tunnel.ps1 `
      -Bastion "ec2-user@1.2.3.4" `
      -PrivateDbHost "aniwhere.xxxx.ap-northeast-2.rds.amazonaws.com" `
      -PrivateDbPort 3306 `
      -LocalPort 25431 `
      -IdentityFile "$env:USERPROFILE\.ssh\your-key.pem"

  이 창은 터널이 유지되는 동안 그대로 둡니다. 끄려면 Ctrl+C.

  호스트에서 파이프라인/앱:
    MYSQL_HOST=127.0.0.1
    MYSQL_PORT=<LocalPort 와 동일>

  Docker (Docker Desktop Windows):
    docker compose run --rm `
      -e MYSQL_HOST=host.docker.internal `
      -e MYSQL_PORT=<LocalPort> `
      api python run_pipeline.py ...
#>

param(
    [Parameter(Mandatory = $false)]
    [string] $Bastion = "ec2-user@YOUR_BASTION_PUBLIC_IP_OR_DNS",

    [Parameter(Mandatory = $false)]
    [string] $PrivateDbHost = "YOUR_PRIVATE_DB_HOST_OR_RDS_ENDPOINT",

    [Parameter(Mandatory = $false)]
    [int] $PrivateDbPort = 3306,

    [Parameter(Mandatory = $false)]
    [int] $LocalPort = 25431,

    [Parameter(Mandatory = $false)]
    [string] $IdentityFile = ""
)

$sshCmd = @(
    "-N",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-L", "${LocalPort}:${PrivateDbHost}:${PrivateDbPort}",
    $Bastion
)

if ($IdentityFile -and (Test-Path -LiteralPath $IdentityFile)) {
    $sshCmd = @("-i", $IdentityFile) + $sshCmd
}

Write-Host ""
Write-Host "=== MySQL SSH tunnel ===" -ForegroundColor Cyan
Write-Host "  Listen:  127.0.0.1:$LocalPort"
Write-Host "  Target:  ${PrivateDbHost}:${PrivateDbPort} (via bastion $Bastion)"
Write-Host ""
Write-Host "  Host app:  MYSQL_HOST=127.0.0.1  MYSQL_PORT=$LocalPort"
Write-Host "  Docker:    MYSQL_HOST=host.docker.internal  MYSQL_PORT=$LocalPort"
Write-Host ""
Write-Host "Starting ssh... (Ctrl+C to stop)" -ForegroundColor Yellow
Write-Host ""

& ssh @sshCmd
