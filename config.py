import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask secret key - change this in .env for production
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

    # Database - SQLite works great on PythonAnywhere free tier
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///paragliding.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Telegram Bot
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    # Secret key for the /api/check monitoring endpoint (called by external cron)
    MONITOR_SECRET = os.environ.get("MONITOR_SECRET", "change-me-monitor-secret")

    # PureTrack API key
    PURETRACK_API_KEY = os.environ.get("PURETRACK_API_KEY", "")

    # Your PythonAnywhere domain (needed to register Telegram webhook)
    # Example: "yourusername.pythonanywhere.com"
    APP_DOMAIN = os.environ.get("APP_DOMAIN", "")
