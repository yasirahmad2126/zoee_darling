@echo off
REM Set Python path
set PYTHON_PATH=C:\Users\tipu\AppData\Local\Programs\Python\Python313\python.exe

REM Ensure pip is installed and upgraded
"%PYTHON_PATH%" -m ensurepip --upgrade
"%PYTHON_PATH%" -m pip install --upgrade pip

REM Install required modules
"%PYTHON_PATH%" -m pip install flask pywin32 psutil pyautogui

REM Show installed packages
"%PYTHON_PATH%" -m pip list

echo.
echo ✅ All modules installed successfully!
pause
