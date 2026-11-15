@echo off
REM 双击启动：转发到 start.ps1，默认 8001 端口
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
