"""Nobeles-Feedback — Flask-Hauptanwendung.

Mitarbeiter-Feedback für Kaffeeautomaten an den Standorten der BCW-Gruppe.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import qrcode
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import func

from models import Automat, Feedback, Standort, User, db

# ── Konfiguration ───────────────────────────────────────────
load_dotenv()
BASE_DIR = Path(__file__).parent.resolve()
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

ALLOWED_EMAIL_DOMAINS = [
    d.strip().lower()
    for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "bcw-gruppe.de").split(",")
    if d.strip()
]

KATEGORIEN_VERFUEGBAR = [
    ("geschmack", "☕ Geschmack"),
    ("sauberkeit", "🧼 Sauberkeit"),
    ("verfuegbarkeit", "📦 Verfügbarkeit (leer / aufgefüllt)"),
    ("auswahl", "🎯 Auswahl"),
    ("temperatur", "🌡️ Temperatur"),
    ("bedienung", "🖐️ Bedienung"),
    ("sonstiges", "💬 Sonstiges"),
]

# ── App-Factory ─────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-please-change")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{INSTANCE_DIR / 'nobeles_feedback.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Bitte zuerst anmelden."
login_manager.login_message_category = "info"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


# ── Helper ──────────────────────────────────────────────────
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def email_domain_allowed(email: str) -> bool:
    email = (email or "").lower().strip()
    if not EMAIL_RE.match(email):
        return False
    domain = email.rsplit("@", 1)[1]
    return domain in ALLOWED_EMAIL_DOMAINS


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def staff_required(fn):
    """Admin oder Standortleiter."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not (current_user.is_admin or current_user.is_leiter):
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def standort_zugriff(standort_id: int | None) -> bool:
    """Darf der aktuelle User diesen Standort sehen?"""
    if current_user.is_admin:
        return True
    if current_user.is_leiter and current_user.standort_id == standort_id:
        return True
    return False


def visible_standorte():
    if current_user.is_admin:
        return Standort.query.order_by(Standort.name).all()
    if current_user.is_leiter and current_user.standort_id:
        return Standort.query.filter_by(id=current_user.standort_id).all()
    return []


@app.context_processor
def inject_globals():
    return {
        "ALLOWED_EMAIL_DOMAINS": ALLOWED_EMAIL_DOMAINS,
        "KATEGORIEN_VERFUEGBAR": KATEGORIEN_VERFUEGBAR,
        "now": datetime.utcnow(),
    }


@app.template_filter("dt")
def fmt_dt(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not value:
        return ""
    return value.strftime(fmt)


@app.template_filter("d")
def fmt_d(value: datetime | None, fmt: str = "%d.%m.%Y") -> str:
    if not value:
        return ""
    return value.strftime(fmt)


# ── Erst-Initialisierung ────────────────────────────────────
def ensure_initial_admin() -> None:
    email = os.environ.get("INITIAL_ADMIN_EMAIL", "").strip().lower()
    pw = os.environ.get("INITIAL_ADMIN_PASSWORD", "").strip()
    name = os.environ.get("INITIAL_ADMIN_NAME", "Admin").strip()
    if not email or not pw:
        return
    if User.query.filter_by(rolle="admin").first():
        return
    if User.query.filter_by(email=email).first():
        return
    if not email_domain_allowed(email):
        app.logger.warning("INITIAL_ADMIN_EMAIL hat keine erlaubte Domain — wird ignoriert.")
        return
    u = User(email=email, name=name, rolle="admin")
    u.set_password(pw)
    db.session.add(u)
    db.session.commit()
    app.logger.info("Initialer Admin angelegt: %s", email)


with app.app_context():
    db.create_all()
    ensure_initial_admin()


# ════════════════════════════════════════════════════════════
# Öffentliche Routen — Feedback per QR (ohne Login)
# ════════════════════════════════════════════════════════════
@app.route("/")
def root():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/f/<token>", methods=["GET", "POST"])
def feedback_form(token: str):
    automat = Automat.query.filter_by(qr_token=token, aktiv=True).first_or_404()

    if request.method == "POST":
        try:
            bewertung = int(request.form.get("bewertung", "0"))
        except ValueError:
            bewertung = 0
        if bewertung < 1 or bewertung > 5:
            flash("Bitte eine Bewertung auswählen.", "danger")
            return render_template("feedback.html", automat=automat)

        kategorien = request.form.getlist("kategorien")
        kategorien_str = ",".join(k for k in kategorien if k)
        was_gut = (request.form.get("was_gut") or "").strip()[:2000]
        was_schlecht = (request.form.get("was_schlecht") or "").strip()[:2000]
        verbesserung = (request.form.get("verbesserung") or "").strip()[:2000]

        fb = Feedback(
            automat_id=automat.id,
            bewertung=bewertung,
            kategorien=kategorien_str or None,
            was_gut=was_gut or None,
            was_schlecht=was_schlecht or None,
            verbesserung=verbesserung or None,
        )
        db.session.add(fb)
        db.session.commit()
        return redirect(url_for("feedback_thanks", token=token))

    return render_template("feedback.html", automat=automat)


@app.route("/f/<token>/danke")
def feedback_thanks(token: str):
    automat = Automat.query.filter_by(qr_token=token).first_or_404()
    return render_template("feedback_thanks.html", automat=automat)


# ════════════════════════════════════════════════════════════
# Auth
# ════════════════════════════════════════════════════════════
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(pw) or not user.is_active:
            flash("E-Mail oder Passwort ungültig.", "danger")
            return render_template("login.html")
        user.last_login = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=True, duration=timedelta(days=14))
        flash(f"Willkommen, {user.name}!", "success")
        return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Abgemeldet.", "info")
    return redirect(url_for("login"))


@app.route("/registrieren", methods=["GET", "POST"])
def registrieren():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        pw2 = request.form.get("password2") or ""

        if not name or not email or not pw:
            flash("Bitte alle Felder ausfüllen.", "danger")
        elif not email_domain_allowed(email):
            flash(
                f"Registrierung nur mit E-Mail-Adressen folgender Domains: "
                f"{', '.join(ALLOWED_EMAIL_DOMAINS)}",
                "danger",
            )
        elif len(pw) < 10:
            flash("Passwort muss mindestens 10 Zeichen lang sein.", "danger")
        elif pw != pw2:
            flash("Passwörter stimmen nicht überein.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Diese E-Mail ist bereits registriert.", "danger")
        else:
            u = User(email=email, name=name, rolle="viewer", is_active_flag=False)
            u.set_password(pw)
            db.session.add(u)
            db.session.commit()
            flash(
                "Konto angelegt. Ein Administrator muss dich freischalten, bevor du dich anmelden kannst.",
                "info",
            )
            return redirect(url_for("login"))

    return render_template("registrieren.html")


# ════════════════════════════════════════════════════════════
# Dashboard
# ════════════════════════════════════════════════════════════
@app.route("/dashboard")
@login_required
def dashboard():
    standorte = visible_standorte()
    standort_ids = [s.id for s in standorte]

    # Stats pro Standort
    seit = datetime.utcnow() - timedelta(days=30)
    standort_stats = []
    for s in standorte:
        automat_ids = [a.id for a in s.automaten]
        q = Feedback.query.filter(Feedback.automat_id.in_(automat_ids))
        anzahl = q.count()
        anzahl_30 = q.filter(Feedback.created_at >= seit).count()
        durchschnitt = db.session.query(func.avg(Feedback.bewertung)).filter(
            Feedback.automat_id.in_(automat_ids)
        ).scalar()
        # Anzahl Feedbacks mit ausgefülltem Text in den letzten 30 Tagen
        mit_text_30 = q.filter(
            Feedback.created_at >= seit,
            db.or_(
                Feedback.was_gut.isnot(None),
                Feedback.was_schlecht.isnot(None),
                Feedback.verbesserung.isnot(None),
            ),
        ).count()
        standort_stats.append(
            {
                "standort": s,
                "anzahl_gesamt": anzahl,
                "anzahl_30": anzahl_30,
                "durchschnitt": round(durchschnitt, 2) if durchschnitt else None,
                "mit_text_30": mit_text_30,
                "anzahl_automaten": len(automat_ids),
            }
        )

    # Gesamtwerte
    if current_user.is_admin:
        gesamt_feedback = Feedback.query.count()
        gesamt_feedback_30 = Feedback.query.filter(Feedback.created_at >= seit).count()
        gesamt_avg = db.session.query(func.avg(Feedback.bewertung)).scalar()
    else:
        ids = [a.id for s in standorte for a in s.automaten]
        gesamt_feedback = Feedback.query.filter(Feedback.automat_id.in_(ids)).count()
        gesamt_feedback_30 = (
            Feedback.query.filter(Feedback.automat_id.in_(ids))
            .filter(Feedback.created_at >= seit)
            .count()
        )
        gesamt_avg = (
            db.session.query(func.avg(Feedback.bewertung))
            .filter(Feedback.automat_id.in_(ids))
            .scalar()
        )

    # Letzte Feedbacks
    letzte_q = Feedback.query
    if not current_user.is_admin:
        ids = [a.id for s in standorte for a in s.automaten]
        letzte_q = letzte_q.filter(Feedback.automat_id.in_(ids))
    letzte_feedbacks = letzte_q.order_by(Feedback.created_at.desc()).limit(15).all()

    return render_template(
        "dashboard.html",
        standort_stats=standort_stats,
        gesamt={
            "feedback": gesamt_feedback,
            "feedback_30": gesamt_feedback_30,
            "avg": round(gesamt_avg, 2) if gesamt_avg else None,
        },
        letzte_feedbacks=letzte_feedbacks,
    )


# ════════════════════════════════════════════════════════════
# Standorte
# ════════════════════════════════════════════════════════════
@app.route("/standorte")
@login_required
def standorte_liste():
    standorte = visible_standorte()
    return render_template("standorte.html", standorte=standorte)


@app.route("/standorte/neu", methods=["POST"])
@admin_required
def standort_neu():
    name = (request.form.get("name") or "").strip()
    adresse = (request.form.get("adresse") or "").strip() or None
    region = (request.form.get("region") or "").strip() or None
    if not name:
        flash("Name ist Pflicht.", "danger")
        return redirect(url_for("standorte_liste"))
    if Standort.query.filter_by(name=name).first():
        flash("Ein Standort mit diesem Namen existiert bereits.", "danger")
        return redirect(url_for("standorte_liste"))
    db.session.add(Standort(name=name, adresse=adresse, region=region))
    db.session.commit()
    flash(f'Standort "{name}" angelegt.', "success")
    return redirect(url_for("standorte_liste"))


@app.route("/standorte/<int:sid>/loeschen", methods=["POST"])
@admin_required
def standort_loeschen(sid: int):
    s = db.session.get(Standort, sid) or abort(404)
    name = s.name
    db.session.delete(s)
    db.session.commit()
    flash(f'Standort "{name}" gelöscht.', "info")
    return redirect(url_for("standorte_liste"))


# ════════════════════════════════════════════════════════════
# Automaten
# ════════════════════════════════════════════════════════════
@app.route("/standorte/<int:sid>")
@login_required
def standort_detail(sid: int):
    s = db.session.get(Standort, sid) or abort(404)
    if not standort_zugriff(s.id):
        abort(403)
    seit = datetime.utcnow() - timedelta(days=30)

    automaten_data = []
    for a in s.automaten:
        avg = db.session.query(func.avg(Feedback.bewertung)).filter(
            Feedback.automat_id == a.id
        ).scalar()
        anzahl = Feedback.query.filter_by(automat_id=a.id).count()
        anzahl_30 = Feedback.query.filter_by(automat_id=a.id).filter(
            Feedback.created_at >= seit
        ).count()
        automaten_data.append(
            {
                "automat": a,
                "avg": round(avg, 2) if avg else None,
                "anzahl": anzahl,
                "anzahl_30": anzahl_30,
            }
        )

    return render_template("standort_detail.html", standort=s, automaten_data=automaten_data)


@app.route("/standorte/<int:sid>/automat/neu", methods=["POST"])
@staff_required
def automat_neu(sid: int):
    s = db.session.get(Standort, sid) or abort(404)
    if not standort_zugriff(s.id):
        abort(403)
    bezeichnung = (request.form.get("bezeichnung") or "").strip()
    if not bezeichnung:
        flash("Bezeichnung ist Pflicht.", "danger")
        return redirect(url_for("standort_detail", sid=sid))
    a = Automat(
        standort_id=sid,
        bezeichnung=bezeichnung,
        modell=(request.form.get("modell") or "").strip() or None,
        lieferant=(request.form.get("lieferant") or "").strip() or None,
    )
    db.session.add(a)
    db.session.commit()
    flash(f'Automat "{bezeichnung}" angelegt.', "success")
    return redirect(url_for("standort_detail", sid=sid))


@app.route("/automat/<int:aid>/loeschen", methods=["POST"])
@admin_required
def automat_loeschen(aid: int):
    a = db.session.get(Automat, aid) or abort(404)
    sid = a.standort_id
    db.session.delete(a)
    db.session.commit()
    flash("Automat gelöscht.", "info")
    return redirect(url_for("standort_detail", sid=sid))


@app.route("/automat/<int:aid>/feedbacks")
@login_required
def automat_feedbacks(aid: int):
    a = db.session.get(Automat, aid) or abort(404)
    if not standort_zugriff(a.standort_id):
        abort(403)
    feedbacks = (
        Feedback.query.filter_by(automat_id=aid).order_by(Feedback.created_at.desc()).all()
    )
    return render_template("automat_feedbacks.html", automat=a, feedbacks=feedbacks)


# ── QR-Code-Generator ──────────────────────────────────────
def _qr_url(token: str) -> str:
    base = os.environ.get("BASE_URL") or request.host_url.rstrip("/")
    return f"{base}/f/{token}"


@app.route("/automat/<int:aid>/qr.png")
@login_required
def automat_qr_png(aid: int):
    a = db.session.get(Automat, aid) or abort(404)
    if not standort_zugriff(a.standort_id):
        abort(403)
    url = _qr_url(a.qr_token)
    img = qrcode.make(url, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    fname = f"qr_{a.standort.name}_{a.bezeichnung}.png".replace(" ", "_").replace("/", "-")
    return send_file(buf, mimetype="image/png", as_attachment=False, download_name=fname)


@app.route("/automat/<int:aid>/qr-drucken")
@login_required
def automat_qr_print(aid: int):
    a = db.session.get(Automat, aid) or abort(404)
    if not standort_zugriff(a.standort_id):
        abort(403)
    url = _qr_url(a.qr_token)
    return render_template("qr_print.html", automat=a, url=url)


# ════════════════════════════════════════════════════════════
# Benutzerverwaltung (nur Admin)
# ════════════════════════════════════════════════════════════
@app.route("/benutzer")
@admin_required
def benutzer_liste():
    users = User.query.order_by(User.created_at.desc()).all()
    standorte = Standort.query.order_by(Standort.name).all()
    return render_template("benutzer.html", users=users, standorte=standorte)


@app.route("/benutzer/<int:uid>/update", methods=["POST"])
@admin_required
def benutzer_update(uid: int):
    u = db.session.get(User, uid) or abort(404)
    rolle = request.form.get("rolle", u.rolle)
    if rolle in {"admin", "leiter", "viewer"}:
        u.rolle = rolle
    sid_raw = request.form.get("standort_id", "")
    u.standort_id = int(sid_raw) if sid_raw.isdigit() else None
    u.is_active_flag = bool(request.form.get("aktiv"))
    db.session.commit()
    flash(f'Benutzer "{u.email}" aktualisiert.', "success")
    return redirect(url_for("benutzer_liste"))


@app.route("/benutzer/<int:uid>/reset-passwort", methods=["POST"])
@admin_required
def benutzer_reset_pw(uid: int):
    u = db.session.get(User, uid) or abort(404)
    neues = (request.form.get("neues_passwort") or "").strip()
    if len(neues) < 10:
        flash("Passwort zu kurz (min. 10 Zeichen).", "danger")
    else:
        u.set_password(neues)
        db.session.commit()
        flash(f"Passwort für {u.email} zurückgesetzt.", "success")
    return redirect(url_for("benutzer_liste"))


@app.route("/benutzer/<int:uid>/loeschen", methods=["POST"])
@admin_required
def benutzer_loeschen(uid: int):
    u = db.session.get(User, uid) or abort(404)
    if u.id == current_user.id:
        flash("Du kannst dich nicht selbst löschen.", "danger")
        return redirect(url_for("benutzer_liste"))
    db.session.delete(u)
    db.session.commit()
    flash(f"Benutzer {u.email} gelöscht.", "info")
    return redirect(url_for("benutzer_liste"))


# ════════════════════════════════════════════════════════════

# Fehler-Handler
# ════════════════════════════════════════════════════════════
@app.errorhandler(403)
def err_403(e):
    return render_template("error.html", code=403, msg="Kein Zugriff."), 403


@app.errorhandler(404)
def err_404(e):
    return render_template("error.html", code=404, msg="Nicht gefunden."), 404


# ── Entrypoint ──────────────────────────────────────────────
if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
