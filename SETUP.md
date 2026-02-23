# Paragliding Tracker — Deployment Guide

## Prerequisites
- Free [PythonAnywhere](https://www.pythonanywhere.com) account
- Telegram account + a bot created via [@BotFather](https://t.me/BotFather)
- Free [cron-job.org](https://cron-job.org) account (for the 5-minute monitor trigger)

---

## 1. Create your Telegram bot

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (format: `123456789:ABC...XYZ`)

---

## 2. Upload files to PythonAnywhere

**Option A — via Git (recommended)**
```bash
# In a PythonAnywhere Bash console:
git clone https://github.com/YOUR_USERNAME/ParaglidingTracking.git
```

**Option B — upload manually**
Use the PythonAnywhere Files tab to upload the entire project folder.

---

## 3. Set up a virtual environment

In a PythonAnywhere **Bash console**:
```bash
cd ~/ParaglidingTracking
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 4. Create the .env file

```bash
cp .env.example .env
nano .env   # fill in your real values
```

Generate a secure `SECRET_KEY`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Generate a `MONITOR_SECRET`:
```bash
python -c "import secrets; print(secrets.token_hex(16))"
```

---

## 5. Configure the PythonAnywhere web app

1. Go to **Web** tab → **Add a new web app**
2. Choose **Manual configuration** → **Python 3.11**
3. Set **Source code** directory to:
   `/home/YOUR_USERNAME/ParaglidingTracking`
4. Set **WSGI configuration file** — click the link, replace its contents with the contents of `wsgi.py` (update `YOUR_PYTHONANYWHERE_USERNAME`)
5. Set **Virtualenv** path to:
   `/home/YOUR_USERNAME/ParaglidingTracking/venv`
6. Click **Reload**

---

## 6. Register the Telegram webhook

In a PythonAnywhere Bash console, with the venv active:
```bash
source venv/bin/activate
flask set-webhook
```

This tells Telegram to send bot messages to your website. Only needed once.

---

## 7. Set up the 5-minute monitoring cron (cron-job.org)

1. Go to [cron-job.org](https://cron-job.org) → Create free account
2. Create a new cron job:
   - **URL**: `https://yourusername.pythonanywhere.com/api/check?key=YOUR_MONITOR_SECRET`
   - **Method**: POST
   - **Schedule**: Every 5 minutes
3. Save and enable the job

> **Alternative**: PythonAnywhere scheduled tasks (free tier allows hourly minimum).
> For hourly monitoring: Web tab → Tasks → add a scheduled task.

---

## 8. Test everything

1. Visit `https://yourusername.pythonanywhere.com`
2. Register an account
3. Go to **Settings** → copy your link code
4. Open Telegram → your bot → send `/link YOUR_CODE`
5. Go to **Dashboard** → click **Draw Zone** → draw a rectangle over a flying area
6. Wait up to 5 minutes for the first monitoring cycle

---

## PureTrack API notes

The app calls PureTrack's internal traffic API. If you get empty results:

1. Open https://puretrack.io in your browser
2. Open DevTools → Network tab → filter by "traffic" or "api"
3. Reload the page and observe the API request URL and parameters
4. Update `TRAFFIC_URL` and the `params` dict in `puretrack.py` accordingly

---

## Architecture overview

```
Browser (Leaflet.js map)
    │
    ├── draw rectangle → POST /api/zones     (save zone)
    ├── click zone → GET /api/flights/<id>   (live flights, shown on map)
    └── settings → link Telegram code

cron-job.org (every 5 min)
    └── POST /api/check?key=SECRET
            │
            ├── For each active WatchZone:
            │     PureTrack API → filter paragliders → compare with DB state
            │     → Telegram notification if new pilot / altitude jump / pilot left
            └── Update pilot_state table

Telegram bot (@YourBot)
    ├── /start     → instructions
    ├── /link CODE → links Telegram chat_id to user account
    ├── /status    → shows linked zones
    └── /stop      → unlinks account
```
