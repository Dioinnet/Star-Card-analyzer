# ============================================================
#  Star Card Analyzer - 快捷设置 AI 助手 API Key
#  用法:
#    交互式:  powershell -File scripts\set_api_key.ps1
#    带参数:  powershell -File scripts\set_api_key.ps1 -Key "sk-xxx"
#             powershell -File scripts\set_api_key.ps1 -Key "sk-xxx" `
#                            -BaseUrl "https://api.moonshot.cn/v1" -Model "moonshot-v1-8k"
#  写入项目根目录 agent.env；应用启动时自动读取（环境变量优先）。
# ============================================================
param(
    [string]$Key = "",
    [string]$BaseUrl = "https://api.deepseek.com",
    [string]$Model = "deepseek-chat"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root "agent.env"

if (-not $Key) {
    $secure = Read-Host "请输入 LLM API Key (sk-...)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $Key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

$Key = $Key.Trim()
if (-not $Key) {
    Write-Host "[!] 未提供 API Key，未做任何修改。" -ForegroundColor Yellow
    exit 1
}

$content = @"
# AI 估价助手 LLM 配置（由 set_api_key.ps1 生成；支持任何 OpenAI 兼容接口）
# 注意：手动设置的环境变量优先于本文件。
OPENAI_API_KEY=$Key
OPENAI_BASE_URL=$BaseUrl
AGENT_MODEL=$Model
"@

Set-Content -Path $envFile -Value $content -Encoding UTF8 -NoNewline:$false
Write-Host "[OK] 已保存到 $envFile" -ForegroundColor Green
Write-Host "     BaseUrl = $BaseUrl"
Write-Host "     Model   = $Model"
Write-Host "     重启应用（或新开 PowerShell 启动 start_app.bat）后 AI 助手生效。"
