from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    telegram_chat_id = db.Column(db.String(64), unique=True, nullable=True)
    # 8-char code users type in Telegram to link their account
    link_code = db.Column(db.String(16), unique=True, nullable=False,
                          default=lambda: secrets.token_hex(4).upper())
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    zones = db.relationship("WatchZone", backref="user", lazy=True,
                            cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def telegram_linked(self):
        return self.telegram_chat_id is not None


class WatchZone(db.Model):
    __tablename__ = "watch_zones"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)

    # Bounding box (drawn rectangle)
    min_lat = db.Column(db.Float, nullable=False)
    max_lat = db.Column(db.Float, nullable=False)
    min_lon = db.Column(db.Float, nullable=False)
    max_lon = db.Column(db.Float, nullable=False)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    pilots = db.relationship("PilotState", backref="zone", lazy=True,
                             cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
            "is_active": self.is_active,
        }


class PilotState(db.Model):
    """Tracks the last known state of a pilot in a watch zone.
    Used to detect new arrivals and altitude jumps.
    """
    __tablename__ = "pilot_state"

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey("watch_zones.id"), nullable=False)

    # Unique identifier for the pilot (from PureTrack - could be name or ID)
    pilot_key = db.Column(db.String(128), nullable=False)
    pilot_name = db.Column(db.String(128), nullable=True)

    last_altitude = db.Column(db.Float, nullable=True)
    last_speed = db.Column(db.Float, nullable=True)
    last_lat = db.Column(db.Float, nullable=True)
    last_lon = db.Column(db.Float, nullable=True)

    first_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("zone_id", "pilot_key", name="uq_zone_pilot"),
    )
