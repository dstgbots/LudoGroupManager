#!/usr/bin/env python3
"""
Test script to verify API credentials and Pyrogram connection
"""

import os
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_pyrogram_credentials():
    """Test Pyrogram client initialization with API credentials"""
    try:
        from pyrogram import Client
        
        print("🔍 Testing Pyrogram API credentials...")
        
        # Get credentials from environment
        api_id = os.getenv("API_ID")
        api_hash = os.getenv("API_HASH")
        session_string = os.getenv("PYROGRAM_SESSION_STRING")
        
        print(f"📱 API ID: {api_id}")
        print(f"🔑 API Hash: {api_hash[:10]}..." if api_hash else "❌ Not found")
        print(f"🔗 Session String: {session_string[:20]}..." if session_string else "❌ Not found")
        
        if not all([api_id, api_hash, session_string]):
            print("❌ Missing required credentials!")
            return False
        
        # Initialize client
        print("\n🚀 Initializing Pyrogram client...")
        client = Client(
            "test_session",
            api_id=int(api_id),
            api_hash=api_hash,
            session_string=session_string,
            no_updates=True,
            in_memory=True
        )
        
        print("✅ Client initialized successfully")
        
        # Test connection
        print("\n🔌 Testing connection...")
        await client.start()
        print("✅ Connection successful")
        
        # Get client info
        me = await client.get_me()
        print(f"👤 Connected as: {me.first_name} (@{me.username})")
        
        # Stop client
        await client.stop()
        print("✅ Client stopped successfully")
        
        return True
        
    except ImportError:
        print("❌ Pyrogram not installed. Run: pip install pyrogram>=2.0.0,<3.0.0")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

async def main():
    """Main test function"""
    print("🧪 Testing Pyrogram API Credentials\n")
    
    success = await test_pyrogram_credentials()
    
    if success:
        print("\n🎉 All tests passed! API credentials are working correctly.")
    else:
        print("\n💥 Tests failed. Please check your configuration.")

if __name__ == "__main__":
    asyncio.run(main())
