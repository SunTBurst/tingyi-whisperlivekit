$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$upstreamPackage = Join-Path $root 'upstream\whisperlivekit\__init__.py'

if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $pythonw)) {
    throw 'The Python environment is missing. Run Setup.ps1 first.'
}
if (-not (Test-Path -LiteralPath $upstreamPackage)) {
    throw 'WhisperLiveKit source is missing. Run Setup.ps1 first.'
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$torchLib = Join-Path $root '.venv\Lib\site-packages\torch\lib'
if (Test-Path -LiteralPath $torchLib) { $env:PATH = $torchLib + ';' + $env:PATH }
$env:HF_HOME = Join-Path $root 'models\cache'
$logFolder = Join-Path $root 'logs'
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
$entry = Join-Path $root 'main.py'
$running = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like ('*' + $entry + '*') })
if ($running.Count -gt 0) { Write-Output 'The app is already running.'; exit 0 }
Start-Process -FilePath $pythonw -ArgumentList ('"' + $entry + '"') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'ui-stdout.log') -RedirectStandardError (Join-Path $logFolder 'ui-stderr.log') | Out-Null
