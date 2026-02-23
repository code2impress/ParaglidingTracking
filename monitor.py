"""
Monitoring engine — compares current PureTrack traffic against stored state
and fires Telegram notifications.

Called from the Flask route  POST /api/check?key=<MONITOR_SECRET>
which is triggered by an external free cron service (e.g. cron-job.org)
every 5 minutes.
"""

from datetime import datetime, timezone, timedelta

from models import db, WatchZone, PilotState
from puretrack import get_paragliders
from notifier import notify_new_pilot, notify_altitude_jump, notify_pilot_left

# How many metres of altitude change counts as a "significant jump"
ALTITUDE_JUMP_THRESHOLD = 300

# After how many minutes without a signal we consider a pilot to have left
PILOT_TIMEOUT_MINUTES = 15


def run_check(bot_token: str, api_key: str) -> dict:
    """
    Main monitoring cycle.

    Iterates every active WatchZone, fetches live paraglider data, compares
    with stored PilotState rows, fires notifications, and updates the DB.

    Returns a summary dict suitable for returning as JSON from the API route.
    """
    now = datetime.now(timezone.utc)
    summary = {"zones_checked": 0, "notifications_sent": 0, "errors": []}

    zones = WatchZone.query.filter_by(is_active=True).all()

    for zone in zones:
        summary["zones_checked"] += 1
        user = zone.user

        if not user.telegram_chat_id:
            # User hasn't linked Telegram yet — skip notifications
            continue

        chat_id = user.telegram_chat_id

        try:
            pilots = get_paragliders(
                zone.min_lat, zone.max_lat, zone.min_lon, zone.max_lon, api_key
            )
        except Exception as exc:
            summary["errors"].append(f"Zone {zone.id}: {exc}")
            continue

        current_keys = {p["_key"] for p in pilots}

        # ── Handle pilots currently in zone ───────────────────────────────────
        for pilot in pilots:
            key = pilot["_key"]
            name = pilot["_name"]
            alt = pilot["_alt"]
            speed = pilot["_speed"]
            lat = pilot["_lat"]
            lon = pilot["_lon"]

            state = PilotState.query.filter_by(
                zone_id=zone.id, pilot_key=key
            ).first()

            if state is None:
                # New pilot — create state row and notify
                state = PilotState(
                    zone_id=zone.id,
                    pilot_key=key,
                    pilot_name=name,
                    last_altitude=alt,
                    last_speed=speed,
                    last_lat=lat,
                    last_lon=lon,
                    first_seen=now,
                    last_seen=now,
                )
                db.session.add(state)

                sent = notify_new_pilot(bot_token, chat_id, name, alt, zone.name)
                if sent:
                    summary["notifications_sent"] += 1
            else:
                # Known pilot — check for significant altitude jump
                if (state.last_altitude is not None and alt is not None
                        and abs(alt - state.last_altitude) >= ALTITUDE_JUMP_THRESHOLD):
                    sent = notify_altitude_jump(
                        bot_token, chat_id, name,
                        state.last_altitude, alt, zone.name
                    )
                    if sent:
                        summary["notifications_sent"] += 1

                # Update stored state
                state.pilot_name = name
                state.last_altitude = alt
                state.last_speed = speed
                state.last_lat = lat
                state.last_lon = lon
                state.last_seen = now

        # ── Handle pilots that left the zone ──────────────────────────────────
        timeout_cutoff = now - timedelta(minutes=PILOT_TIMEOUT_MINUTES)

        stale = PilotState.query.filter(
            PilotState.zone_id == zone.id,
            PilotState.pilot_key.notin_(current_keys),
            PilotState.last_seen < timeout_cutoff,
        ).all()

        for state in stale:
            notify_pilot_left(bot_token, chat_id, state.pilot_name or "Unknown",
                              zone.name)
            summary["notifications_sent"] += 1
            db.session.delete(state)

    db.session.commit()
    summary["timestamp"] = now.isoformat()
    return summary
