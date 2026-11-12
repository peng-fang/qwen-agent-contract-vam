$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw "Python venv not found: $Python. Create it with: py -3.11 -m venv .venv"
}

$existing = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host 'App already appears to be running at http://127.0.0.1:7860'
    Start-Process 'http://127.0.0.1:7860'
    exit 0
}

Write-Host '[1/3] Checking Ollama...'
$ollamaUp = $false
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null
    $ollamaUp = $true
} catch {
    Write-Host 'Ollama not responding, starting ollama serve...'
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
            $ollamaUp = $true
            break
        } catch { }
    }
}
if (-not $ollamaUp) {
    throw 'Ollama did not start. Run `ollama serve` in a separate terminal.'
}

Write-Host '[2/3] Checking model qwen2.5:7b...'
$tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10
$modelName = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { 'qwen2.5:7b' }
if (-not ($tags.models.name -contains $modelName)) {
    Write-Host "Model $modelName not found, pulling it (about 4.7 GB)..."
    & ollama pull $modelName
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull $modelName" }
}

Write-Host '[3/3] Starting app at http://127.0.0.1:7860 ...'
& $Python examples\assistant_contract_local.py
