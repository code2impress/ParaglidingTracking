"""
PureTrack API client.

Real endpoint: GET https://puretrack.io/api/traffic
Parameters:
  key   — PureTrack API key
  lat1  — NE corner latitude   (max_lat)
  long1 — NE corner longitude  (max_lon)
  lat2  — SW corner latitude   (min_lat)
  long2 — SW corner longitude  (min_lon)
  t     — max age in minutes (default 5)

Response:
{
  "data": ["T1713592586,L47.63,G12.44,A1800,S4.2,V1.1,O7,KABCxyz,mPilotName,..."],
  "success": true
}

Each row is a compact comma-separated string where each token is:
  T = unix timestamp
  L = latitude
  G = longitude
  A = altitude (metres)
  S = speed (m/s)
  V = vertical speed (m/s)
  C = course (degrees)
  O = object type  (7 = paraglider / hang-glider)
  K = unique tracker key
  E = registration / callsign
  m = display name / pilot name
"""

import requests

TRAFFIC_URL = "https://puretrack.io/api/traffic"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://puretrack.io/",
    "Accept": "application/json",
}

# PureTrack object type 7 = paraglider / hang-glider
PARAGLIDER_TYPES = {7}

# Fallback heuristic (used when object type is absent in the record)
MIN_ALT_M    = 50
MAX_ALT_M    = 7_000
MAX_SPEED_MS = 25   # m/s ≈ 90 km/h


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_record(record_str: str) -> dict:
    """
    Convert a compact PureTrack data string into a normalised dict.
    Example input: "T1713592586,L47.63,G12.44,A1200,S3.1,V0.8,O7,KXYZabc,mHansPilot"
    """
    raw = {}
    for token in record_str.split(","):
        if len(token) >= 2:
            raw[token[0]] = token[1:]

    lat   = float(raw["L"]) if "L" in raw else None
    lon   = float(raw["G"]) if "G" in raw else None
    alt   = float(raw["A"]) if "A" in raw else None
    speed = float(raw["S"]) if "S" in raw else None

    # Best available display name: pilot name > registration > tracker key
    name = raw.get("m") or raw.get("E") or raw.get("K", "Unknown")
    key  = raw.get("K") or raw.get("E") or record_str[:24]

    return {
        "_key":         key,
        "_name":        name,
        "_lat":         lat,
        "_lon":         lon,
        "_alt":         alt,
        "_speed":       speed,
        "_vspeed":      float(raw["V"]) if "V" in raw else None,
        "_object_type": int(raw["O"])   if "O" in raw else None,
        "_timestamp":   int(raw["T"])   if "T" in raw else None,
    }


# ── API call ──────────────────────────────────────────────────────────────────

def fetch_traffic(min_lat: float, max_lat: float,
                  min_lon: float, max_lon: float,
                  api_key: str,
                  timeout: int = 15) -> list[dict]:
    """
    Fetch all traffic within the bounding box from PureTrack.
    Returns parsed list of dicts, empty on any error.
    """
    params = {
        "key":   api_key,
        "lat1":  max_lat,   # NE corner
        "long1": max_lon,
        "lat2":  min_lat,   # SW corner
        "long2": min_lon,
        "t":     5,         # max age: 5 minutes
    }
    try:
        resp = requests.get(TRAFFIC_URL, params=params,
                            headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        raw_list = data.get("data", [])
        return [_parse_record(r) for r in raw_list if isinstance(r, str)]
    except Exception as exc:
        print(f"[puretrack] fetch error: {exc}")
        return []


# ── Paraglider filter ─────────────────────────────────────────────────────────

def filter_paragliders(traffic: list[dict]) -> list[dict]:
    """
    Keep only likely paragliders / hang-gliders.

    If PureTrack reports object_type, use it (type 7 = paraglider).
    If object_type is missing, fall back to altitude + speed heuristic.
    """
    results = []
    for obj in traffic:
        obj_type = obj.get("_object_type")

        if obj_type is not None:
            if obj_type in PARAGLIDER_TYPES:
                results.append(obj)
            # Known non-paraglider type — skip
        else:
            # Unknown type — apply heuristic
            alt   = obj.get("_alt")
            speed = obj.get("_speed")
            name  = obj.get("_name", "Unknown")
            if name == "Unknown":
                continue
            if alt is None or not (MIN_ALT_M <= alt <= MAX_ALT_M):
                continue
            if speed is not None and speed > MAX_SPEED_MS:
                continue
            results.append(obj)

    return results


# ── Public wrapper ────────────────────────────────────────────────────────────

def get_paragliders(min_lat: float, max_lat: float,
                    min_lon: float, max_lon: float,
                    api_key: str) -> list[dict]:
    """Fetch traffic and return only likely paragliders."""
    raw = fetch_traffic(min_lat, max_lat, min_lon, max_lon, api_key)
    return filter_paragliders(raw)
