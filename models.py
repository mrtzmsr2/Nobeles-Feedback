"""Datenbankmodelle für Nobeles-Feedback."""
from datetime import datetime
import secrets

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def _token(n: int = 16) -> str:
    return secrets.token_urlsafe(n)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    rolle = db.Column(db.String(20), nullable=False, default="viewer")  # admin | leiter | viewer
    standort_id = db.Column(db.Integer, db.ForeignKey("standorte.id"), nullable=True)
    is_active_flag = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    standort = db.relationship("Standort", backref="benutzer")

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self) -> bool:
        return self.rolle == "admin"

    @property
    def is_leiter(self) -> bool:
        return self.rolle == "leiter"

    @property
    def is_active(self) -> bool:  # Flask-Login Hook
        return bool(self.is_active_flag)


class Standort(db.Model):
    __tablename__ = "standorte"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    adresse = db.Column(db.String(255), nullable=True)
    region = db.Column(db.String(80), nullable=True)
    aktiv = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    automaten = db.relationship(
        "Automat", backref="standort", cascade="all, delete-orphan", lazy=True
    )


class Automat(db.Model):
    __tablename__ = "automaten"
    id = db.Column(db.Integer, primary_key=True)
    standort_id = db.Column(db.Integer, db.ForeignKey("standorte.id"), nullable=False)
    bezeichnung = db.Column(db.String(120), nullable=False)  # z.B. "Küche EG"
    modell = db.Column(db.String(120), nullable=True)
    lieferant = db.Column(db.String(120), nullable=True)
    qr_token = db.Column(db.String(40), unique=True, nullable=False, default=lambda: _token(16))
    aktiv = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    feedbacks = db.relationship(
        "Feedback", backref="automat", cascade="all, delete-orphan", lazy=True
    )


class Feedback(db.Model):
    __tablename__ = "feedbacks"
    id = db.Column(db.Integer, primary_key=True)
    automat_id = db.Column(db.Integer, db.ForeignKey("automaten.id"), nullable=False)
    bewertung = db.Column(db.Integer, nullable=False)  # 1..5
    # kommagetrennte Liste der Kategorien (geschmack,sauberkeit,verfuegbarkeit,auswahl,temperatur,bedienung,sonstiges)
    kategorien = db.Column(db.String(255), nullable=True)
    # Strukturierter Feedbackbogen
    was_gut = db.Column(db.Text, nullable=True)
    was_schlecht = db.Column(db.Text, nullable=True)
    verbesserung = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    @property
    def kategorie_liste(self) -> list[str]:
        return [k.strip() for k in (self.kategorien or "").split(",") if k.strip()]

    @property
    def bewertung_emoji(self) -> str:
        return {1: "😡", 2: "🙁", 3: "😐", 4: "🙂", 5: "😍"}.get(self.bewertung, "❓")

    @property
    def hat_text(self) -> bool:
        return bool(self.was_gut or self.was_schlecht or self.verbesserung)
