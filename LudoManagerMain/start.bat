@echo off
echo =====================================
echo    LudoManager Startup Script
echo =====================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found! Please install Python 3.8+
    pause
    exit /b 1
)

REM Check if we're in the right directory
if not exist "test.py" (
    echo ❌ test.py not found! Make sure you're in the LudoManagerMain folder
    pause
    exit /b 1
)

if not exist "bot.py" (
    echo ❌ bot.py not found! Make sure you're in the LudoManagerMain folder
    pause
    exit /b 1
)

echo ✅ Python found
echo ✅ LudoManager files found
echo.

REM Install dependencies if requirements.txt exists
if exist "requirements.txt" (
    echo 📦 Installing/checking dependencies...
    pip install -r requirements.txt
    echo.
)

REM Check for .env file
if not exist ".env" (
    echo ⚠️ WARNING: .env file not found!
    echo 📝 Please create .env file from env_template.txt
    echo.
    echo Press any key to continue anyway, or Ctrl+C to exit and create .env first
    pause
)

echo 🚀 Starting LudoManager...
echo 📡 Pyrogram listener + Bot manager integration
echo 🛑 Press Ctrl+C to stop
echo =====================================
echo.

REM Start the integrated system
python test.py

echo.
echo 👋 LudoManager stopped
pause
