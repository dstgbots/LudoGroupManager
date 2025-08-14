#!/bin/bash

# LudoManager Startup Script for Linux/Mac
echo "====================================="
echo "    LudoManager Startup Script"
echo "====================================="
echo

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo "❌ Python not found! Please install Python 3.8+"
        exit 1
    else
        PYTHON_CMD="python"
    fi
else
    PYTHON_CMD="python3"
fi

# Check if we're in the right directory
if [ ! -f "test.py" ]; then
    echo "❌ test.py not found! Make sure you're in the LudoManagerMain folder"
    exit 1
fi

if [ ! -f "bot.py" ]; then
    echo "❌ bot.py not found! Make sure you're in the LudoManagerMain folder"
    exit 1
fi

echo "✅ Python found ($PYTHON_CMD)"
echo "✅ LudoManager files found"
echo

# Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "📦 Installing/checking dependencies..."
    $PYTHON_CMD -m pip install -r requirements.txt
    echo
fi

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️ WARNING: .env file not found!"
    echo "📝 Please create .env file from env_template.txt"
    echo
    echo "Press Enter to continue anyway, or Ctrl+C to exit and create .env first"
    read
fi

echo "🚀 Starting LudoManager..."
echo "📡 Pyrogram listener + Bot manager integration"
echo "🛑 Press Ctrl+C to stop"
echo "====================================="
echo

# Start the integrated system
$PYTHON_CMD test.py

echo
echo "👋 LudoManager stopped"
