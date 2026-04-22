@echo off
title Mendix Multi-Agent Analyzer
echo ============================================
echo   Mendix Multi-Agent Analyzer  v1.0
echo ============================================
echo.

REM ── Try standard Python first ──────────────────────────────────────
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] Using system Python
    python run.py
    goto :END
)

REM ── Try LM Studio bundled Python (cpython3.11) ─────────────────────
set LMS_PY=%USERPROFILE%\.lmstudio\extensions\backends\vendor\_amphibian\cpython3.11-win-x86@6\python.exe
if exist "%LMS_PY%" (
    echo [INFO] Using LM Studio Python 3.11 at:
    echo        %LMS_PY%
    echo.
    "%LMS_PY%" run.py
    goto :END
)

REM ── Try LM Studio Program Files Python ─────────────────────────────
set LMS_PY2=C:\Program Files\LM Studio\resources\app\.webpack\bin\extensions\backends\vendor\_amphibian\cpython3.11-win-x86@6\python.exe
if exist "%LMS_PY2%" (
    echo [INFO] Using LM Studio Python (Program Files)
    "%LMS_PY2%" run.py
    goto :END
)

REM ── Python not found ───────────────────────────────────────────────
echo [ERROR] Python not found on this system.
echo.
echo Options to fix this:
echo   1. Install Python from https://python.org  (add to PATH)
echo   2. Open LM Studio at least once so it installs its bundled Python
echo   3. Install Anaconda / Miniconda
echo.
echo After installing Python, run:  pip install requests
echo Then run this launcher again.
echo.
pause
exit /B 1

:END
echo.
echo [INFO] Application closed.
pause
