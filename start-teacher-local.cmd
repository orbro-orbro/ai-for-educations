@echo off
title Knowbound teacher local test
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-teacher-local.ps1"
if errorlevel 1 (
  echo.
  echo Start failed. Read the [CODE] line above, fix it, then double-click this file again.
  pause
  exit /b 1
)
pause
