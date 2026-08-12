@echo off
REM ============================================================
REM  LandIQ - Langflow launcher
REM  Double-click this file to start Langflow correctly.
REM  Auth is disabled for local dev so the API works from api.py.
REM ============================================================

cd /d C:\Users\HP\OneDrive\Desktop\ai_boardroom_v3

call langflow_env\Scripts\activate.bat

set LANGFLOW_AUTO_LOGIN=true
set LANGFLOW_SKIP_AUTH_AUTO_LOGIN=true
set LANGFLOW_WORKER_TIMEOUT=700

echo.
echo ============================================================
echo  Starting Langflow on http://localhost:7860
echo  Auth wall: DISABLED (local dev)
echo  Leave this window OPEN while you demo.
echo ============================================================
echo.

langflow run --port 7860

pause
