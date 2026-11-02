@echo off
echo ============================================================
echo  Claude Orchestrator - Server PC (FastAPI + Cloudflare)
echo ============================================================
echo.

set PYTHON=python
where python >nul 2>&1
if errorlevel 1 set PYTHON="C:\Users\BALMON 019\AppData\Local\Programs\Python\Python313\python.exe"

echo [1/3] Install dependensi ...
%PYTHON% -m pip install fastapi uvicorn[standard] requests --quiet

echo [2/3] Menjalankan FastAPI server di port 8000 ...
start "Claude API Server" cmd /k "%PYTHON% -m uvicorn server:app --host 0.0.0.0 --port 8000"

echo [3/3] Menjalankan Cloudflare Tunnel ...
echo        (Jika cloudflared belum ada, akan didownload otomatis)
echo.

REM Download cloudflared jika belum ada
if not exist cloudflared.exe (
    echo Mendownload cloudflared.exe ...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
)

echo.
echo ============================================================
echo  SALIN URL di bawah ini ke kolom "URL Server" di Streamlit!
echo ============================================================
echo.
cloudflared.exe tunnel --url http://localhost:8000

pause
