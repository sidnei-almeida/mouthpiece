# Windows version of smoke.sh: after the installer ran, create a voice, speak a line, check the WAV.
$ErrorActionPreference = 'Stop'
$mp = Join-Path $env:LOCALAPPDATA 'Programs\Mouthpiece\bin\mouthpiece.cmd'
$fixture = Join-Path $PSScriptRoot 'fixtures\reference-en.wav'
& $mp voice add $fixture --name ci --lang en
if ($LASTEXITCODE) { throw 'voice add failed' }
$out = Join-Path $env:RUNNER_TEMP 'smoke.wav'
$json = & $mp say 'Hello from the release test.' -o $out --voice ci-en.wav --json
if ($LASTEXITCODE) { throw 'say failed' }
Write-Host $json
$r = $json | ConvertFrom-Json
$bytes = [IO.File]::ReadAllBytes($out)
$rate = [BitConverter]::ToInt32($bytes, 24); $bits = [BitConverter]::ToInt16($bytes, 34); $ch = [BitConverter]::ToInt16($bytes, 22)
if ($rate -ne 48000 -or $bits -ne 24 -or $ch -ne 1 -or $r.duration -le 0.5) { throw "bad output: $rate Hz, $bits bit, $ch ch, $($r.duration) s" }
Write-Host "smoke test ok: $($r.duration) s, $rate Hz, $bits bit"
& $mp stop
