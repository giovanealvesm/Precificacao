# Inicializacao silenciosa do CRM Pro + Cloudflare + envio de link
param(
    [string]$ProjectDir = ""
)

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

Set-Location $ProjectDir

$startupLog = Join-Path $ProjectDir "startup_log.txt"
$envFile = Join-Path $ProjectDir ".env"

function Load-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    Get-Content $Path -ErrorAction SilentlyContinue | ForEach-Object {
        $line = $_.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }

        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if (-not [string]::IsNullOrWhiteSpace($key)) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Log-Info {
    param([string]$Message)
    "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) [INFO] $Message" | Out-File -FilePath $startupLog -Append -Encoding UTF8
}

function Log-Error {
    param([string]$Message)
    "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) [ERRO] $Message" | Out-File -FilePath $startupLog -Append -Encoding UTF8
}

function Log-Warn {
    param([string]$Message)
    "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) [AVISO] $Message" | Out-File -FilePath $startupLog -Append -Encoding UTF8
}

function Show-ErrorWindow {
    param([string]$Message)
    $safeMessage = $Message.Replace('"', "'")
    Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "echo [ERRO] $safeMessage & echo. & echo Verifique startup_log.txt para detalhes. & pause" -WorkingDirectory $ProjectDir | Out-Null
}

function Test-TcpPort {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(1200, $false)
        if (-not $ok) {
            $client.Close()
            return $false
        }
        $client.EndConnect($async)
        $client.Close()
        return $true
    }
    catch {
        return $false
    }
}

function Wait-ForPort {
    param(
        [int]$Port,
        [int]$Retries = 20,
        [int]$DelaySeconds = 1
    )
    for ($i = 0; $i -lt $Retries; $i++) {
        if (Test-TcpPort -Port $Port) {
            return $true
        }
        Start-Sleep -Seconds $DelaySeconds
    }
    return $false
}

function Test-ProcessAlive {
    param([string]$PidFile)

    if (-not (Test-Path $PidFile)) {
        return $false
    }

    $pidValue = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if (-not $pidValue) {
        return $false
    }

    return [bool](Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue)
}

function Write-PidFile {
    param(
        [string]$PidFile,
        [int]$ProcessId
    )

    Set-Content -Path $PidFile -Value $ProcessId -Encoding ascii
}

function Stop-ProcessByPidFile {
    param([string]$PidFile)

    if (-not (Test-Path $PidFile)) {
        return
    }

    $pidValue = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if (-not $pidValue) {
        return
    }

    $proc = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

function Stop-CloudflaredByUrl {
    param([string]$UrlFragment)

    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match "cloudflared" -and $_.CommandLine -match [regex]::Escape($UrlFragment)
    }

    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-CloudflareTunnel {
    param(
        [string]$CloudflaredExe,
        [string]$ProjectDir,
        [string]$LogFile,
        [string]$ErrFile,
        [string]$Url,
        [string]$Token,
        [string]$TunnelLabel
    )

    if (-not [string]::IsNullOrWhiteSpace($Token)) {
        Log-Info "Iniciando $TunnelLabel via Named Tunnel (token)."
        return Start-Process -FilePath $CloudflaredExe -ArgumentList @("tunnel", "run", "--token", $Token) -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
    }

    Log-Info "Iniciando $TunnelLabel via Quick Tunnel: $Url"
    return Start-Process -FilePath $CloudflaredExe -ArgumentList @("tunnel", "--url", $Url) -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
}

try {
    "" | Out-File -FilePath $startupLog -Encoding UTF8
    Log-Info "Iniciando fluxo silencioso de startup."
    Load-DotEnv -Path $envFile
    Log-Info "Variaveis do arquivo .env carregadas para o processo atual."

    $landingSyncScript = Join-Path $ProjectDir "atualizar_landing_config.ps1"
    if (Test-Path $landingSyncScript) {
        try {
            & $landingSyncScript -ProjectDir $ProjectDir | Out-Null
            Log-Info "landing_page_config.js sincronizado com APP_PUBLIC_URL."
        }
        catch {
            Log-Warn "Falha ao sincronizar landing_page_config.js: $($_.Exception.Message)"
        }
    }

    # Priorizar o Python do venv se existir
    $venvPy = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        $pythonExe = $venvPy
    }
    else {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCmd) {
            $fallbackPy = "C:/Users/mthia/AppData/Local/Microsoft/WindowsApps/python3.13.exe"
            if (Test-Path $fallbackPy) {
                $pythonExe = $fallbackPy
            }
            else {
                throw "Python nao encontrado no PATH."
            }
        }
        else {
            $pythonExe = $pythonCmd.Source
        }
    }

    $cloudflaredExe = $null
    $cloudflaredLocal = Join-Path $ProjectDir "cloudflared.exe"
    if (Test-Path $cloudflaredLocal) {
        $cloudflaredExe = $cloudflaredLocal
    }
    else {
        $cfCmd = Get-Command cloudflared -ErrorAction SilentlyContinue
        if ($cfCmd) {
            $cloudflaredExe = $cfCmd.Source
        }
        else {
            Log-Warn "cloudflared nao encontrado. O CRM vai iniciar apenas em modo local ate instalar o Cloudflare Tunnel."
        }
    }

    $streamlitLog = Join-Path $ProjectDir "streamlit_pro.log"
    $streamlitErr = Join-Path $ProjectDir "streamlit_pro.err.log"
    $appTunnelLog = Join-Path $ProjectDir "cloudflare_tunnel.log"
    $appTunnelErr = Join-Path $ProjectDir "cloudflare_tunnel.err.log"
    $apiLog = Join-Path $ProjectDir "api_server.log"
    $apiErr = Join-Path $ProjectDir "api_server.err.log"
    $apiTunnelLog = Join-Path $ProjectDir "api_tunnel.log"
    $apiTunnelErr = Join-Path $ProjectDir "api_tunnel.err.log"
    $remoteControlLog = Join-Path $ProjectDir "remote_control.log"
    $remoteControlErr = Join-Path $ProjectDir "remote_control.err.log"
    $controlTunnelLog = Join-Path $ProjectDir "control_tunnel.log"
    $controlTunnelErr = Join-Path $ProjectDir "control_tunnel.err.log"
    $emailLog = Join-Path $ProjectDir "enviar_link.log"
    $emailErr = Join-Path $ProjectDir "enviar_link.err.log"
    $streamlitPidFile = Join-Path $ProjectDir "streamlit_pro.pid"
    $appTunnelPidFile = Join-Path $ProjectDir "cloudflare_tunnel.pid"
    $apiPidFile = Join-Path $ProjectDir "api_server.pid"
    $apiTunnelPidFile = Join-Path $ProjectDir "api_tunnel.pid"
    $remoteControlPidFile = Join-Path $ProjectDir "remote_control.pid"
    $controlTunnelPidFile = Join-Path $ProjectDir "control_tunnel.pid"
    $apiPortRaw = [Environment]::GetEnvironmentVariable("APP_API_PORT", "Process")
    if ([string]::IsNullOrWhiteSpace($apiPortRaw)) {
        $apiPortRaw = "8787"
    }
    $apiPort = [int]$apiPortRaw
    $appTunnelToken = [Environment]::GetEnvironmentVariable("CF_TUNNEL_TOKEN", "Process")
    if ([string]::IsNullOrWhiteSpace($appTunnelToken)) {
        $appTunnelToken = [Environment]::GetEnvironmentVariable("CF_TUNNEL_TOKEN", "User")
    }
    if ([string]::IsNullOrWhiteSpace($appTunnelToken)) {
        $appTunnelToken = [Environment]::GetEnvironmentVariable("CF_TUNNEL_TOKEN", "Machine")
    }
    $controlTunnelToken = [Environment]::GetEnvironmentVariable("CF_CONTROL_TUNNEL_TOKEN", "Process")
    if ([string]::IsNullOrWhiteSpace($controlTunnelToken)) {
        $controlTunnelToken = [Environment]::GetEnvironmentVariable("CF_CONTROL_TUNNEL_TOKEN", "User")
    }
    if ([string]::IsNullOrWhiteSpace($controlTunnelToken)) {
        $controlTunnelToken = [Environment]::GetEnvironmentVariable("CF_CONTROL_TUNNEL_TOKEN", "Machine")
    }
    $apiTunnelToken = [Environment]::GetEnvironmentVariable("CF_API_TUNNEL_TOKEN", "Process")
    if ([string]::IsNullOrWhiteSpace($apiTunnelToken)) {
        $apiTunnelToken = [Environment]::GetEnvironmentVariable("CF_API_TUNNEL_TOKEN", "User")
    }
    if ([string]::IsNullOrWhiteSpace($apiTunnelToken)) {
        $apiTunnelToken = [Environment]::GetEnvironmentVariable("CF_API_TUNNEL_TOKEN", "Machine")
    }
    $appPublicUrl = [Environment]::GetEnvironmentVariable("APP_PUBLIC_URL", "Process")
    if ([string]::IsNullOrWhiteSpace($appPublicUrl)) {
        $appPublicUrl = [Environment]::GetEnvironmentVariable("APP_PUBLIC_URL", "User")
    }
    if ([string]::IsNullOrWhiteSpace($appPublicUrl)) {
        $appPublicUrl = [Environment]::GetEnvironmentVariable("APP_PUBLIC_URL", "Machine")
    }
    $apiPublicUrl = [Environment]::GetEnvironmentVariable("APP_API_PUBLIC_URL", "Process")
    if ([string]::IsNullOrWhiteSpace($apiPublicUrl)) {
        $apiPublicUrl = [Environment]::GetEnvironmentVariable("APP_API_PUBLIC_URL", "User")
    }
    if ([string]::IsNullOrWhiteSpace($apiPublicUrl)) {
        $apiPublicUrl = [Environment]::GetEnvironmentVariable("APP_API_PUBLIC_URL", "Machine")
    }

    if ([string]::IsNullOrWhiteSpace($appTunnelToken)) {
        Log-Warn "CF_TUNNEL_TOKEN ausente. O CRM usara Quick Tunnel temporario, que pode mudar e demorar a propagar."
    }
    if ([string]::IsNullOrWhiteSpace($appPublicUrl)) {
        Log-Warn "APP_PUBLIC_URL ausente. A landing publica nao exibira link fixo do CRM ate essa variavel ser configurada."
    }
    if ([string]::IsNullOrWhiteSpace($apiTunnelToken)) {
        Log-Warn "CF_API_TUNNEL_TOKEN ausente. A API web ficara disponivel apenas localmente, sem URL publica fixa."
    }
    if ([string]::IsNullOrWhiteSpace($apiPublicUrl)) {
        Log-Warn "APP_API_PUBLIC_URL ausente. O app.html precisara de URL manual da API ate essa variavel ser configurada."
    }
    if ([string]::IsNullOrWhiteSpace($controlTunnelToken)) {
        Log-Warn "CF_CONTROL_TUNNEL_TOKEN ausente. O controle remoto usara Quick Tunnel temporario."
    }

    Remove-Item -Force -ErrorAction SilentlyContinue $streamlitLog, $streamlitErr, $appTunnelLog, $appTunnelErr, $apiLog, $apiErr, $apiTunnelLog, $apiTunnelErr, $emailLog, $emailErr

    if (-not (Test-TcpPort -Port $apiPort)) {
        Log-Info "Iniciando API web na porta $apiPort."
        $apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @("api_server.py") -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput $apiLog -RedirectStandardError $apiErr -PassThru
        Write-PidFile -PidFile $apiPidFile -ProcessId $apiProcess.Id

        if (-not (Wait-ForPort -Port $apiPort -Retries 15 -DelaySeconds 1)) {
            throw "API web nao subiu na porta $apiPort."
        }
    }
    else {
        Log-Info "API web ja estava ativa na porta $apiPort."
    }

    if ($cloudflaredExe) {
        if (-not (Test-ProcessAlive -PidFile $apiTunnelPidFile)) {
            Log-Info "Iniciando tunnel da API na porta $apiPort."
            $apiTunnelProcess = Start-CloudflareTunnel -CloudflaredExe $cloudflaredExe -ProjectDir $ProjectDir -LogFile $apiTunnelLog -ErrFile $apiTunnelErr -Url "http://localhost:$apiPort" -Token $apiTunnelToken -TunnelLabel "tunnel da API"
            Write-PidFile -PidFile $apiTunnelPidFile -ProcessId $apiTunnelProcess.Id
        }
        else {
            Log-Info "Tunnel da API ja estava ativo."
        }
    }
    else {
        Log-Warn "Tunnel da API nao iniciado porque cloudflared nao esta disponivel."
    }

    if (-not (Test-TcpPort -Port 8765)) {
        Log-Info "Iniciando servidor de controle remoto na porta 8765."
        Remove-Item -Force -ErrorAction SilentlyContinue $remoteControlLog, $remoteControlErr
        $controlProcess = Start-Process -FilePath $pythonExe -ArgumentList @("remote_control.py") -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput $remoteControlLog -RedirectStandardError $remoteControlErr -PassThru
        Write-PidFile -PidFile $remoteControlPidFile -ProcessId $controlProcess.Id

        if (-not (Wait-ForPort -Port 8765 -Retries 15 -DelaySeconds 1)) {
            throw "Servidor de controle remoto nao subiu na porta 8765."
        }
    }
    else {
        Log-Info "Servidor de controle remoto ja estava ativo na porta 8765."
    }

    if ($cloudflaredExe) {
        if (-not (Test-ProcessAlive -PidFile $controlTunnelPidFile)) {
            Log-Info "Iniciando tunnel de controle remoto na porta 8765."
            Remove-Item -Force -ErrorAction SilentlyContinue $controlTunnelLog, $controlTunnelErr
            $controlTunnelProcess = Start-CloudflareTunnel -CloudflaredExe $cloudflaredExe -ProjectDir $ProjectDir -LogFile $controlTunnelLog -ErrFile $controlTunnelErr -Url "http://localhost:8765" -Token $controlTunnelToken -TunnelLabel "tunnel de controle"
            Write-PidFile -PidFile $controlTunnelPidFile -ProcessId $controlTunnelProcess.Id
        }
        else {
            Log-Info "Tunnel de controle remoto ja estava ativo."
        }
    }
    else {
        Log-Warn "Tunnel de controle remoto nao iniciado porque cloudflared nao esta disponivel."
    }

    if (Test-TcpPort -Port 8501) {
        Log-Info "CRM Pro ja estava ativo na porta 8501."
    }
    else {
        Log-Info "Iniciando CRM Pro em background na porta 8501."
        $streamlitProcess = Start-Process -FilePath $pythonExe -ArgumentList @(
            "-m", "streamlit", "run", "crm_pro.py",
            "--server.port=8501",
            "--server.address=0.0.0.0",
            "--server.enableCORS=false",
            "--server.enableXsrfProtection=false",
            "--logger.level=error"
        ) -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput $streamlitLog -RedirectStandardError $streamlitErr -PassThru
        Write-PidFile -PidFile $streamlitPidFile -ProcessId $streamlitProcess.Id

        if (-not (Wait-ForPort -Port 8501 -Retries 25 -DelaySeconds 1)) {
            throw "CRM Pro nao subiu na porta 8501."
        }
    }

    if ($cloudflaredExe) {
        Stop-ProcessByPidFile -PidFile $appTunnelPidFile
        Stop-CloudflaredByUrl -UrlFragment "http://localhost:8501"

        $appTunnelProcess = Start-CloudflareTunnel -CloudflaredExe $cloudflaredExe -ProjectDir $ProjectDir -LogFile $appTunnelLog -ErrFile $appTunnelErr -Url "http://localhost:8501" -Token $appTunnelToken -TunnelLabel "tunnel principal"
        Write-PidFile -PidFile $appTunnelPidFile -ProcessId $appTunnelProcess.Id

        Start-Sleep -Seconds 5

        Log-Info "Iniciando envio de link por email."
        Start-Process -FilePath $pythonExe -ArgumentList @("enviar_ip_email.py", "cloudflare") -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput $emailLog -RedirectStandardError $emailErr | Out-Null
    }
    else {
        Log-Warn "Cloudflare indisponivel. O link externo por email nao sera enviado nesta inicializacao."
    }

    Log-Info "Fluxo de startup concluido sem abrir janelas."
    exit 0
}
catch {
    $errorMessage = $_.Exception.Message
    Log-Error $errorMessage
    Show-ErrorWindow $errorMessage
    exit 1
}
