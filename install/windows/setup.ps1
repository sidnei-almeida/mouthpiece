# Mouthpiece setup for Windows. The installer runs this after copying the app; it can also be run by
# hand to repair an install:  powershell -ExecutionPolicy Bypass -File setup.ps1
#
# 1. uv (Python manager) into <app>\bin   2. pick the PyTorch build for this GPU (Intel Arc -> XPU,
# NVIDIA -> CUDA, otherwise CPU)   3. Python 3.12 venv with the pinned packages   4. the voice model
# (~4 GB, pinned revision)   5. the `mouthpiece` command on the user's PATH.
# MOUTHPIECE_BACKEND=xpu|cu130|cu126|cpu overrides step 2.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest's progress bar slows downloads to a crawl
$App = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bin = Join-Path $App 'bin'
$Log = Join-Path $App 'setup.log'
$Host.UI.RawUI.WindowTitle = 'Mouthpiece - instalando'
Start-Transcript -Path $Log -Force | Out-Null

function Step($text) { Write-Host "`n>> $text" -ForegroundColor White }
function Run($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$([IO.Path]::GetFileName($exe)) falhou (codigo $LASTEXITCODE)" }
}

try {
    Write-Host 'Mouthpiece - your voice, typed.' -ForegroundColor White
    Write-Host 'Isto baixa o Python, o PyTorch e o modelo de voz: alguns GB. Pode levar varios minutos.'

    Step 'uv (gerenciador de Python)'
    $Uv = Join-Path $Bin 'uv.exe'
    if (-not (Test-Path $Uv)) {
        New-Item -ItemType Directory -Force -Path $Bin | Out-Null
        $env:UV_INSTALL_DIR = $Bin
        $env:UV_NO_MODIFY_PATH = '1'
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
    if (-not (Test-Path $Uv)) { throw 'nao consegui instalar o uv' }

    Step 'Placa de video'
    $Backend = $env:MOUTHPIECE_BACKEND
    if (-not $Backend) {
        $gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
        Write-Host ('  encontrada: ' + ($gpus -join ', '))
        if ($gpus -match 'NVIDIA') {
            $driver = 0
            try { $driver = [int]((& nvidia-smi --query-gpu=driver_version --format=csv,noheader | Select-Object -First 1).Split('.')[0]) } catch {}
            $Backend = if ($driver -ge 580) { 'cu130' } else { 'cu126' }
        } elseif ($gpus -match 'Intel.*Arc') {
            $Backend = 'xpu'
        } else {
            $Backend = 'cpu'
            Write-Host '  Nenhuma placa compativel: vai rodar na CPU (funciona, mas bem mais devagar).' -ForegroundColor Yellow
        }
    }
    Write-Host "  usando: $Backend"

    Step 'Python 3.12 e pacotes'
    $Venv = Join-Path $App '.venv'
    $Py = Join-Path $Venv 'Scripts\python.exe'
    Run $Uv @('venv', '--python', '3.12', '--allow-existing', $Venv)
    Run $Uv @('pip', 'install', '--python', $Py, 'torch==2.14.1', 'torchaudio==2.11.0', '--index-url', "https://download.pytorch.org/whl/$Backend")
    Run $Uv @('pip', 'install', '--python', $Py, '-r', (Join-Path $App 'requirements.txt'))
    Run $Uv @('pip', 'install', '--python', $Py, '--no-deps', 'qwen-tts==0.1.1')

    Step 'Modelo de voz (~4 GB)'
    Push-Location $App
    try {
        Run $Py @('-c', 'from huggingface_hub import snapshot_download; import server_model as m; snapshot_download(m.MODEL_ID, revision=m.MODEL_REVISION); print("ok")')
    } finally { Pop-Location }

    Step 'Comando mouthpiece no terminal'
    Set-Content -Encoding ASCII -Path (Join-Path $Bin 'mouthpiece.cmd') -Value "@echo off`r`n`"%~dp0..\.venv\Scripts\python.exe`" `"%~dp0..\cli.py`" %*"
    $path = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (($path -split ';') -notcontains $Bin) {
        [Environment]::SetEnvironmentVariable('Path', (($path.TrimEnd(';') + ';' + $Bin).TrimStart(';')), 'User')
    }

    Write-Host "`nPronto." -ForegroundColor Green
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host "`nA instalacao falhou: $_" -ForegroundColor Red
    Write-Host "Detalhes em: $Log"
    Stop-Transcript | Out-Null
    Read-Host 'Enter para fechar'
    exit 1
}
