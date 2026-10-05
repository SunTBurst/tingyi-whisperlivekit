$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Setup.ps1')
exit $LASTEXITCODE
