@echo off
echo Starting FastAPI application...
start /b python api.py

echo.
echo Starting Localtunnel on Port 8000...
echo Waiting 5 seconds for API to initialize...
timeout /t 5 /nobreak >nul

echo.
echo =======================================================
echo If you get an error about 'Execution Policies' for npx, 
echo the tunnel might not start. If it works, it will print 
echo 'your url is: https://...' below.
echo =======================================================
call npx.cmd localtunnel --port 8000
