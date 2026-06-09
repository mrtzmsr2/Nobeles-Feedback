# ☕ Nobeles Feedback

**Mitarbeiter-Feedback-System für Kaffeeautomaten an den Standorten der BCW-Gruppe.**

Eine schlanke Flask-Webanwendung im BCW/FOM-Design, mit der die Zentrale aus
Feedback aller Standorte einsammeln, auswerten und Defekte als Tickets nachverfolgen kann.

## ✨ Features

- 📱 **QR-Code-Feedback ohne Login** — Mitarbeiter scannen den QR-Sticker am Automaten und geben in unter 10 Sekunden Feedback (Emoji-Bewertung 1–5, Kategorien, optionaler Kommentar)
- 🏢 **Standort- und Automaten-Verwaltung** — Zentrale legt Standorte und Automaten an, generiert druckbare A6-QR-Sticker
- 📊 **Dashboard mit Ø-Bewertungen und 30-Tage-Trend** je Standort/Automat
- 🛠️ **Defekt-Tickets** mit Foto-Upload, Status, Priorität und Bearbeiter-Notizen — werden bei Kategorie "Defekt" im Feedback automatisch angelegt
- 👥 **Rollen-System**: Admin (alles), Standortleitung (eigener Standort), Viewer (nur lesen)
- 🔒 **Auth**: E-Mail + Passwort, **Registrierung nur mit `@bcw-gruppe.de`-Adressen**, Admin muss neue Konten freischalten
- 🎨 **Design**: identisches FOM/BCW-CSS-System wie Fuhrpark/Immomanagement (Primary `#00bfb3`)

## 🚀 Lokale Entwicklung

### 1. Voraussetzungen
- Python 3.10+
- Git

### 2. Setup

```powershell
# Repo klonen
git clone https://github.com/mrtzmsr2/Nobeles-Feedback.git
cd Nobeles-Feedback

# Venv + Dependencies
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Konfiguration
Copy-Item .env.example .env
# .env öffnen und SECRET_KEY + INITIAL_ADMIN_EMAIL/PASSWORD anpassen
```

`SECRET_KEY` erzeugen:
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Starten

```powershell
python app.py
```

➜ http://localhost:5000 öffnen, mit dem `INITIAL_ADMIN_EMAIL` + `INITIAL_ADMIN_PASSWORD` aus deiner `.env` anmelden.

## 📦 Deployment (pm2 auf Strato/Linux, analog Fuhrpark)

```bash
# Auf dem Server
git clone https://github.com/mrtzmsr2/Nobeles-Feedback.git
cd Nobeles-Feedback
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # SECRET_KEY, INITIAL_ADMIN_*, BASE_URL=https://feedback.bcw-gruppe.de

# Mit pm2 starten (Production: gunicorn)
pm2 start "venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 app:app" --name nobeles-feedback
pm2 save

# Nginx davorschalten, TLS via Let's Encrypt
```

### Update auf dem Server
```bash
cd Nobeles-Feedback
git pull origin master
source venv/bin/activate
pip install -r requirements.txt
pm2 restart nobeles-feedback
```

## 🗂️ Projektstruktur

```
Nobeles-Feedback/
├── app.py              # Flask-Anwendung (Routes)
├── models.py           # SQLAlchemy-Modelle (User, Standort, Automat, Feedback, Ticket)
├── requirements.txt
├── .env.example
├── .gitignore
├── instance/
│   └── nobeles_feedback.db   # SQLite (wird automatisch erzeugt)
├── static/
│   └── uploads/        # Ticket-Foto-Uploads
└── templates/
    ├── base.html
    ├── login.html
    ├── registrieren.html
    ├── dashboard.html
    ├── feedback.html              # öffentlich, QR-Landing
    ├── feedback_thanks.html
    ├── standorte.html
    ├── standort_detail.html
    ├── automat_feedbacks.html
    ├── tickets.html
    ├── ticket_detail.html
    ├── benutzer.html
    ├── qr_print.html              # druckbares QR-Sticker-Layout (A6)
    └── error.html
```

## 🎨 Branding

Das Design verwendet das BCW/FOM-Design-System wie auch `mrtzmsr2/Fuhrpark`
und `fom-immobilienmanagement`. Primärfarbe `#00bfb3` (Teal).

## 🔐 Sicherheit & Datenschutz

- Feedback wird **anonym** gespeichert (keine IP, kein User-Agent persistiert)
- Passwörter mit `werkzeug.security` (PBKDF2-SHA256) gehasht
- Registrierung domain-restricted (`ALLOWED_EMAIL_DOMAINS` in `.env`)
- Neue Konten standardmäßig deaktiviert — Admin schaltet manuell frei
- Datei-Uploads auf 8 MB begrenzt, nur PNG/JPG/WEBP/GIF erlaubt
- CSRF: Form-POSTs sind durch Session-Cookies geschützt; für Produktion ggf. `Flask-WTF` ergänzen

## 🛣️ Roadmap (Phase 2)

- [ ] E-Mail-Benachrichtigung an Standortleitung bei mehreren negativen Bewertungen in Folge
- [ ] Wartungs-Log und Service-Intervalle pro Automat
- [ ] CSV-Export der Feedbacks
- [ ] LDAP-Integration gegen `bcw-intern.local` (analog Fuhrpark) — Selbst-Registrierung ablösen
- [ ] Teams-Tab-Wrapper (iframe-Manifest für Microsoft Teams)
- [ ] Mehrsprachig (DE/EN)
