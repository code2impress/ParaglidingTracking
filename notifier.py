"""
Telegram notification sender.

All messages go through send_telegram().  The higher-level helpers
(notify_new_pilot, notify_altitude_jump, notify_pilot_landed) format
the text and delegate to it.
"""

import requests


def send_telegram(bot_token: str, chat_id: str, text: str) -> bool:
    """
    Send a Telegram message.  Returns True on success, False on error.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"[notifier] Telegram error for chat {chat_id}: {exc}")
        return False


# ── Notification helpers ───────────────────────────────────────────────────────

def notify_new_pilot(bot_token: str, chat_id: str,
                     pilot_name: str, altitude: float,
                     zone_name: str) -> bool:
    text = (
        f"🪂 <b>New pilot appeared!</b>\n"
        f"Zone: <b>{zone_name}</b>\n"
        f"Pilot: {pilot_name}\n"
        f"Altitude: {int(altitude)} m"
    )
    return send_telegram(bot_token, chat_id, text)


def notify_altitude_jump(bot_token: str, chat_id: str,
                         pilot_name: str, old_alt: float, new_alt: float,
                         zone_name: str) -> bool:
    direction = "↑" if new_alt > old_alt else "↓"
    text = (
        f"📈 <b>Altitude change!</b>\n"
        f"Zone: <b>{zone_name}</b>\n"
        f"Pilot: {pilot_name}\n"
        f"Altitude: {int(old_alt)} m {direction} {int(new_alt)} m "
        f"({int(new_alt - old_alt):+d} m)"
    )
    return send_telegram(bot_token, chat_id, text)


def notify_pilot_left(bot_token: str, chat_id: str,
                      pilot_name: str, zone_name: str) -> bool:
    text = (
        f"🏁 <b>Pilot left the zone</b>\n"
        f"Zone: <b>{zone_name}</b>\n"
        f"Pilot: {pilot_name}"
    )
    return send_telegram(bot_token, chat_id, text)
