"""
Paragliding Tracker — Flask web application.

Routes
------
Public
  GET  /               Landing page
  GET  /register       Registration form
  POST /register       Create account
  GET  /login          Login form
  POST /login          Authenticate
  GET  /logout         Log out

Authenticated
  GET  /dashboard      Map + zone management
  GET  /settings       Telegram link settings

REST API (auth required)
  GET    /api/zones              List user's zones (JSON)
  POST   /api/zones              Create zone
  DELETE /api/zones/<id>         Delete zone
  PATCH  /api/zones/<id>/toggle  Enable / disable zone
  GET    /api/flights/<zone_id>  Live flights in a zone (JSON)

Monitoring (called by external cron)
  POST /api/check?key=<MONITOR_SECRET>   Run one monitoring cycle

Telegram webhook (called by Telegram servers)
  POST /telegram/webhook
"""

import json
from functools import wraps

import requests
from flask import (Flask, render_template, redirect, url_for,
                   flash, request, jsonify, abort)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)

from config import Config
from models import db, User, WatchZone, PilotState
from puretrack import get_paragliders
from notifier import send_telegram
import monitor as monitor_engine

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ── DB initialisation ─────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()


# ── Public routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not email or not password:
            flash("Email and password are required.", "danger")
            return render_template("register.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return render_template("register.html")

        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Account created! Welcome aboard.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Authenticated pages ────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    zones = WatchZone.query.filter_by(user_id=current_user.id).all()
    return render_template("dashboard.html", zones=zones)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "regen_code":
            import secrets
            current_user.link_code = secrets.token_hex(4).upper()
            # Unlink Telegram since old code is now invalid
            current_user.telegram_chat_id = None
            db.session.commit()
            flash("Link code regenerated. Please re-link Telegram with the new code.", "info")
        return redirect(url_for("settings"))
    return render_template("settings.html")


# ── Zone API ──────────────────────────────────────────────────────────────────

@app.route("/api/zones", methods=["GET"])
@login_required
def api_zones_list():
    zones = WatchZone.query.filter_by(user_id=current_user.id).all()
    return jsonify([z.to_dict() for z in zones])


@app.route("/api/zones", methods=["POST"])
@login_required
def api_zones_create():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    min_lat = data.get("min_lat")
    max_lat = data.get("max_lat")
    min_lon = data.get("min_lon")
    max_lon = data.get("max_lon")

    if not name:
        return jsonify({"error": "name is required"}), 400
    if None in (min_lat, max_lat, min_lon, max_lon):
        return jsonify({"error": "Bounding box coordinates are required"}), 400

    # Limit per user to prevent abuse
    zone_count = WatchZone.query.filter_by(user_id=current_user.id).count()
    if zone_count >= 10:
        return jsonify({"error": "Maximum 10 zones per account"}), 400

    zone = WatchZone(
        user_id=current_user.id,
        name=name,
        min_lat=float(min_lat),
        max_lat=float(max_lat),
        min_lon=float(min_lon),
        max_lon=float(max_lon),
    )
    db.session.add(zone)
    db.session.commit()
    return jsonify(zone.to_dict()), 201


@app.route("/api/zones/<int:zone_id>", methods=["DELETE"])
@login_required
def api_zones_delete(zone_id):
    zone = WatchZone.query.filter_by(
        id=zone_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(zone)
    db.session.commit()
    return jsonify({"deleted": zone_id})


@app.route("/api/zones/<int:zone_id>/toggle", methods=["PATCH"])
@login_required
def api_zones_toggle(zone_id):
    zone = WatchZone.query.filter_by(
        id=zone_id, user_id=current_user.id
    ).first_or_404()
    zone.is_active = not zone.is_active
    db.session.commit()
    return jsonify(zone.to_dict())


# ── Live flights API ──────────────────────────────────────────────────────────

@app.route("/api/flights/<int:zone_id>")
@login_required
def api_flights(zone_id):
    zone = WatchZone.query.filter_by(
        id=zone_id, user_id=current_user.id
    ).first_or_404()

    pilots = get_paragliders(zone.min_lat, zone.max_lat,
                             zone.min_lon, zone.max_lon)
    result = []
    for p in pilots:
        result.append({
            "key": p["_key"],
            "name": p["_name"],
            "alt": p["_alt"],
            "speed": p["_speed"],
            "lat": p["_lat"],
            "lon": p["_lon"],
        })
    return jsonify(result)


@app.route("/api/flights/all")
@login_required
def api_flights_all():
    """Return all active paragliders in the given map viewport bounding box."""
    try:
        min_lat = float(request.args["min_lat"])
        max_lat = float(request.args["max_lat"])
        min_lon = float(request.args["min_lon"])
        max_lon = float(request.args["max_lon"])
    except (KeyError, ValueError):
        return jsonify({"error": "min_lat, max_lat, min_lon, max_lon required"}), 400

    pilots = get_paragliders(min_lat, max_lat, min_lon, max_lon)
    result = []
    for p in pilots:
        result.append({
            "key":    p["_key"],
            "name":   p["_name"],
            "alt":    p["_alt"],
            "speed":  p["_speed"],
            "vspeed": p.get("_vspeed"),
            "lat":    p["_lat"],
            "lon":    p["_lon"],
            "type":   p.get("_object_type"),
            "age":    p.get("_age"),
        })
    return jsonify({"count": len(result), "pilots": result})


# ── Monitoring endpoint (called by external cron) ─────────────────────────────

@app.route("/api/check", methods=["GET", "POST"])
def api_check():
    provided_key = request.args.get("key", "")
    if provided_key != app.config["MONITOR_SECRET"]:
        abort(401)

    bot_token = app.config["TELEGRAM_BOT_TOKEN"]
    result = monitor_engine.run_check(bot_token)
    return jsonify(result)


# ── Telegram webhook ──────────────────────────────────────────────────────────

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message") or data.get("edited_message", {})
    if not message:
        return "ok"

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()
    bot_token = app.config["TELEGRAM_BOT_TOKEN"]

    if text.startswith("/start"):
        send_telegram(bot_token, chat_id,
                      "👋 Welcome to the Paragliding Tracker bot!\n\n"
                      "To receive notifications, link your account:\n"
                      "1. Log in at your ParaglidingTracker website\n"
                      "2. Go to <b>Settings</b>\n"
                      "3. Copy your 8-character link code\n"
                      "4. Send: /link YOUR_CODE")

    elif text.startswith("/link "):
        code = text.split(" ", 1)[1].strip().upper()
        user = User.query.filter_by(link_code=code).first()
        if not user:
            send_telegram(bot_token, chat_id,
                          "❌ Code not found. Check your Settings page for the correct code.")
        elif user.telegram_chat_id and user.telegram_chat_id != chat_id:
            send_telegram(bot_token, chat_id,
                          "⚠️ This code is already linked to another Telegram account.")
        else:
            user.telegram_chat_id = chat_id
            db.session.commit()
            send_telegram(bot_token, chat_id,
                          f"✅ Linked! You will now receive notifications for "
                          f"{len(user.zones)} watch zone(s).")

    elif text == "/status":
        user = User.query.filter_by(telegram_chat_id=chat_id).first()
        if not user:
            send_telegram(bot_token, chat_id,
                          "You are not linked to any account. Send /link YOUR_CODE to connect.")
        else:
            active = sum(1 for z in user.zones if z.is_active)
            send_telegram(bot_token, chat_id,
                          f"✅ Linked to: {user.email}\n"
                          f"Active zones: {active} / {len(user.zones)}")

    elif text == "/stop":
        user = User.query.filter_by(telegram_chat_id=chat_id).first()
        if user:
            user.telegram_chat_id = None
            db.session.commit()
        send_telegram(bot_token, chat_id,
                      "🔕 Notifications stopped. Your Telegram has been unlinked.\n"
                      "Send /link YOUR_CODE to re-connect any time.")

    return "ok"


# ── Telegram webhook registration helper ─────────────────────────────────────

@app.cli.command("set-webhook")
def set_webhook():
    """Register the Telegram webhook URL.  Run once after deploying."""
    domain = app.config["APP_DOMAIN"]
    token = app.config["TELEGRAM_BOT_TOKEN"]
    if not domain or not token:
        print("ERROR: Set APP_DOMAIN and TELEGRAM_BOT_TOKEN in .env first.")
        return
    url = f"https://api.telegram.org/bot{token}/setWebhook"
    webhook_url = f"https://{domain}/telegram/webhook"
    resp = requests.post(url, json={"url": webhook_url}, timeout=10)
    print(resp.json())


if __name__ == "__main__":
    app.run(debug=True)
