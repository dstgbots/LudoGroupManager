#!/usr/bin/env python3
"""
Installation and setup script for Ludo Group Manager Bot
"""

import subprocess
import sys
import os

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"📦 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e.stderr}")
        return False

def check_python_version():
    """Check if Python version is compatible"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("❌ Python 3.8 or higher is required")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} detected")
    return True

def install_dependencies():
    """Install required Python packages"""
    print("\n🔧 Installing Dependencies")
    print("=" * 30)
    
    dependencies = [
        "python-telegram-bot==20.7",
        "pymongo==4.6.1", 
        "python-dotenv==1.0.0"
    ]
    
    for dep in dependencies:
        if not run_command(f"pip install {dep}", f"Installing {dep}"):
            return False
    
    return True

def check_mongodb():
    """Check if MongoDB is accessible"""
    print("\n🔍 Checking MongoDB Connection")
    print("=" * 35)
    
    try:
        from pymongo import MongoClient
        client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=2000)
        client.server_info()
        print("✅ MongoDB connection successful")
        return True
    except Exception as e:
        print("❌ MongoDB connection failed")
        print(f"   Error: {e}")
        print("\n💡 MongoDB Installation Guide:")
        print("   Windows: Download from https://www.mongodb.com/try/download/community")
        print("   Linux: sudo apt install mongodb (Ubuntu/Debian)")
        print("   macOS: brew install mongodb-community")
        return False

def main():
    """Main installation function"""
    print("🎮 Ludo Group Manager Bot - Installation")
    print("=" * 45)
    
    # Check Python version
    if not check_python_version():
        sys.exit(1)
    
    # Install dependencies
    if not install_dependencies():
        print("\n❌ Installation failed during dependency installation")
        sys.exit(1)
    
    # Check MongoDB
    mongodb_ok = check_mongodb()
    
    print("\n🎉 Installation Summary")
    print("=" * 25)
    print("✅ Python dependencies installed")
    print(f"{'✅' if mongodb_ok else '❌'} MongoDB {'connected' if mongodb_ok else 'not accessible'}")
    
    if mongodb_ok:
        print("\n🚀 Next Steps:")
        print("1. Run: python setup_env.py (to configure bot settings)")
        print("2. Run: python start_bot.py (to start the bot)")
    else:
        print("\n⚠️  Please install and start MongoDB before proceeding")
        print("Then run: python setup_env.py")
    
    print("\n📖 For detailed setup instructions, see README.md")

if __name__ == "__main__":
    main()
