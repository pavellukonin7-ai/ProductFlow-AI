$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== ProductFlow AI ===" -ForegroundColor Cyan

if (-not (Test-Path ".venv")) {
    Write-Host "Создаю виртуальное окружение..."
    py -m venv .venv
}

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Не найден Python виртуального окружения: $Python"
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Создан .env. Заполните BOT_TOKEN и при необходимости OPENAI_API_KEY, затем запустите скрипт снова." -ForegroundColor Yellow
    exit 1
}

$env:PYTHONPATH = $PSScriptRoot

Write-Host "Проверяю зависимости..."
& $Python -m pip install -r requirements.txt

Write-Host "Проверяю конфигурацию, MCP, Telegram и AI..."
& $Python -m scripts.check_project
if ($LASTEXITCODE -ne 0) {
    throw "Предварительная проверка не пройдена. Бот не запущен."
}

Write-Host "Запускаю ProductFlow AI..." -ForegroundColor Green
& $Python -m telegram_bot.main
