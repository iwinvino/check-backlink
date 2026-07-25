@echo off
cd /d "%~dp0"
echo ============================================
echo   TOOL CHECK BACKLINK SEO - Dang khoi dong
echo ============================================
python -m pip install -r requirements.txt --quiet
python -m streamlit run app.py
pause
