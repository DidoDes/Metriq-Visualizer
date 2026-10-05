@echo off
setlocal
cd /d "%~dp0"
rem Reuse an existing virtual environment; otherwise create one with the
rem Python launcher (py) or, when it is not installed, with python.
if not exist .venv\Scripts\python.exe (
  set "BOOTSTRAP="
  where py >nul 2>nul && set "BOOTSTRAP=py -3"
  if not defined BOOTSTRAP (
    where python >nul 2>nul && set "BOOTSTRAP=python"
  )
)
if not exist .venv\Scripts\python.exe if not defined BOOTSTRAP (
  echo Metriq Visualizer requires Python 3.10 or newer.
  echo Install it from https://www.python.org/downloads/ and run this file again.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  %BOOTSTRAP% -m venv .venv || (pause & exit /b 1)
)
set "VENV_PY=.venv\Scripts\python.exe"
"%VENV_PY%" -m pip install --upgrade pip || (pause & exit /b 1)
"%VENV_PY%" -m pip install -r requirements.txt || (pause & exit /b 1)
"%VENV_PY%" metriq_visualizer_app.py %*
if errorlevel 1 pause
