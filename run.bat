@echo off
cd /d %~dp0
echo Epoch B-roll: http://localhost:8000  (LAN: use this PC's IP from ipconfig)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
