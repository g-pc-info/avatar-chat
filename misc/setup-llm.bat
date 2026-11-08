@echo off
rem Local LLM setup (llama.cpp + llama-swap + model).
rem Called from start.bat on first run:  call misc\setup-llm.bat auto
rem Can also be run alone by double-clicking this file.
setlocal
cd /d "%~dp0.."
set "PDIR=%CD%\"
set "DL=%PDIR%misc\downloads"
set "HELPER=%PDIR%misc\setup-llm-helper.ps1"
set "AUTO=%~1"

rem ---- versions (change here to update)
rem llama.cpp v0.9.0 = build b12110 (the binaries are published under the b-number tag)
set "LLAMA_TAG=b12110"
set "SWAP_VER=270"
set "MODEL_STHENO=Llama-3.1-8B-Stheno-v3.4-Q4_K_M.gguf"
set "MODEL_LUMI=Lumimaid-v0.2-8B.q4_k_m.gguf"
set "URL_STHENO=https://huggingface.co/bartowski/Llama-3.1-8B-Stheno-v3.4-GGUF/resolve/main/%MODEL_STHENO%"
set "URL_LUMI=https://huggingface.co/NeverSleep/Lumimaid-v0.2-8B-GGUF/resolve/main/%MODEL_LUMI%"
set "GH_LLAMA=https://github.com/ggml-org/llama.cpp/releases/download/%LLAMA_TAG%"
set "URL_SWAP=https://github.com/mostlygeek/llama-swap/releases/download/v%SWAP_VER%/llama-swap_%SWAP_VER%_windows_amd64.zip"
set "SWAP_ZIP=llama-swap_%SWAP_VER%_windows_amd64.zip"

:menu
echo.
echo ==== Local LLM setup ====
echo Your graphics card:
powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController).Name | ForEach-Object { '   ' + $_ }"
echo.
echo   1. Radeon                            ^(AMD graphics card^)
echo   2. GeForce RTX 20 series or later    ^(NVIDIA, VRAM 8GB or more^)
echo   3. I already have an LLM server      ^(LM Studio, Ollama, etc.^)
echo   4. Skip ^(set it up later in the app Settings^)
echo.
choice /c 1234 /n /m "Press a number key [1-4]: "
if errorlevel 4 goto :skip
if errorlevel 3 goto :endpoint
if errorlevel 2 goto :geforce
goto :radeon

:radeon
set "LLAMA_ZIP=llama-%LLAMA_TAG%-bin-win-vulkan-x64.zip"
set "CUDART_ZIP="
goto :install

:geforce
set "LLAMA_ZIP=llama-%LLAMA_TAG%-bin-win-cuda-12.4-x64.zip"
set "CUDART_ZIP=cudart-llama-bin-win-cuda-12.4-x64.zip"
goto :install

:skip
echo Skipped. You can run misc\setup-llm.bat any time.
goto :ok

:endpoint
echo.
echo Which server do you use?
echo   1. LM Studio       ^(http://127.0.0.1:1234/v1^)
echo   2. Ollama          ^(http://127.0.0.1:11434/v1^)
echo   3. llama.cpp / llama-swap  ^(http://127.0.0.1:8080/v1^)
echo   4. Go back
echo.
choice /c 1234 /n /m "Press a number key [1-4]: "
if errorlevel 4 goto :menu
if errorlevel 3 set "EP_URL=http://127.0.0.1:8080/v1"
if errorlevel 3 goto :endpoint_save
if errorlevel 2 set "EP_URL=http://127.0.0.1:11434/v1"
if errorlevel 2 goto :endpoint_save
set "EP_URL=http://127.0.0.1:1234/v1"
:endpoint_save
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Action config -Root "%CD%" -Url "%EP_URL%"
if errorlevel 1 goto :fail
echo.
echo [OK] Saved. Pick the model name in the app Settings.
goto :ok

:install
if not exist "%DL%" mkdir "%DL%"
if not exist "%PDIR%llama.cpp" mkdir "%PDIR%llama.cpp"
if not exist "%PDIR%llama-swap" mkdir "%PDIR%llama-swap"
if not exist "%PDIR%models" mkdir "%PDIR%models"

echo.
echo Do you also want the second model, Lumimaid v0.2 8B ^(about 4.9GB more^)?
echo   1. No, Stheno only   ^(recommended^)
echo   2. Yes, both
choice /c 12 /n /m "Press a number key [1-2]: "
set "LUMI=0"
if errorlevel 2 set "LUMI=1"

echo.
echo Downloading now. This takes a while ^(the model is slow on purpose to be kind to the server^).
echo Please do not close this window. If you do, just start again; it continues where it stopped.

rem ---- llama.cpp
if exist "%PDIR%llama.cpp\llama-server.exe" (
  echo [OK] llama.cpp is already installed. Skipping.
  goto :swap
)
echo Downloading llama.cpp %LLAMA_TAG% ...
call :dl "%GH_LLAMA%/%LLAMA_ZIP%" "%DL%\%LLAMA_ZIP%" ""
if errorlevel 1 goto :fail
call :unzip "%DL%\%LLAMA_ZIP%" "%PDIR%llama.cpp"
if errorlevel 1 goto :fail
if "%CUDART_ZIP%"=="" goto :llamadone
echo Downloading CUDA runtime ...
call :dl "%GH_LLAMA%/%CUDART_ZIP%" "%DL%\%CUDART_ZIP%" ""
if errorlevel 1 goto :fail
call :unzip "%DL%\%CUDART_ZIP%" "%PDIR%llama.cpp"
if errorlevel 1 goto :fail
:llamadone
if not exist "%PDIR%llama.cpp\llama-server.exe" (
  echo [NG] llama-server.exe was not found after extraction.
  goto :fail
)
echo [OK] llama.cpp installed.

:swap
rem ---- llama-swap
if exist "%PDIR%llama-swap\llama-swap.exe" (
  echo [OK] llama-swap is already installed. Skipping.
  goto :models
)
echo Downloading llama-swap v%SWAP_VER% ...
call :dl "%URL_SWAP%" "%DL%\%SWAP_ZIP%" ""
if errorlevel 1 goto :fail
call :unzip "%DL%\%SWAP_ZIP%" "%PDIR%llama-swap"
if errorlevel 1 goto :fail
if not exist "%PDIR%llama-swap\llama-swap.exe" (
  echo [NG] llama-swap.exe was not found after extraction.
  goto :fail
)
echo [OK] llama-swap installed.

:models
rem ---- models (files over 500MB are rate-limited to be kind to the servers)
echo.
echo Downloading model: Stheno v3.4 8B Q4_K_M ^(about 4.9GB, limited to 5MB/s, roughly 17 minutes^)
call :dl "%URL_STHENO%" "%PDIR%models\%MODEL_STHENO%" "--limit-rate 5m"
if errorlevel 1 goto :fail
echo [OK] Stheno ready.
if not "%LUMI%"=="1" goto :config
echo.
echo Downloading model: Lumimaid v0.2 8B Q4_K_M ^(about 4.9GB, roughly 17 minutes^)
call :dl "%URL_LUMI%" "%PDIR%models\%MODEL_LUMI%" "--limit-rate 5m"
if errorlevel 1 goto :fail
echo [OK] Lumimaid ready.

:config
rem ---- llama-swap config + app config
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Action yaml -Root "%CD%" -Lumimaid %LUMI%
if errorlevel 1 goto :fail
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Action config -Root "%CD%" -Url "http://127.0.0.1:8080/v1" -Model "stheno-8b"
if errorlevel 1 goto :fail

echo.
echo [OK] Setup finished. llama-swap starts automatically with start.bat.
echo   Model names: stheno-8b ^(and lumimaid-8b if you chose it^). Change them in Settings.
goto :ok

:ok
if "%AUTO%"=="" pause
endlocal
exit /b 0

:fail
echo.
echo [NG] Setup did not finish. Check the messages above. It will be offered again next time.
pause
endlocal
exit /b 1

rem ---- subroutines
:dl
rem %1 = url, %2 = output file, %3 = extra curl options
if exist "%~2" (
  echo [OK] Already downloaded: %~nx2
  exit /b 0
)
curl.exe -L --fail -C - %~3 -o "%~2.part" "%~1"
if errorlevel 1 (
  echo [NG] Download failed: %~1
  exit /b 1
)
move /Y "%~2.part" "%~2" >nul
exit /b 0

:unzip
rem %1 = zip file, %2 = destination folder
powershell -NoProfile -Command "Expand-Archive -Force -Path '%~1' -DestinationPath '%~2'"
if errorlevel 1 (
  echo [NG] Extraction failed: %~1
  exit /b 1
)
exit /b 0
