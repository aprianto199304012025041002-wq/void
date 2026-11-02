@echo off
echo ============================================================
echo  Claude Orchestrator - Streamlit Web UI
echo ============================================================
echo.

REM Cari python
set PYTHON=python
where python >nul 2>&1
if errorlevel 1 (
    set PYTHON="C:\Users\BALMON 019\AppData\Local\Programs\Python\Python313\python.exe"
)

echo [1/3] Menginstal dependensi ...
%PYTHON% -m pip install -r requirements.txt --quiet

echo [2/3] Menginstal browser Playwright (jika belum) ...
%PYTHON% -m playwright install chromium

echo [3/3] Menjalankan Streamlit ...
echo.
echo  Buka browser di: http://localhost:8501
echo  Tekan Ctrl+C untuk berhenti.
echo.
%PYTHON% -m streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0 --browser.gatherUsageStats false

pause
