param(
    [string]$ProjectDir = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $ProjectDir "deploy_github_pages"
}

$syncScript = Join-Path $ProjectDir "atualizar_landing_config.ps1"
if (Test-Path $syncScript) {
    & $syncScript -ProjectDir $ProjectDir | Out-Null
}

$filesToCopy = @(
    @{ Source = "index.html"; Target = "index.html" },
    @{ Source = "login.html"; Target = "login.html" },
    @{ Source = "dashboard.html"; Target = "dashboard.html" },
    @{ Source = "sync.html"; Target = "sync.html" },
    @{ Source = "app.html"; Target = "app.html" },
    @{ Source = "clients.html"; Target = "clients.html" },
    @{ Source = "agendamentos.html"; Target = "agendamentos.html" },
    @{ Source = "auth_web.js"; Target = "auth_web.js" },
    @{ Source = "landing_page_config.js"; Target = "landing_page_config.js" }
)

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

New-Item -ItemType File -Path (Join-Path $OutputDir ".nojekyll") -Force | Out-Null

$staleTargets = @(
    "landing_page.html",
    "landing_page.css"
)

foreach ($staleTarget in $staleTargets) {
    $stalePath = Join-Path $OutputDir $staleTarget
    if (Test-Path $stalePath) {
        Remove-Item -Path $stalePath -Force -ErrorAction SilentlyContinue
    }
}

foreach ($item in $filesToCopy) {
    $sourcePath = Join-Path $ProjectDir $item.Source
    if (-not (Test-Path $sourcePath)) {
        throw "Arquivo obrigatorio nao encontrado: $($item.Source)"
    }

    $targetPath = Join-Path $OutputDir $item.Target
    try {
        Copy-Item -Path $sourcePath -Destination $targetPath -Force
    }
    catch {
        throw "Falha ao copiar $($item.Source). Se o projeto estiver no OneDrive, marque o arquivo como disponivel offline antes de gerar o pacote do GitHub Pages. Detalhe: $($_.Exception.Message)"
    }
}

$assetsSource = Join-Path $ProjectDir "assets"
if (Test-Path $assetsSource) {
    try {
        Copy-Item -Path $assetsSource -Destination (Join-Path $OutputDir "assets") -Recurse -Force
    }
    catch {
        throw "Falha ao copiar a pasta assets. Se ela estiver somente na nuvem, marque-a como disponivel offline no OneDrive antes de gerar o pacote. Detalhe: $($_.Exception.Message)"
    }
}

Write-Host "[OK] Pacote pronto para GitHub Pages em $OutputDir"