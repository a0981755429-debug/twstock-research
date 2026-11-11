@echo off
chcp 65001 >nul
REM ============================================================
REM Intraday price alerts - checks price rules with live quotes
REM every 5 minutes during market hours (09:00-13:30), then exits.
REM Rules: dashboard /alerts page. Channel: config.yaml notify.
REM
REM Usage:
REM   intraday-alerts.bat        <- every 5 minutes
REM   intraday-alerts.bat 3      <- every 3 minutes
REM ============================================================
setlocal
title TW Stock - Intraday Price Alerts

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=py
)

set INTERVAL=%1
if "%INTERVAL%"=="" set INTERVAL=5

%PYTHON% -m scripts.intraday_alerts --interval %INTERVAL%
echo.
echo Press any key to close...
pause >nul
