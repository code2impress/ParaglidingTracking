"""
PureTrack API client + paraglider filter.

The bounding-box conversion from a PureTrack URL
  https://puretrack.io/?l=<lat>,<lon>&z=<zoom>
to a geographic rectangle uses the same formula as your original script.

NOTE: PureTrack does not publish an official public API.
The endpoint below was identified by watching browser network requests on puretrack.io.
If it changes, open DevTools → Network → filter "api" while the map is loaded to find
the updated endpoint and adjust TRAFFIC_URL accordingly.
"""

import requests

# ── API configuration ──────────────────────────────────────────────────────────
TRAFFIC_URL = "https://puretrack.io/api/v2/traffic"

# Simulate a real browser so the request isn't rejected
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://puretrack.io/",
    "Accept": "application/json",
}

# ── Paraglider heuristic thresholds ───────────────────────────────────────────
MIN_ALT_M = 300        # below this → probably on the ground
MAX_ALT_M = 7_000      # above this → likely an airplane or glider at altitude
MAX_SPEED_MS = 20      # m/s ≈ 72 km/h — paragliders rarely exceed this


# ── Bounding box helpers ───────────────────────────────────────────────────────

def zoom_to_bbox(center_lat: float, center_lon: float,
                 zoom: float, factor: float = 1.0) -> dict:
    """
    Convert a PureTrack URL center + zoom level to a lat/lon bounding box.

    factor > 1 expands the visible area (useful to catch pilots just outside
    the visible window).  factor = 1 matches the browser view exactly.
    """
    lat_span = (180 / (2 ** zoom)) * factor
    lon_span = (360 / (2 ** zoom)) * factor
    return {
        "min_lat": center_lat - lat_span / 2,
        "max_lat": center_lat + lat_span / 2,
        "min_lon": center_lon - lon_span / 2,
        "max_lon": center_lon + lon_span / 2,
    }


# ── Main API call ──────────────────────────────────────────────────────────────

def fetch_traffic(min_lat: float, max_lat: float,
                  min_lon: float, max_lon: float,
                  timeout: int = 15) -> list[dict]:
    """
    Fetch all traffic objects inside the given bounding box from PureTrack.

    Returns a list of raw traffic objects (dicts) as returned by the API.
    Returns an empty list on any error so the caller can continue safely.
    """
    params = {
        "sw": f"{min_lat},{min_lon}",
        "ne": f"{max_lat},{max_lon}",
    }
    try:
        resp = requests.get(TRAFFIC_URL, params=params,
                            headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # The API returns either a list or {"data": [...]}
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data", data.get("traffic", []))
        return []
    except Exception as exc:
        print(f"[puretrack] fetch error: {exc}")
        return []


# ── Paraglider filter ──────────────────────────────────────────────────────────

def _pilot_key(obj: dict) -> str:
    """Return a stable unique key for a traffic object."""
    # Try common ID fields; fall back to name
    for field in ("id", "uid", "object_id", "callsign", "name", "label"):
        val = obj.get(field)
        if val:
            return str(val)
    return str(obj)


def _pilot_name(obj: dict) -> str:
    for field in ("name", "label", "callsign", "pilot"):
        val = obj.get(field)
        if val:
            return str(val)
    return "Unknown"


def _altitude(obj: dict) -> float | None:
    for field in ("altitude", "alt", "altitude_m", "elevation"):
        val = obj.get(field)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def _speed(obj: dict) -> float | None:
    for field in ("speed", "speed_ms", "groundspeed"):
        val = obj.get(field)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def filter_paragliders(traffic: list[dict]) -> list[dict]:
    """
    Apply heuristic filter to keep only likely paragliders.

    Keeps objects that:
      - have an altitude between MIN_ALT_M and MAX_ALT_M
      - have a speed at or below MAX_SPEED_MS (or no speed reported)
      - have some name/label (rules out anonymous transponders)
    """
    results = []
    for obj in traffic:
        alt = _altitude(obj)
        speed = _speed(obj)
        name = _pilot_name(obj)

        if name == "Unknown":
            continue
        if alt is None or not (MIN_ALT_M <= alt <= MAX_ALT_M):
            continue
        if speed is not None and speed > MAX_SPEED_MS:
            continue

        # Attach normalised fields so callers don't need to re-parse
        obj["_key"] = _pilot_key(obj)
        obj["_name"] = name
        obj["_alt"] = alt
        obj["_speed"] = speed
        obj["_lat"] = obj.get("lat") or obj.get("latitude")
        obj["_lon"] = obj.get("lon") or obj.get("lng") or obj.get("longitude")
        results.append(obj)

    return results


# ── Convenience wrapper ────────────────────────────────────────────────────────

def get_paragliders(min_lat: float, max_lat: float,
                    min_lon: float, max_lon: float) -> list[dict]:
    """Fetch traffic and return only likely paragliders."""
    raw = fetch_traffic(min_lat, max_lat, min_lon, max_lon)
    return filter_paragliders(raw)
