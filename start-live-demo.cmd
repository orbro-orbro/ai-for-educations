@echo off
title Knowbound live model demo
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-live-demo.ps1"
if errorlevel 1 (
  echo.
  echo 启动失败。若已打开配置文件，请填好模型名和对应 Key 后保存，再双击本文件。
  pause
  exit /b 1
)
pause
