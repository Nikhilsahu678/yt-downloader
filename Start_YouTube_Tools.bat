@echo off
title YouTube Tools – Portable Launcher
setlocal enabledelayedexpansion

:: Configuration
set "DOWNLOADER_PATH=%USERPROFILE%\yt_downloader"
set "INFO_PATH=%USERPROFILE%\yt_info"
set "DOWNLOADER_URL=https://github.com/Nikhilsahu678/yt-downloader/archive/refs/heads/main.zip"
set "INFO_APP_URL=https://raw.githubusercontent.com/Nikhilsahu678/yt-downloader/main/info_app.py"
set "INFO_HTML_URL=https://raw.githubusercontent.com/Nikhilsahu678/yt-downloader/main/info_index.html"

echo ====================================================
echo    YouTube Downloader & Info Extractor Portable
echo ====================================================
echo.

:: --- Check for Python ---
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Trying to install via winget...
    winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements >nul 2>&1
    if errorlevel 1 (
        echo Failed to install Python automatically.
        echo Please install Python from https://python.org and run this script again.
        pause
        exit /b 1
    )
    call :RefreshEnv
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python installation succeeded but not found in PATH. Please restart your PC and run this script again.
        pause
        exit /b 1
    )
)

:: --- Check for FFmpeg ---
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo FFmpeg not found. Trying to install via winget...
    winget install "FFmpeg" --accept-source-agreements --accept-package-agreements >nul 2>&1
    if errorlevel 1 (
        echo Failed to install FFmpeg automatically.
        echo Please install FFmpeg from https://ffmpeg.org/download.html and run this script again.
        pause
        exit /b 1
    )
    call :RefreshEnv
    where ffmpeg >nul 2>&1
    if errorlevel 1 (
        echo FFmpeg installation succeeded but not found in PATH. Please restart your PC and run this script again.
        pause
        exit /b 1
    )
)

:: --- Install Python libraries ---
echo Installing required Python libraries...
python -m pip install flask yt-dlp --quiet 2>nul
if %errorlevel% neq 0 (
    python -m pip install --upgrade pip --quiet 2>nul
    python -m pip install flask yt-dlp --quiet 2>nul
    if %errorlevel% neq 0 (
        echo Failed to install required packages. Please check your internet connection and try again.
        pause
        exit /b 1
    )
)
echo Libraries installed successfully.

:: ================== YouTube Downloader ==================
if not exist "%DOWNLOADER_PATH%" (
    echo Downloading YouTube Downloader from GitHub...
    powershell -Command "Invoke-WebRequest -Uri '%DOWNLOADER_URL%' -OutFile '%TEMP%\yt_dl.zip'; Expand-Archive -Path '%TEMP%\yt_dl.zip' -DestinationPath '%TEMP%\yt_dl_extract' -Force; Move-Item -Path '%TEMP%\yt_dl_extract\yt-downloader-main' -Destination '%DOWNLOADER_PATH%'; Remove-Item '%TEMP%\yt_dl.zip'; Remove-Item -Recurse -Force '%TEMP%\yt_dl_extract' -ErrorAction SilentlyContinue" 2>nul
    if not exist "%DOWNLOADER_PATH%\app.py" (
        echo Failed to download YouTube Downloader. Check your internet connection.
        pause
        exit /b 1
    )
    echo Downloader installed.
) else (
    echo YouTube Downloader already exists.
)

:: ================== YouTube Info Extractor (download latest from GitHub) ==================
if not exist "%INFO_PATH%" mkdir "%INFO_PATH%"
echo Checking for latest Info Extractor update...
powershell -Command "Invoke-WebRequest -Uri '%INFO_APP_URL%' -OutFile '%INFO_PATH%\app.py'" 2>nul
if not exist "%INFO_PATH%\templates" mkdir "%INFO_PATH%\templates"
powershell -Command "Invoke-WebRequest -Uri '%INFO_HTML_URL%' -OutFile '%INFO_PATH%\templates\index.html'" 2>nul
if not exist "%INFO_PATH%\app.py" (
    echo Failed to download Info Extractor files. Check your internet connection.
    pause
    exit /b 1
)
echo Info Extractor updated.

:: ================== Start servers ==================
echo Starting YouTube Downloader on port 5000...
start "YouTube Downloader" cmd /k "cd /d %DOWNLOADER_PATH% && python app.py"

echo Starting YouTube Info Extractor on port 5001...
start "YouTube Info Extractor" cmd /k "cd /d %INFO_PATH% && python app.py"

echo.
echo ====================================================
echo   Both apps are running!
echo   Downloader:    http://127.0.0.1:5000
echo   Info Extractor: http://127.0.0.1:5001
echo ====================================================
echo Close each window with Ctrl+C when done.
echo.

pause

goto :eof

:RefreshEnv
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH ^| findstr /i path') do set "SysPath=%%b"
set "PATH=%SysPath%;%PATH%"
goto :eof
