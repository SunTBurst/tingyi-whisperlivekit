param()

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$upstreamPath = Join-Path $root 'upstream'
$expectedRevision = '363e4f6d029694d9c81ae548beddd9d3c88a3637'
$upstreamUrl = 'https://github.com/QuentinFuxa/WhisperLiveKit.git'

if ($env:OS -ne 'Windows_NT') {
    throw 'This setup script supports Windows only. See docs/INSTALL.md for the current scope.'
}
$uv = Get-Command uv.exe -ErrorAction SilentlyContinue
if (-not $uv) { throw 'uv is required. Install it from https://docs.astral.sh/uv/ and rerun Setup.ps1.' }
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { throw 'Git is required. Install Git for Windows and rerun Setup.ps1.' }

if (Test-Path -LiteralPath $upstreamPath) {
    if (-not (Test-Path -LiteralPath (Join-Path $upstreamPath '.git'))) {
        throw "The upstream folder exists but is not a Git checkout: $upstreamPath. Move it aside and rerun Setup.ps1."
    }
    $actualRevision = (& $git.Source -C $upstreamPath rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualRevision -ne $expectedRevision) {
        throw "The existing upstream checkout is not the required revision $expectedRevision. It was left unchanged."
    }
} else {
    & $git.Source clone --filter=blob:none --no-checkout $upstreamUrl $upstreamPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not clone WhisperLiveKit. Check the network and rerun Setup.ps1.' }
    & $git.Source -C $upstreamPath checkout --detach $expectedRevision
    if ($LASTEXITCODE -ne 0) { throw 'Could not check out the pinned WhisperLiveKit revision.' }
}

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & $uv.Source python install 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Could not install managed Python 3.12 with uv.' }
    & $uv.Source venv --python 3.12 (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
$pythonVersion = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.12') {
    throw "The existing .venv uses Python $pythonVersion. This project setup requires Python 3.12; replace .venv and rerun Setup.ps1."
}

& $uv.Source pip install --python $python -r (Join-Path $root 'requirements-public.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the desktop application dependencies.' }
& $uv.Source pip install --python $python -e "$upstreamPath[cpu]"
if ($LASTEXITCODE -ne 0) { throw 'Could not install WhisperLiveKit and its declared CPU dependencies.' }
& $uv.Source pip check --python $python
if ($LASTEXITCODE -ne 0) { throw 'The installed Python dependencies are inconsistent.' }

Write-Output 'Setup completed. Start the app with Start.ps1. Speech and translation weights are separate downloads.'
