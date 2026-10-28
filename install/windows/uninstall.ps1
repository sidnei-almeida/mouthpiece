# Run by the uninstaller: stops Mouthpiece if it's running and takes its folder off the user's PATH.
# The user's voices and generations (%APPDATA%\Mouthpiece) and the downloaded model
# (%USERPROFILE%\.cache\huggingface) are kept.
$App = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py = Join-Path $App '.venv\Scripts\python.exe'
if (Test-Path $Py) { & $Py (Join-Path $App 'cli.py') stop 2>$null | Out-Null }
$Bin = Join-Path $App 'bin'
$path = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($path) {
    $kept = ($path -split ';') | Where-Object { $_ -and $_ -ne $Bin }
    [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
}
