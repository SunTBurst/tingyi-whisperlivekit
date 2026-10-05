param(
    [switch]$AcceptNonCommercialLicense
)

$ErrorActionPreference = 'Stop'
Write-Warning 'NLLB-200 distilled 600M model weights are licensed CC-BY-NC-4.0. They are for non-commercial use only and require attribution. Review the model card and license before downloading.'
Write-Output 'https://huggingface.co/facebook/nllb-200-distilled-600M'
if (-not $AcceptNonCommercialLicense) {
    $answer = Read-Host 'Type ACCEPT-NONCOMMERCIAL to confirm you have reviewed the license and want to download these weights'
    if ($answer -cne 'ACCEPT-NONCOMMERCIAL') { throw 'Download cancelled. No model files were requested.' }
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'The Python environment is missing. Run Setup.ps1 first.' }
$downloader = Join-Path $PSScriptRoot 'scripts\download_nllb.py'
if (-not (Test-Path -LiteralPath $downloader)) { throw 'The pinned model downloader is missing from this source checkout.' }
$env:PYTHONUTF8 = '1'
& $python $downloader
if ($LASTEXITCODE -ne 0) { throw 'The NLLB download or checksum verification failed.' }
