@echo off
setlocal
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -m venv .venv
  if errorlevel 1 goto error
)
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
.venv\Scripts\python.exe -m streamlit run app.py
if errorlevel 1 goto error
goto end
:error
echo Setup or launch failed. Read the error above and check README.md.
pause
:end
endlocal
