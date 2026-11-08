@echo off
setlocal
cd /d "%~dp0"
set "PDIR=%CD%\"
set "SYS=%PDIR%system\"
set "PYDIR=%SYS%python"
set "PIP_CACHE_DIR=%SYS%.pip\cache"
set "PYTHONUTF8=1"
set "PATH=%PYDIR%;%PYDIR%\Scripts;%PATH%"

if not exist "%SYS%" mkdir "%SYS%"
if not exist "%PDIR%misc\downloads" mkdir "%PDIR%misc\downloads"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"

rem ---- Python 3.12.10 embeddable (first run only)
if not exist "%PYDIR%\python.exe" (
  if not exist "misc\downloads\python-3.12.10-embed-amd64.zip" (
    echo Downloading Python 3.12.10 embeddable...
    curl -L -o "misc\downloads\python-3.12.10-embed-amd64.zip" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
  )
  if not exist "misc\downloads\python-3.12.10-embed-amd64.zip" (
    echo Download failed. Check your internet connection.
    pause
    exit /b 1
  )
  powershell -NoProfile -Command "Expand-Archive -Force -Path 'misc\downloads\python-3.12.10-embed-amd64.zip' -DestinationPath 'system\python'"
  powershell -NoProfile -Command "(Get-Content 'system\python\python312._pth') -replace '#import site','import site' | Set-Content 'system\python\python312._pth'"
)

rem ---- pip (first run only)
if not exist "%PYDIR%\Scripts\pip.exe" (
  echo Installing pip...
  curl -L -o "%PYDIR%\get-pip.py" "https://bootstrap.pypa.io/get-pip.py"
  python "%PYDIR%\get-pip.py" --no-warn-script-location
  if errorlevel 1 (
    echo pip install failed.
    pause
    exit /b 1
  )
)

rem ---- MS Visual C++ runtime (needed by Pillow). Skipped if already installed.
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Installed >nul 2>&1
if errorlevel 1 (
  if not exist "misc\downloads\vc_redist.x64.exe" (
    curl -L -o "misc\downloads\vc_redist.x64.exe" "https://aka.ms/vs/17/release/vc_redist.x64.exe"
  )
  echo Installing Visual C++ runtime. Please allow administrator access in the taskbar.
  start /wait "" "misc\downloads\vc_redist.x64.exe" /install /quiet /norestart
)

rem ---- libraries (re-run only when requirements.txt changed)
fc /b requirements.txt "%SYS%requirements.installed" >nul 2>&1
if errorlevel 1 (
  echo Installing libraries...
  python -m pip install --no-warn-script-location -r requirements.txt
  if errorlevel 1 (
    echo Library install failed.
    pause
    exit /b 1
  )
  copy /Y requirements.txt "%SYS%requirements.installed" >nul
)

rem ---- first-run local LLM setup (menu). Skipped if already done or if a config already exists.
if exist "%SYS%llm-setup.done" goto :llmdone
if exist "%PDIR%user-data\config.json" goto :llmdone
call "%PDIR%misc\setup-llm.bat" auto
if not errorlevel 1 echo done> "%SYS%llm-setup.done"
:llmdone

rem ---- local LLM server (only if setup-llm.bat installed llama-swap)
if not exist "%PDIR%llama-swap\llama-swap.exe" goto :runapp
if not exist "%PDIR%llama-swap\config.yaml" goto :runapp
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if not errorlevel 1 goto :runapp
echo Starting llama-swap on 127.0.0.1:8080 ...
start "llama-swap" /min /d "%PDIR%llama-swap" "%PDIR%llama-swap\llama-swap.exe" -config config.yaml -listen 127.0.0.1:8080

:runapp
rem ---- run
python "%PDIR%app\main.py"
if errorlevel 1 pause
endlocal
