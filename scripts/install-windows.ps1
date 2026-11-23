param([ValidateSet('both','codex','claude','none')][string]$McpHost = 'both')
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable exited with status $LASTEXITCODE" }
}
if (!(Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Install Python 3.11 or later from python.org with the Windows launcher.'
}
if ($McpHost -in @('both','codex') -and !(Get-Command codex -ErrorAction SilentlyContinue)) {
    throw 'Install Codex CLI or select the claude or none MCP host.'
}
$chromePaths = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
if (!($chromePaths | Where-Object { Test-Path -LiteralPath $_ })) {
    Write-Host 'Install Google Chrome before using the browser worker.'
}
Invoke-Checked 'py' @('-3', '-c', 'import sys; sys.exit(sys.version_info < (3, 11))')
Invoke-Checked 'py' @('-3', '-m', 'venv', '.venv')
$python = (Resolve-Path '.venv\Scripts\python.exe').Path
Invoke-Checked $python @('-m', 'pip', 'install', '.')
Invoke-Checked $python @('-I', '-m', 'hunyuan_workbench', '--help')
Invoke-Checked $python @('smoke_mcp.py', '--installed')
Invoke-Checked $python @('-I', '-m', 'mcp_config', '--host', $McpHost)
