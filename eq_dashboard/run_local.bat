@echo off
REM Jalankan dashboard di PC ini saja (tidak terbuka ke jaringan)
cd /d "%~dp0"
.venv\Scripts\streamlit run app.py --server.address 127.0.0.1 --server.port 8501
