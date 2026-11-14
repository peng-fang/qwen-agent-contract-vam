# 一键启动：FastAPI + 已构建前端（离线可用）
#
# 用法：
#   .\start.ps1                 # 默认 8001 端口并打开浏览器
#   .\start.ps1 -Port 8002      # 换端口
#   .\start.ps1 -NoBrowser      # 不自动打开浏览器
#   .\start.ps1 -Rebuild        # 先重新 npm run build
#
# 依赖：Python 3.10+（需 fastapi / uvicorn / qwen_agent），前端 dist 已提交到完整包。
# 不依赖 Ollama/DashScope；没有模型时条款对照、风险评分、评测仍可用，推演会给出可读提示。

param(
    [int]$Port = 8001,
    [switch]$NoBrowser,
    [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$DistIndex = Join-Path $Frontend 'dist\index.html'

function Fail($Message) {
    Write-Host $Message -ForegroundColor Red
    exit 1
}

Write-Host '== 签之前 · 本地一键启动 ==' -ForegroundColor Cyan

# 1) 找 Python：优先项目内 venv，其次 py -3.12 / python
$PyExe = $null
$PyPrefix = @()
$candidates = @(
    $env:PYTHON,
    (Join-Path $Root '.venv\Scripts\python.exe'),
    (Join-Path $Root '..\.venv312\Scripts\python.exe'),
    (Join-Path $Root '..\venv\Scripts\python.exe')
)
foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) {
        $PyExe = $candidate
        break
    }
}
if (-not $PyExe) {
    try {
        & py -3.12 --version *> $null
        $PyExe = 'py'
        $PyPrefix = @('-3.12')
    } catch {
        $PyExe = $null
    }
}
if (-not $PyExe) {
    try {
        & python --version *> $null
        $PyExe = 'python'
    } catch {
        Fail '未找到 Python。请安装 Python 3.10+，或在本目录创建 .venv 后重试。'
    }
}

# 2) 检查后端依赖
$probe = if ($PyExe -eq 'py') { & py -3.12 -c 'import fastapi, uvicorn, qwen_agent' 2>&1 } else { & $PyExe -c 'import fastapi, uvicorn, qwen_agent' 2>&1 }
if ($LASTEXITCODE -ne 0) {
    Write-Host $probe
    Fail "当前 Python 缺少依赖。请执行：`n  $PyExe -m pip install -r backend\requirements.txt`n  $PyExe -m pip install -e .`n或使用完整包内已配好的虚拟环境。"
}
Write-Host "Python: $PyExe $($PyPrefix -join ' ')" -ForegroundColor DarkGray

# 3) 前构建产物
if ($Rebuild -or -not (Test-Path $DistIndex)) {
    $nodeModules = Join-Path $Frontend 'node_modules'
    if (-not (Test-Path $nodeModules)) {
        Fail '缺少 frontend\dist 且未安装 node_modules。离线包应自带 dist；如需重建，请在 frontend 下执行 npm ci 后重试。'
    }
    Write-Host '正在构建前端 ...' -ForegroundColor Yellow
    Push-Location $Frontend
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { Fail '前端构建失败。' }
    } finally {
        Pop-Location
    }
}

$url = "http://127.0.0.1:$Port/"
$health = "http://127.0.0.1:$Port/api/health"

# 4) 后台等待就绪并打开浏览器（不改变前台 uvicorn 的 Ctrl+C 行为）
if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($h, $u)
        for ($i = 0; $i -lt 60; $i++) {
            try {
                $r = Invoke-RestMethod -Uri $h -TimeoutSec 1
                if ($r.status -eq 'ok') { break }
            } catch { }
            Start-Sleep -Milliseconds 500
        }
        Start-Process $u
    } -ArgumentList $health, $url | Out-Null
}

Write-Host "服务地址：$url" -ForegroundColor Green
Write-Host "健康检查：$health" -ForegroundColor DarkGray
Write-Host '按 Ctrl+C 停止。' -ForegroundColor DarkGray

# 5) 前台启动（Ctrl+C 即停）
Push-Location $Backend
try {
    if ($PyExe -eq 'py') {
        & py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port $Port
    } else {
        & $PyExe -m uvicorn app.main:app --host 127.0.0.1 --port $Port
    }
} finally {
    Pop-Location
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
}
