"""
تشغيل البوت والـ API معاً في نفس الـ Process
"""

import asyncio
import threading
import uvicorn
from telegram.ext import Application
from bot import main as run_bot, BOT_TOKEN
import api_bridge

def start_api():
    uvicorn.run(api_bridge.app, host="0.0.0.0", port=8000, log_level="warning")

def main():
    # شغّل الـ API في خلفية
    t = threading.Thread(target=start_api, daemon=True)
    t.start()
    print("✅ API  → http://localhost:8000")
    print("📖 Docs → http://localhost:8000/docs")

    # شغّل البوت
    print("🤖 Starting Bot...")
    run_bot()

if __name__ == "__main__":
    main()
