"""
OGN (Open Glider Network) live data client.

Free, no API key required.  Covers all of Europe including the Alps.

Endpoint discovered from live.glidernet.org JavaScript source:
  GET https://live.glidernet.org/lxml.php
  ?a=1       show all aircraft (including recently offline)
  &b=latMax  NE corner latitude
  &c=latMin  SW corner latitude
  &d=lonMax  NE corner longitude
  &e=lonMin  SW corner longitude

Response: XML  <markers><m a="lat,lon,cn,device,alt,time,age,track,speed,vario,type,..."/></markers>

Field index in the comma-separated "a" attribute:
  0  latitude   (decimal degrees)
  1  longitude  (decimal degrees)
  2  callsign / competition number
  3  device ID
  4  altitude   (metres MSL)
  5  last fix time (HH:MM:SS UTC)
  6  age        (seconds since last fix)
  7  track      (degrees)
  8  speed      (km/h)
  9  vario      (m/s)
  10 aircraft type (see OGN type codes below)
  11 receiver station
  12 ICAO hex (or 0)
  13 OGN device ID

OGN aircraft type codes:
  1  glider / motor-glider
  2  tow plane
  3  helicopter
  4  skydiver
  5  drop plane
  6  hang-glider
  7  paraglider   <- main target
  8  powered aircraft
  9  jet
"""

import xml.etree.ElementTree as ET
import requests

OGN_URL = "https://live.glidernet.org/lxml.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://live.glidernet.org/",
}

# OGN type IDs we care about
PARAGLIDER_TYPES = {6, 7}   # 6 = hang-glider, 7 = paraglider

# Heuristic fallback (when aircraft type field is 0 / absent)
MIN_ALT_M    = 50
MAX_ALT_M    = 7_000
MAX_SPEED_KH = 80    # km/h — paragliders rarely exceed this
MAX_AGE_SECS = 600   # ignore fixes older than 10 minutes


# -- XML parser ----------------------------------------------------------------

# Known device-ID prefixes used by FLARM/OGN trackers.
# Stripping these gives a shorter, more readable hex identifier.
_DEVICE_PREFIXES = ("ICA", "FLR", "OGN", "SKY", "PAW", "SAS", "NAV", "RND")


def _format_device_name(device: str) -> str:
    """Turn a cryptic device ID like 'ICA3D1234' into 'Pilot #3D1234'."""
    upper = device.upper()
    for prefix in _DEVICE_PREFIXES:
        if upper.startswith(prefix):
            return f"Pilot #{device[len(prefix):].upper()}"
    return f"Pilot #{device}"


def _parse_marker(attr: str) -> dict | None:
    """Parse one OGN <m a="..."/> attribute string into a normalised dict."""
    parts = attr.split(",")
    if len(parts) < 10:
        return None

    try:
        lat    = float(parts[0])
        lon    = float(parts[1])
        cn     = parts[2].strip()
        device = parts[3].strip()
        alt    = float(parts[4]) if parts[4] else None
        age    = int(parts[6])   if parts[6] else 9999
        speed  = float(parts[8]) if parts[8] else None   # km/h
        vario  = float(parts[9]) if parts[9] else None
        atype  = int(parts[10])  if parts[10] else 0
    except (ValueError, IndexError):
        return None

    # Use callsign as display name; fall back to a human-readable device label
    name = cn if cn and cn != "0" else _format_device_name(device)

    return {
        "_key":         device or cn,
        "_name":        name or "Unknown",
        "_lat":         lat,
        "_lon":         lon,
        "_alt":         alt,
        "_speed":       speed / 3.6 if speed is not None else None,  # m/s for compatibility
        "_speed_kmh":   speed,
        "_vspeed":      vario,
        "_age":         age,
        "_object_type": atype,
    }


# -- API call ------------------------------------------------------------------

def fetch_traffic(min_lat: float, max_lat: float,
                  min_lon: float, max_lon: float,
                  timeout: int = 15) -> list[dict]:
    """
    Fetch all OGN traffic within the bounding box.
    Returns parsed list of dicts, empty list on any error.
    """
    params = {
        "a": 1,           # include recently offline
        "b": max_lat,     # NE corner
        "c": min_lat,     # SW corner
        "d": max_lon,
        "e": min_lon,
    }
    try:
        resp = requests.get(OGN_URL, params=params,
                            headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        results = []
        for m in root.findall("m"):
            parsed = _parse_marker(m.get("a", ""))
            if parsed:
                results.append(parsed)
        return results
    except Exception as exc:
        print(f"[ogn] fetch error: {exc}")
        return []


# -- Paraglider filter ---------------------------------------------------------

def filter_paragliders(traffic: list[dict]) -> list[dict]:
    """
    Keep only likely paragliders / hang-gliders.

    Uses OGN aircraft type first; falls back to altitude + speed heuristic
    for type-0 records (anonymous FLARM devices).
    """
    results = []
    for obj in traffic:
        age   = obj.get("_age", 9999)
        atype = obj.get("_object_type", 0)

        if age > MAX_AGE_SECS:
            continue

        if atype in PARAGLIDER_TYPES:
            results.append(obj)
        elif atype == 0:
            alt   = obj.get("_alt")
            speed_kmh = obj.get("_speed_kmh")
            name  = obj.get("_name", "Unknown")
            if name == "Unknown":
                continue
            if alt is None or not (MIN_ALT_M <= alt <= MAX_ALT_M):
                continue
            if speed_kmh is not None and speed_kmh > MAX_SPEED_KH:
                continue
            results.append(obj)

    return results


# -- Public wrapper ------------------------------------------------------------

def get_paragliders(min_lat: float, max_lat: float,
                    min_lon: float, max_lon: float) -> list[dict]:
    """Fetch OGN traffic and return only likely paragliders."""
    raw = fetch_traffic(min_lat, max_lat, min_lon, max_lon)
    return filter_paragliders(raw)
