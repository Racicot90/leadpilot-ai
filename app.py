import os
import re
import json
import sqlite3
import hashlib
import hmac
import threading
import time
import html
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode, quote
from urllib.request import Request, urlopen
from http.cookies import SimpleCookie

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "5000"))

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "LeadPilot Demo Services")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-this-secret")
NOTIFY_PHONE = os.environ.get("NOTIFY_PHONE", "").strip()
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "").strip()
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
BUSINESS_ID = 1
print(
    "Twilio config:",
    {
        "notify_phone": bool(NOTIFY_PHONE),
        "from_number": bool(TWILIO_PHONE_NUMBER),
        "account_sid": bool(TWILIO_ACCOUNT_SID),
        "auth_token": bool(TWILIO_AUTH_TOKEN),
    },
    flush=True
)

USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row

def db():
    if USE_POSTGRES:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

    con = sqlite3.connect("leadpilot.db")
    con.row_factory = sqlite3.Row
    return con

def execute(con, sql, params=()):
    if USE_POSTGRES:
        sql = sql.replace("?", "%s")
    return con.execute(sql, params)

def init_db():
    con = db()

    if USE_POSTGRES:
        execute(con, """
            CREATE TABLE IF NOT EXISTS businesses(
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                services TEXT DEFAULT '',
                service_area TEXT DEFAULT '',
                email TEXT DEFAULT '',
                alert_phone TEXT DEFAULT '',
                routing_enabled INTEGER DEFAULT 1,
                routing_priority INTEGER DEFAULT 0,
                daily_lead_cap INTEGER DEFAULT 0,
                last_routed_at TEXT DEFAULT '',
                reserved_until TEXT DEFAULT '',
                verification_status TEXT DEFAULT 'Pending',
                test_business INTEGER DEFAULT 0,
                legal_business_name TEXT DEFAULT '',
                dba_name TEXT DEFAULT '',
                owner_contact_name TEXT DEFAULT '',
                business_phone TEXT DEFAULT '',
                business_address TEXT DEFAULT '',
                license_number TEXT DEFAULT '',
                license_type TEXT DEFAULT '',
                insurance_provider TEXT DEFAULT '',
                insurance_expiration TEXT DEFAULT '',
                business_registration TEXT DEFAULT '',
                identity_verified INTEGER DEFAULT 0,
                license_verified INTEGER DEFAULT 0,
                license_active_verified INTEGER DEFAULT 0,
                insurance_verified INTEGER DEFAULT 0,
                registration_verified INTEGER DEFAULT 0,
                terms_accepted INTEGER DEFAULT 0
            )
        """)
        execute(con, """
            CREATE TABLE IF NOT EXISTS leads(
                id BIGSERIAL PRIMARY KEY,
                business_id INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                name TEXT,
                phone TEXT,
                email TEXT,
                zip TEXT,
                service TEXT,
                urgency TEXT,
                message TEXT,
                status TEXT DEFAULT 'New',
                lead_score INTEGER DEFAULT 0,
                qualification TEXT DEFAULT 'Standard',
                recommended_action TEXT
            )
        """)
        execute(con, """
            CREATE TABLE IF NOT EXISTS coverage_waitlist(
                id BIGSERIAL PRIMARY KEY,
                created_at TEXT NOT NULL,
                service TEXT NOT NULL,
                location TEXT,
                city TEXT DEFAULT '',
                county TEXT DEFAULT '',
                zip TEXT,
                name TEXT,
                phone TEXT,
                email TEXT,
                issue TEXT,
                status TEXT DEFAULT 'Waiting'
            )
        """)
        execute(con, """
            CREATE TABLE IF NOT EXISTS provider_prospects(
                id BIGSERIAL PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                business_name TEXT NOT NULL,
                service TEXT NOT NULL,
                city TEXT DEFAULT '',
                county TEXT DEFAULT '',
                zip TEXT DEFAULT '',
                contact_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                email TEXT DEFAULT '',
                website TEXT DEFAULT '',
                status TEXT DEFAULT 'Prospect',
                notes TEXT DEFAULT ''
            )
        """)
        execute(con, """
            INSERT INTO businesses(id, name)
            VALUES(1, ?)
            ON CONFLICT (id) DO NOTHING
        """, (BUSINESS_NAME,))
    else:
        execute(con, """
            CREATE TABLE IF NOT EXISTS businesses(
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                services TEXT DEFAULT '',
                service_area TEXT DEFAULT '',
                email TEXT DEFAULT '',
                alert_phone TEXT DEFAULT '',
                routing_enabled INTEGER DEFAULT 1,
                routing_priority INTEGER DEFAULT 0,
                daily_lead_cap INTEGER DEFAULT 0,
                last_routed_at TEXT DEFAULT '',
                reserved_until TEXT DEFAULT '',
                verification_status TEXT DEFAULT 'Pending',
                test_business INTEGER DEFAULT 0,
                legal_business_name TEXT DEFAULT '',
                dba_name TEXT DEFAULT '',
                owner_contact_name TEXT DEFAULT '',
                business_phone TEXT DEFAULT '',
                business_address TEXT DEFAULT '',
                license_number TEXT DEFAULT '',
                license_type TEXT DEFAULT '',
                insurance_provider TEXT DEFAULT '',
                insurance_expiration TEXT DEFAULT '',
                business_registration TEXT DEFAULT '',
                identity_verified INTEGER DEFAULT 0,
                license_verified INTEGER DEFAULT 0,
                license_active_verified INTEGER DEFAULT 0,
                insurance_verified INTEGER DEFAULT 0,
                registration_verified INTEGER DEFAULT 0,
                terms_accepted INTEGER DEFAULT 0
            )
        """)
        execute(con, """
            CREATE TABLE IF NOT EXISTS leads(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                name TEXT,
                phone TEXT,
                email TEXT,
                zip TEXT,
                service TEXT,
                urgency TEXT,
                message TEXT,
                status TEXT DEFAULT 'New',
                lead_score INTEGER DEFAULT 0,
                qualification TEXT DEFAULT 'Standard',
                recommended_action TEXT
            )
        """)
        execute(con, """
            CREATE TABLE IF NOT EXISTS coverage_waitlist(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                service TEXT NOT NULL,
                location TEXT,
                city TEXT DEFAULT '',
                county TEXT DEFAULT '',
                zip TEXT,
                name TEXT,
                phone TEXT,
                email TEXT,
                issue TEXT,
                status TEXT DEFAULT 'Waiting'
            )
        """)
        execute(con, """
            CREATE TABLE IF NOT EXISTS provider_prospects(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                business_name TEXT NOT NULL,
                service TEXT NOT NULL,
                city TEXT DEFAULT '',
                county TEXT DEFAULT '',
                zip TEXT DEFAULT '',
                contact_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                email TEXT DEFAULT '',
                website TEXT DEFAULT '',
                status TEXT DEFAULT 'Prospect',
                notes TEXT DEFAULT ''
            )
        """)
        execute(con, "INSERT OR IGNORE INTO businesses(id,name) VALUES(1,?)", (BUSINESS_NAME,))

    # Safe schema upgrades for existing databases.
    if USE_POSTGRES:
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS services TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS service_area TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS email TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS alert_phone TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS routing_enabled INTEGER DEFAULT 1")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS routing_priority INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS daily_lead_cap INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS last_routed_at TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS reserved_until TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'Pending'")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS test_business INTEGER DEFAULT 1")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS legal_business_name TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS dba_name TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS owner_contact_name TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS business_phone TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS business_address TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS license_number TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS license_type TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS insurance_provider TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS insurance_expiration TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS business_registration TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS identity_verified INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS license_verified INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS license_active_verified INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS insurance_verified INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS registration_verified INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS terms_accepted INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_score INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS qualification TEXT DEFAULT 'Standard'")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS recommended_action TEXT")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS chase_10_sent INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS chase_30_sent INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE coverage_waitlist ADD COLUMN IF NOT EXISTS city TEXT DEFAULT ''")
        execute(con, "ALTER TABLE coverage_waitlist ADD COLUMN IF NOT EXISTS county TEXT DEFAULT ''")
    else:
        for sql in [
            "ALTER TABLE businesses ADD COLUMN services TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN service_area TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN email TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN alert_phone TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN routing_enabled INTEGER DEFAULT 1",
            "ALTER TABLE businesses ADD COLUMN routing_priority INTEGER DEFAULT 0",
            "ALTER TABLE businesses ADD COLUMN daily_lead_cap INTEGER DEFAULT 0",
            "ALTER TABLE businesses ADD COLUMN last_routed_at TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN reserved_until TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN verification_status TEXT DEFAULT 'Pending'",
            "ALTER TABLE businesses ADD COLUMN test_business INTEGER DEFAULT 1",
            "ALTER TABLE businesses ADD COLUMN legal_business_name TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN dba_name TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN owner_contact_name TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN business_phone TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN business_address TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN license_number TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN license_type TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN insurance_provider TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN insurance_expiration TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN business_registration TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN identity_verified INTEGER DEFAULT 0",
            "ALTER TABLE businesses ADD COLUMN license_verified INTEGER DEFAULT 0",
            "ALTER TABLE businesses ADD COLUMN license_active_verified INTEGER DEFAULT 0",
            "ALTER TABLE businesses ADD COLUMN insurance_verified INTEGER DEFAULT 0",
            "ALTER TABLE businesses ADD COLUMN registration_verified INTEGER DEFAULT 0",
            "ALTER TABLE businesses ADD COLUMN terms_accepted INTEGER DEFAULT 0",
            "ALTER TABLE leads ADD COLUMN lead_score INTEGER DEFAULT 0",
            "ALTER TABLE leads ADD COLUMN qualification TEXT DEFAULT 'Standard'",
            "ALTER TABLE leads ADD COLUMN recommended_action TEXT",
            "ALTER TABLE coverage_waitlist ADD COLUMN city TEXT DEFAULT ''",
            "ALTER TABLE coverage_waitlist ADD COLUMN county TEXT DEFAULT ''"
        ]:
            try:
                execute(con, sql)
            except Exception:
                pass

    con.commit()
    con.close()


def get_business_settings(business_id=BUSINESS_ID):
    con = db()
    row = execute(
        con,
        """SELECT id,name,services,service_area,email,alert_phone,
                  routing_enabled,routing_priority,daily_lead_cap,last_routed_at,reserved_until,
                  verification_status,test_business,legal_business_name,dba_name,
                  owner_contact_name,business_phone,business_address,license_number,
                  license_type,insurance_provider,insurance_expiration,business_registration,
                  identity_verified,license_verified,license_active_verified,
                  insurance_verified,registration_verified,terms_accepted
           FROM businesses WHERE id=?""",
        (business_id,)
    ).fetchone()
    con.close()

    if not row:
        return {
            "id": business_id, "name": BUSINESS_NAME, "services": "", "service_area": "",
            "email": "", "alert_phone": NOTIFY_PHONE, "routing_enabled": 1,
            "routing_priority": 0, "daily_lead_cap": 0, "last_routed_at": "",
            "reserved_until": "", "verification_status": "Pending", "test_business": 1,
            "legal_business_name": "", "dba_name": "", "owner_contact_name": "",
            "business_phone": "", "business_address": "", "license_number": "",
            "license_type": "", "insurance_provider": "", "insurance_expiration": "",
            "business_registration": "", "identity_verified": 0, "license_verified": 0,
            "license_active_verified": 0, "insurance_verified": 0,
            "registration_verified": 0, "terms_accepted": 0
        }

    return {k: row[k] for k in row.keys()}


def save_business_settings(name, services, service_area, email, alert_phone,
                           routing_enabled=1, routing_priority=0, daily_lead_cap=0,
                           verification_status="Pending", test_business=0,
                           legal_business_name="", dba_name="", owner_contact_name="",
                           business_phone="", business_address="", license_number="",
                           license_type="", insurance_provider="", insurance_expiration="",
                           business_registration="", identity_verified=0, license_verified=0,
                           license_active_verified=0, insurance_verified=0,
                           registration_verified=0, terms_accepted=0,
                           business_id=BUSINESS_ID):
    con = db()
    execute(
        con,
        """UPDATE businesses SET name=?,services=?,service_area=?,email=?,alert_phone=?,
           routing_enabled=?,routing_priority=?,daily_lead_cap=?,
           verification_status=?,test_business=?,legal_business_name=?,dba_name=?,
           owner_contact_name=?,business_phone=?,business_address=?,license_number=?,
           license_type=?,insurance_provider=?,insurance_expiration=?,business_registration=?,
           identity_verified=?,license_verified=?,license_active_verified=?,
           insurance_verified=?,registration_verified=?,terms_accepted=?
           WHERE id=?""",
        (
            (name or BUSINESS_NAME).strip(), (services or "").strip(),
            (service_area or "").strip(), (email or "").strip(), (alert_phone or "").strip(),
            1 if str(routing_enabled) in ("1","true","on","yes") else 0,
            max(0,min(int(routing_priority or 0),2)), max(0,int(daily_lead_cap or 0)),
            verification_status if verification_status in ("Pending","Verified","Rejected","Expired") else "Pending",
            1 if str(test_business) in ("1","true","on","yes") else 0,
            (legal_business_name or "").strip(), (dba_name or "").strip(),
            (owner_contact_name or "").strip(), (business_phone or "").strip(),
            (business_address or "").strip(), (license_number or "").strip(),
            (license_type or "").strip(), (insurance_provider or "").strip(),
            (insurance_expiration or "").strip(), (business_registration or "").strip(),
            1 if str(identity_verified) in ("1","true","on","yes") else 0,
            1 if str(license_verified) in ("1","true","on","yes") else 0,
            1 if str(license_active_verified) in ("1","true","on","yes") else 0,
            1 if str(insurance_verified) in ("1","true","on","yes") else 0,
            1 if str(registration_verified) in ("1","true","on","yes") else 0,
            1 if str(terms_accepted) in ("1","true","on","yes") else 0,
            business_id
        )
    )
    con.commit()
    con.close()


def effective_verification_status(business):
    status = (business.get("verification_status") or "Pending").strip()
    if status == "Verified":
        expiry = (business.get("insurance_expiration") or "").strip()
        if expiry:
            try:
                if datetime.strptime(expiry, "%Y-%m-%d").date() < datetime.utcnow().date():
                    return "Expired"
            except ValueError:
                pass
    return status


def business_is_marketplace_eligible(business):
    if int(business.get("test_business") or 0) == 1:
        return True
    return effective_verification_status(business) == "Verified"


def business_can_receive_leads(business):
    """Universal lead gate for marketplace, dedicated pages, chat, and direct API."""
    if not business:
        return False
    if int(business.get("routing_enabled") or 0) != 1:
        return False
    if int(business.get("test_business") or 0) == 1:
        return True
    return effective_verification_status(business) == "Verified"


def settings_html(saved=False, business_id=BUSINESS_ID):
    s = get_business_settings(business_id)
    esc = html.escape
    saved_msg = '<div class="success">✓ Settings saved</div>' if saved else ''

    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot Business Settings</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}
.wrap{{max-width:680px;margin:auto;padding:18px}}
.card{{background:#fff;border-radius:20px;padding:22px;box-shadow:0 8px 28px rgba(0,0,0,.07)}}
h1{{margin:0 0 6px;font-size:28px}}
.sub{{color:#667085;margin-bottom:20px}}
label{{display:block;font-weight:800;margin:14px 0 6px}}
input,textarea,select{{width:100%;padding:13px;border:1px solid #d0d5dd;border-radius:10px;font-size:16px;font-family:inherit}}
textarea{{min-height:90px;resize:vertical}}
.hint{{font-size:12px;color:#667085;margin-top:5px}}
button{{width:100%;padding:14px;border:0;border-radius:10px;background:#172033;color:#fff;font-weight:800;font-size:16px;margin-top:20px}}
.links{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px}}
.links a{{color:#3448c5;text-decoration:none;font-weight:800}}
.success{{background:#dcfae6;color:#05603a;padding:11px;border-radius:10px;margin-bottom:14px;font-weight:700}}
</style>
</head>
<body>
<div class="wrap">
<div class="links"><a href="/dashboard?business={business_id}">← Dashboard</a><a href="/b/{business_id}">Customer page</a></div>
<div class="card">
<h1>Business Settings</h1>
<div class="sub">Customize LeadPilot for this business.</div>
{saved_msg}
<div style="background:#f7f9fc;border-radius:12px;padding:12px;margin-bottom:16px;font-size:13px;color:#475467">
LeadPilot now uses these settings when answering customers about the business, services, and service area.
</div>
<form method="POST" action="/settings?business={business_id}">
<label>Business name</label>
<input name="name" value="{esc(s['name'], quote=True)}" required>

<label>Services offered</label>
<textarea name="services" placeholder="HVAC, plumbing, electrical, roofing...">{esc(s['services'])}</textarea>
<div class="hint">Separate services with commas.</div>

<label>Service area</label>
<input name="service_area" value="{esc(s['service_area'], quote=True)}" placeholder="Orange County, Orlando, 32801, 32803..."><div class="hint">Enter Florida counties, cities, ZIP codes, or “Florida” for statewide coverage. Separate multiple areas with commas.</div>

<label>Business email</label>
<input name="email" type="email" value="{esc(s['email'], quote=True)}" placeholder="office@example.com">

<label>Hot-lead alert phone</label>
<input name="alert_phone" value="{esc(s['alert_phone'], quote=True)}" placeholder="+19045551234">
<div class="hint">During the Twilio trial, this must be a verified recipient.</div>

<label>Marketplace routing</label>
<select name="routing_enabled">
  <option value="1" {"selected" if s["routing_enabled"] else ""}>Accept marketplace leads</option>
  <option value="0" {"selected" if not s["routing_enabled"] else ""}>Pause marketplace leads</option>
</select>

<label>Routing priority</label>
<select name="routing_priority">
  <option value="0" {"selected" if s["routing_priority"] == 0 else ""}>Standard</option>
  <option value="1" {"selected" if s["routing_priority"] == 1 else ""}>Priority</option>
  <option value="2" {"selected" if s["routing_priority"] == 2 else ""}>Premium</option>
</select>
<div class="hint">Higher tiers are considered first. Businesses on the same tier rotate fairly.</div>

<label>Daily marketplace lead cap</label>
<input name="daily_lead_cap" type="number" min="0" value="{s['daily_lead_cap']}">
<div class="hint">0 means unlimited. Once the cap is reached, LeadPilot skips this business until the next UTC day.</div>


<div style="margin-top:24px;padding-top:18px;border-top:1px solid #e4e7ec">
<h2 style="margin:0 0 8px">LeadPilot Verification</h2>
<div class="hint">Real businesses must be Verified to receive marketplace leads. Test businesses can route during beta but never display a Verified badge.</div>
<label>Verification status</label>
<select name="verification_status">
<option value="Pending" {"selected" if s["verification_status"]=="Pending" else ""}>Pending</option>
<option value="Verified" {"selected" if s["verification_status"]=="Verified" else ""}>Verified</option>
<option value="Rejected" {"selected" if s["verification_status"]=="Rejected" else ""}>Rejected</option>
<option value="Expired" {"selected" if s["verification_status"]=="Expired" else ""}>Expired</option>
</select>
<label>Account type</label>
<select name="test_business">
<option value="0" {"selected" if not s["test_business"] else ""}>Real business</option>
<option value="1" {"selected" if s["test_business"] else ""}>Test business</option>
</select>
<label>Legal business name</label><input name="legal_business_name" value="{esc(s['legal_business_name'], quote=True)}">
<label>DBA / public name</label><input name="dba_name" value="{esc(s['dba_name'], quote=True)}">
<label>Owner / contact</label><input name="owner_contact_name" value="{esc(s['owner_contact_name'], quote=True)}">
<label>Business phone</label><input name="business_phone" value="{esc(s['business_phone'], quote=True)}">
<label>Business address</label><input name="business_address" value="{esc(s['business_address'], quote=True)}">
<label>License number</label><input name="license_number" value="{esc(s['license_number'], quote=True)}">
<label>License type</label><input name="license_type" value="{esc(s['license_type'], quote=True)}">
<label>Insurance provider</label><input name="insurance_provider" value="{esc(s['insurance_provider'], quote=True)}">
<label>Insurance expiration</label><input type="date" name="insurance_expiration" value="{esc(s['insurance_expiration'], quote=True)}">
<label>Business registration / Sunbiz reference</label><input name="business_registration" value="{esc(s['business_registration'], quote=True)}">
<div style="margin-top:16px;background:#f8fafc;padding:14px;border-radius:12px">
<strong>Admin verification checklist</strong>
<label><input style="width:auto" type="checkbox" name="identity_verified" value="1" {"checked" if s["identity_verified"] else ""}> Business identity verified</label>
<label><input style="width:auto" type="checkbox" name="license_verified" value="1" {"checked" if s["license_verified"] else ""}> Trade license verified</label>
<label><input style="width:auto" type="checkbox" name="license_active_verified" value="1" {"checked" if s["license_active_verified"] else ""}> License active</label>
<label><input style="width:auto" type="checkbox" name="insurance_verified" value="1" {"checked" if s["insurance_verified"] else ""}> Insurance verified</label>
<label><input style="width:auto" type="checkbox" name="registration_verified" value="1" {"checked" if s["registration_verified"] else ""}> Registration verified</label>
<label><input style="width:auto" type="checkbox" name="terms_accepted" value="1" {"checked" if s["terms_accepted"] else ""}> Provider terms accepted</label>
</div>
</div>
<button type="submit">Save business settings</button>
</form>
</div>
</div>
</body>
</html>"""

def list_businesses():
    con = db()
    rows = execute(
        con,
        "SELECT id,name,services,service_area,email,alert_phone,routing_enabled,routing_priority,daily_lead_cap,last_routed_at,reserved_until,verification_status,test_business,legal_business_name,dba_name,owner_contact_name,business_phone,business_address,license_number,license_type,insurance_provider,insurance_expiration,business_registration,identity_verified,license_verified,license_active_verified,insurance_verified,registration_verified,terms_accepted FROM businesses ORDER BY id"
    ).fetchall()

    enriched = []
    for r in rows:
        metrics = business_routing_metrics(con, int(r["id"]))
        enriched.append((r, metrics))

    con.close()
    return enriched


def create_business(name, services="", service_area="", email="", alert_phone=""):
    con = db()
    if USE_POSTGRES:
        new_id = execute(con, "SELECT COALESCE(MAX(id),0)+1 AS next_id FROM businesses").fetchone()["next_id"]
    else:
        new_id = execute(con, "SELECT COALESCE(MAX(id),0)+1 AS next_id FROM businesses").fetchone()["next_id"]

    execute(
        con,
        """INSERT INTO businesses(id,name,services,service_area,email,alert_phone,routing_enabled,routing_priority,daily_lead_cap,last_routed_at,reserved_until,verification_status,test_business)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            int(new_id),
            (name or f"Business {new_id}").strip(),
            (services or "").strip(),
            (service_area or "").strip(),
            (email or "").strip(),
            (alert_phone or "").strip(),
            1, 0, 0, "", "", "Pending", 0
        )
    )
    con.commit()
    con.close()
    return int(new_id)


def businesses_html(created_id=None):
    rows = list_businesses()
    items = ""
    for r, metrics in rows:
        bid = r["id"]
        items += f"""
        <div class="biz">
          <div><strong>{html.escape(r['name'] or 'Unnamed business')}</strong>
          <span>{html.escape(r['service_area'] or 'No service area yet')}</span>
          <span>{"Accepting leads" if business_can_receive_leads(dict(r)) else "Lead routing blocked"} · Priority {int(r["routing_priority"] or 0)} · Daily cap {"Unlimited" if int(r["daily_lead_cap"] or 0) == 0 else int(r["daily_lead_cap"])}</span>
          <span>Routing health {metrics["health"]}/100 · Leads today {metrics["today_count"]} · Open New {metrics["new_count"]}</span>
          <span>{"🧪 Test Business" if r["test_business"] else ("🛡️ LeadPilot Verified" if effective_verification_status(dict(r))=="Verified" else "Verification: "+effective_verification_status(dict(r)))}</span></div>
          <div class="bizlinks">
            <a href="/b/{bid}">Customer page</a>
            <a href="/dashboard?business={bid}">Dashboard</a>
            <a href="/settings?business={bid}">Settings</a>
          </div>
        </div>
        """

    created = ""
    if created_id:
        created = f'<div class="success">✓ Business created. Customer page: <a href="/b/{created_id}">/b/{created_id}</a></div>'

    return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot Businesses</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}
.wrap{{max-width:780px;margin:auto;padding:18px}} .card,.biz{{background:#fff;border-radius:16px;padding:18px;margin-bottom:12px;box-shadow:0 5px 18px rgba(0,0,0,.05)}}
h1{{margin:0 0 6px}} .muted{{color:#667085;margin-bottom:18px}}
label{{display:block;font-weight:800;margin:12px 0 5px}} input,textarea{{width:100%;padding:12px;border:1px solid #d0d5dd;border-radius:10px;font-size:16px}}
button{{margin-top:16px;width:100%;padding:13px;border:0;border-radius:10px;background:#172033;color:white;font-weight:800}}
.biz{{display:flex;justify-content:space-between;gap:14px;align-items:center}} .biz span{{display:block;color:#667085;font-size:13px;margin-top:4px}}
.bizlinks{{display:flex;gap:10px;flex-wrap:wrap}} a{{color:#3448c5;font-weight:700;text-decoration:none}} .success{{background:#dcfae6;color:#05603a;padding:12px;border-radius:10px;margin-bottom:12px}}
@media(max-width:650px){{.biz{{display:block}} .bizlinks{{margin-top:12px}}}}
</style></head><body><div class="wrap">
<div style="margin-bottom:12px"><a href="/coverage-demand">🔥 Coverage Demand</a> · <a href="/recruiting">Provider Recruiting</a></div><h1>LeadPilot Businesses</h1>
<div class="muted">Each business gets its own customer page, settings, dashboard, service area, and leads.</div>
{created}
<div class="card">
<h2 style="margin-top:0">Create business</h2>
<form method="POST" action="/businesses">
<label>Business name</label><input name="name" required>
<label>Services</label><textarea name="services" placeholder="HVAC, plumbing, roofing"></textarea>
<label>Service area</label><input name="service_area" placeholder="Orange County, Orlando, 32801, 32803..."><div style="font-size:12px;color:#667085;margin-top:5px">Enter Florida counties, cities, ZIP codes, or “Florida” for statewide coverage. Separate multiple areas with commas.</div>
<label>Email</label><input name="email" type="email">
<label>Hot-lead alert phone</label><input name="alert_phone" placeholder="+19045551234">
<button type="submit">Create business page</button>
</form>
</div>
<h2>Your businesses</h2>
{items or '<div class="card">No businesses yet.</div>'}
</div></body></html>"""


# --- Florida Location Engine V1 -------------------------------------------
# Beta geocoding uses OpenStreetMap Nominatim to translate a Florida city or
# ZIP into normalized city/county/ZIP aliases. Results are cached in memory.
LOCATION_CACHE = {}

def _location_cache_key(value):
    return " ".join((value or "").lower().strip().split())

def resolve_florida_location(value):
    """Resolve a Florida city or ZIP into normalized geographic aliases."""
    raw = (value or "").strip(" .?!,")
    key = _location_cache_key(raw)
    if not key:
        return None

    if key in LOCATION_CACHE:
        return LOCATION_CACHE[key]

    # Ask specifically for Florida/USA so a city name elsewhere is not routed
    # to a Florida contractor by accident.
    zip_match = re.search(r"\b\d{5}\b", raw)
    if zip_match:
        query = f"{zip_match.group(0)}, Florida, USA"
    else:
        query = f"{raw}, Florida, USA"

    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?format=jsonv2&addressdetails=1&limit=3&countrycodes=us&q={quote(query)}"
    )

    req = Request(
        url,
        headers={
            "User-Agent": "LeadPilotAI-beta/1.0",
            "Accept": "application/json"
        }
    )

    try:
        with urlopen(req, timeout=8) as resp:
            results = json.loads(resp.read().decode("utf-8"))

        chosen = None
        for item in results:
            address = item.get("address") or {}
            state = (address.get("state") or "").strip()
            state_code = (address.get("ISO3166-2-lvl4") or "").strip().upper()
            if state.lower() == "florida" or state_code == "US-FL":
                chosen = item
                break

        if not chosen:
            LOCATION_CACHE[key] = None
            return None

        address = chosen.get("address") or {}

        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("hamlet")
            or ""
        ).strip()

        county = (address.get("county") or "").strip()
        postcode = (address.get("postcode") or "").strip()
        state = (address.get("state") or "Florida").strip()

        aliases = set()
        for item in [raw, city, county, postcode, state]:
            normalized = normalize_place(item)
            if normalized:
                aliases.add(normalized)

        # County values sometimes include the word "County"; keep both forms.
        county_norm = normalize_place(county)
        if county_norm.endswith(" county"):
            aliases.add(county_norm[:-7].strip())

        resolved = {
            "input": raw,
            "city": city,
            "county": county,
            "postcode": postcode,
            "state": state,
            "aliases": sorted(aliases),
            "display": ", ".join(
                x for x in [city, county, "Florida"] if x
            )
        }
        LOCATION_CACHE[key] = resolved
        return resolved

    except Exception as e:
        print("Florida location lookup error:", repr(e), flush=True)
        # Preserve the existing text matcher as a graceful fallback.
        fallback = {
            "input": raw,
            "city": "",
            "county": "",
            "postcode": zip_match.group(0) if zip_match else "",
            "state": "Florida",
            "aliases": [normalize_place(raw)],
            "display": raw
        }
        LOCATION_CACHE[key] = fallback
        return fallback


def normalize_place(value):
    value = (value or "").lower().strip()
    replacements = {
        "st. ": "saint ",
        "st ": "saint ",
        "county of ": "",
    }
    for a, b in replacements.items():
        value = value.replace(a, b)
    return " ".join(value.strip(" .?!,").split())


def business_supports_service(business, service):
    offered = [
        s.strip().lower()
        for s in (business["services"] or "").split(",")
        if s.strip()
    ]
    service_l = (service or "").strip().lower()
    if not offered or not service_l or service_l == "general repair":
        return False
    return any(service_l in s or s in service_l for s in offered)


def business_serves_location(business, resolved_location):
    """Match configured business territory against resolved city/county/ZIP."""
    if not resolved_location:
        return False

    configured_parts = [
        normalize_place(p)
        for p in re.split(r"[,;\n]+", business["service_area"] or "")
        if p.strip()
    ]
    if not configured_parts:
        return False

    aliases = {
        normalize_place(a)
        for a in (resolved_location.get("aliases") or [])
        if normalize_place(a)
    }

    for configured in configured_parts:
        if configured in ("florida", "statewide", "all florida", "florida statewide"):
            return True

        for alias in aliases:
            if configured == alias:
                return True
            if configured and alias and (
                configured in alias or alias in configured
            ):
                return True

    return False


def _parse_utc_timestamp(value):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


def reserve_business_turn(business_id, minutes=15):
    """Reserve a marketplace routing turn when a business is selected."""
    now = datetime.utcnow()
    until = now + timedelta(minutes=minutes)

    con = db()
    execute(
        con,
        "UPDATE businesses SET last_routed_at=?, reserved_until=? WHERE id=?",
        (
            now.strftime("%Y-%m-%d %H:%M:%S"),
            until.strftime("%Y-%m-%d %H:%M:%S"),
            business_id
        )
    )
    con.commit()
    con.close()


def business_routing_metrics(con, business_id):
    """
    Calculate lightweight performance signals from the business's own lead history.

    We intentionally keep this beta-safe:
    - New businesses are not punished for having little/no history.
    - Booked/Closed leads count as successful outcomes.
    - A large untouched New backlog lowers the score.
    - Today's lead count lowers the score to preserve distribution fairness.
    """
    rows = execute(
        con,
        """SELECT status, created_at
           FROM leads
           WHERE business_id=?
           ORDER BY id DESC
           LIMIT 100""",
        (business_id,)
    ).fetchall()

    total = len(rows)
    new_count = 0
    contacted = 0
    successes = 0
    overdue_new = 0
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_count = 0

    for r in rows:
        status = (r["status"] or "New").strip()
        if (r["created_at"] or "").startswith(today):
            today_count += 1

        if status == "New":
            new_count += 1
            # A New lead older than 30 minutes counts as overdue for routing health.
            raw = (r["created_at"] or "").strip()
            created = _parse_utc_timestamp(raw)
            if created and (datetime.utcnow() - created).total_seconds() >= 1800:
                overdue_new += 1
        else:
            contacted += 1

        if status in ("Booked", "Closed"):
            successes += 1

    if total == 0:
        engagement_rate = 1.0
        success_rate = 0.5
    else:
        engagement_rate = contacted / total
        success_rate = successes / total

    # 0-100 operational health score. New businesses begin around 70.
    if total < 3:
        health = 70
    else:
        health = int(
            45
            + (engagement_rate * 30)
            + (success_rate * 25)
            - min(new_count * 2, 14)
            - min(overdue_new * 5, 20)
        )

    health = max(0, min(100, health))

    return {
        "total": total,
        "today_count": today_count,
        "new_count": new_count,
        "overdue_new": overdue_new,
        "engagement_rate": engagement_rate,
        "success_rate": success_rate,
        "health": health,
    }


def match_business_for_lead(service, location, reserve=True):
    """
    LeadPilot Intelligent Routing V4.

    Eligibility:
      1. Marketplace routing enabled.
      2. Requested service offered.
      3. Florida territory match.
      4. Daily lead cap not reached.

    Distribution:
      1. Active reservations are skipped when another eligible business is free.
      2. Priority tier matters.
      3. Healthy/responsive businesses receive a modest performance advantage.
      4. Heavy current backlog and today's lead count reduce ranking.
      5. Least-recently-routed breaks close ties.

    This keeps routing fair while rewarding businesses that actually work their leads.
    """
    resolved = resolve_florida_location(location)
    if not resolved:
        return None, None

    con = db()
    businesses = execute(
        con,
        """SELECT id,name,services,service_area,email,alert_phone,
                  routing_enabled,routing_priority,daily_lead_cap,
                  last_routed_at,reserved_until,verification_status,test_business,
                  legal_business_name,dba_name,owner_contact_name,business_phone,
                  business_address,license_number,license_type,insurance_provider,
                  insurance_expiration,business_registration,identity_verified,
                  license_verified,license_active_verified,insurance_verified,
                  registration_verified,terms_accepted
           FROM businesses
           ORDER BY id"""
    ).fetchall()

    now = datetime.utcnow()
    eligible = []

    for b in businesses:
        if int(b["routing_enabled"] if b["routing_enabled"] is not None else 1) != 1:
            continue
        if not business_can_receive_leads(dict(b)):
            continue
        if not business_supports_service(b, service):
            continue
        if not business_serves_location(b, resolved):
            continue

        metrics = business_routing_metrics(con, int(b["id"]))

        cap = int(b["daily_lead_cap"] or 0)
        if cap > 0 and metrics["today_count"] >= cap:
            continue

        priority = int(b["routing_priority"] or 0)
        last_routed = (b["last_routed_at"] or "").strip()
        reserved_until = _parse_utc_timestamp(b["reserved_until"])
        is_reserved = reserved_until is not None and reserved_until > now

        # Routing score: tier is important, but performance/fairness still matter.
        # Standard=0, Priority=1, Premium=2.
        routing_score = (
            priority * 100
            + metrics["health"] * 0.35
            - metrics["today_count"] * 12
            - metrics["new_count"] * 3
            - metrics["overdue_new"] * 7
        )

        # Give brand-new businesses a small exploration boost so they can earn history.
        if metrics["total"] < 3:
            routing_score += 8

        eligible.append({
            "business": b,
            "metrics": metrics,
            "priority": priority,
            "last_routed": last_routed,
            "is_reserved": is_reserved,
            "routing_score": routing_score,
        })

    con.close()

    if not eligible:
        return None, resolved

    # A reservation represents a business that just got the current routing turn.
    pool = [e for e in eligible if not e["is_reserved"]]
    if not pool:
        pool = eligible

    # Highest score wins. For near-equal scores, least recently routed wins.
    pool.sort(
        key=lambda e: (
            -round(e["routing_score"], 2),
            e["last_routed"],
            int(e["business"]["id"])
        )
    )
    selected = pool[0]["business"]

    if reserve:
        reserve_business_turn(int(selected["id"]), minutes=15)

    return selected, resolved


def routing_diagnostics(service, location):
    """Explain marketplace eligibility and routing health for beta troubleshooting."""
    resolved = resolve_florida_location(location)
    if not resolved:
        return ["Location could not be resolved."]

    con = db()
    businesses = execute(
        con,
        """SELECT id,name,services,service_area,routing_enabled,
                  routing_priority,daily_lead_cap,last_routed_at,reserved_until
           FROM businesses ORDER BY id"""
    ).fetchall()

    now = datetime.utcnow()
    lines = []

    for b in businesses:
        reasons = []
        eligible = True

        if int(b["routing_enabled"] if b["routing_enabled"] is not None else 1) != 1:
            eligible = False
            reasons.append("paused")

        if not business_can_receive_leads(dict(b)):
            eligible = False
            reasons.append("ineligible: verification/routing")

        if not business_supports_service(b, service):
            eligible = False
            reasons.append("service mismatch")

        if not business_serves_location(b, resolved):
            eligible = False
            reasons.append("location mismatch")

        metrics = business_routing_metrics(con, int(b["id"]))
        cap = int(b["daily_lead_cap"] or 0)
        if cap > 0 and metrics["today_count"] >= cap:
            eligible = False
            reasons.append("daily cap reached")

        reserved_until = _parse_utc_timestamp(b["reserved_until"])
        if reserved_until and reserved_until > now:
            reasons.append(f"reserved until {reserved_until.strftime('%H:%M:%S')} UTC")

        priority = int(b["routing_priority"] or 0)
        routing_score = (
            priority * 100
            + metrics["health"] * 0.35
            - metrics["today_count"] * 12
            - metrics["new_count"] * 3
            - metrics["overdue_new"] * 7
            + (8 if metrics["total"] < 3 else 0)
        )

        status = "eligible" if eligible else "not eligible"
        lines.append(
            f"{b['name']}: {status}; tier={priority}; health={metrics['health']}/100; "
            f"today={metrics['today_count']}; new={metrics['new_count']}; "
            f"overdue={metrics['overdue_new']}; routing_score={routing_score:.1f}; "
            + (", ".join(reasons) if reasons else "ready")
        )

    con.close()
    return lines


def save_coverage_waitlist(service, location, customer_zip, name, phone, email, issue):
    """Save unmet marketplace demand with normalized Florida geography."""
    resolved = resolve_florida_location(location or customer_zip) or {}
    city = (resolved.get("city") or "").strip()
    county = (resolved.get("county") or "").strip()
    postcode = (resolved.get("postcode") or customer_zip or "").strip()
    con = db()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    execute(
        con,
        """INSERT INTO coverage_waitlist
           (created_at,service,location,city,county,zip,name,phone,email,issue,status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            now,
            (service or "General Repair").strip(),
            (location or "").strip(), city, county, postcode,
            (name or "").strip(), (phone or "").strip(),
            (email or "").strip(), (issue or "").strip(), "Waiting"
        )
    )
    con.commit()
    con.close()


def coverage_demand_html():
    """Admin view of unmet demand, ranked to show where provider recruiting matters most."""
    con = db()
    rows = execute(con, """SELECT * FROM coverage_waitlist ORDER BY id DESC""").fetchall()
    con.close()

    groups = {}
    waiting_total = 0
    for r in rows:
        status = (r["status"] or "Waiting").strip()
        if status != "Waiting":
            continue
        waiting_total += 1
        service = (r["service"] or "General Repair").strip()
        city = (r["city"] or "").strip()
        county = (r["county"] or "").strip()
        location = (r["location"] or "").strip()
        area = county or city or location or "Unknown area"
        key = (area, service)
        g = groups.setdefault(key, {"area":area, "service":service, "count":0, "city":city, "county":county})
        g["count"] += 1

    ranked = sorted(groups.values(), key=lambda x: (-x["count"], x["area"].lower(), x["service"].lower()))
    top = ranked[0] if ranked else None

    demand_cards = ""
    for g in ranked:
        heat = "hot" if g["count"] >= 10 else ("warm" if g["count"] >= 5 else "normal")
        label = "🔥 Recruit now" if g["count"] >= 10 else ("Growing demand" if g["count"] >= 5 else "Demand detected")
        detail = g["county"] or g["city"] or g["area"]
        recruit_url = (
            "/recruiting?service=" + quote(g["service"]) +
            "&city=" + quote(g["city"] or g["area"]) +
            "&count=" + str(g["count"])
        )
        demand_cards += f"""<div class="demand-card {heat}">
        <div>
          <span class="eyebrow">{html.escape(label)}</span>
          <h3>{html.escape(g['service'])}</h3>
          <p>{html.escape(detail)}</p>
          <a class="recruit-btn" href="{recruit_url}">Find / Recruit Provider →</a>
        </div>
        <div class="demand-count">{g['count']}<small>waiting</small></div>
        </div>"""
    if not demand_cards:
        demand_cards = '<div class="empty">No unmet coverage demand yet. New waitlist requests will appear here automatically.</div>'

    request_rows = ""
    for r in rows[:100]:
        place = (r["county"] or r["city"] or r["location"] or "—").strip()
        contact = (r["phone"] or r["email"] or "—").strip()
        request_rows += f"""<div class="request"><div><strong>{html.escape(r['service'] or 'General Repair')}</strong><span>{html.escape(place)} · {html.escape(r['zip'] or '')}</span><span>{html.escape(r['created_at'] or '')} · {html.escape(r['status'] or 'Waiting')}</span></div><div class="contact">{html.escape(r['name'] or 'Unnamed')}<span>{html.escape(contact)}</span></div></div>"""

    opportunity = (f"Top recruiting opportunity: {top['service']} in {top['area']} — {top['count']} waiting customer(s)." if top else "LeadPilot will rank recruiting opportunities as waitlist demand comes in.")
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>LeadPilot Coverage Demand</title><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}.wrap{{max-width:900px;margin:auto;padding:18px}}a{{color:#3448c5;text-decoration:none;font-weight:800}}h1{{margin:8px 0 4px}}.sub{{color:#667085}}.nav{{display:flex;gap:16px;flex-wrap:wrap;margin:14px 0 20px}}.summary{{background:#172033;color:#fff;border-radius:18px;padding:20px;margin-bottom:16px}}.summary span{{opacity:.75;font-size:13px}}.summary strong{{display:block;font-size:36px;margin:4px 0}}.summary p{{margin:8px 0 0;line-height:1.4}}.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.demand-card{{background:#fff;border-radius:16px;padding:18px;display:flex;justify-content:space-between;gap:14px;align-items:center;box-shadow:0 5px 18px rgba(0,0,0,.05)}}.demand-card.hot{{border:2px solid #fda29b}}.demand-card.warm{{border:2px solid #fedf89}}.eyebrow{{font-size:11px;text-transform:uppercase;font-weight:900;color:#667085}}h3{{font-size:21px;margin:5px 0}}.demand-card p{{margin:0;color:#667085}}.demand-count{{font-size:32px;font-weight:900;text-align:center;min-width:78px}}.recruit-btn{{display:inline-block;margin-top:12px;background:#172033;color:#fff!important;padding:9px 12px;border-radius:9px;font-size:12px}}.demand-count small{{display:block;font-size:11px;color:#667085}}h2{{margin-top:28px}}.request{{background:#fff;border-radius:14px;padding:14px 16px;margin:9px 0;display:flex;justify-content:space-between;gap:14px;box-shadow:0 4px 14px rgba(0,0,0,.04)}}.request span{{display:block;color:#667085;font-size:12px;margin-top:4px}}.contact{{text-align:right;font-weight:700}}.empty{{background:#fff;border-radius:14px;padding:22px;color:#667085}}@media(max-width:650px){{.grid{{grid-template-columns:1fr}}.request{{display:block}}.contact{{text-align:left;margin-top:10px}}}}
</style></head><body><div class="wrap"><div class="nav"><a href="/dashboard">Dashboard</a><a href="/recruiting">Provider Recruiting</a><a href="/businesses">Businesses</a><a href="/">Customer page</a><a href="/logout">Log out</a></div><h1>Coverage Demand</h1><div class="sub">Live unmet customer demand tells LeadPilot where to recruit verified providers next.</div><div class="summary"><span>Customers currently waiting</span><strong>{waiting_total}</strong><p>{html.escape(opportunity)}</p></div><div class="grid">{demand_cards}</div><h2>Recent coverage requests</h2>{request_rows or '<div class="empty">No requests yet.</div>'}</div></body></html>"""



PROSPECT_STATUSES = ["Prospect", "Contacted", "Interested", "Verification", "Approved", "Live", "Passed"]


def create_provider_prospect(business_name, service, city="", county="", zip_code="",
                             contact_name="", phone="", email="", website="", notes=""):
    con = db()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    if USE_POSTGRES:
        cur = execute(
            con,
            """INSERT INTO provider_prospects
               (created_at,updated_at,business_name,service,city,county,zip,
                contact_name,phone,email,website,status,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               RETURNING id""",
            (
                now, now, (business_name or "Unnamed prospect").strip(),
                (service or "General Repair").strip(), (city or "").strip(),
                (county or "").strip(), (zip_code or "").strip(),
                (contact_name or "").strip(), (phone or "").strip(),
                (email or "").strip(), (website or "").strip(),
                "Prospect", (notes or "").strip()
            )
        )
        prospect_id = cur.fetchone()["id"]
    else:
        cur = execute(
            con,
            """INSERT INTO provider_prospects
               (created_at,updated_at,business_name,service,city,county,zip,
                contact_name,phone,email,website,status,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now, now, (business_name or "Unnamed prospect").strip(),
                (service or "General Repair").strip(), (city or "").strip(),
                (county or "").strip(), (zip_code or "").strip(),
                (contact_name or "").strip(), (phone or "").strip(),
                (email or "").strip(), (website or "").strip(),
                "Prospect", (notes or "").strip()
            )
        )
        prospect_id = cur.lastrowid
    con.commit()
    con.close()
    return prospect_id


def update_provider_prospect_status(prospect_id, status):
    if status not in PROSPECT_STATUSES:
        return False
    con = db()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    cur = execute(
        con,
        "UPDATE provider_prospects SET status=?, updated_at=? WHERE id=?",
        (status, now, prospect_id)
    )
    con.commit()
    changed = cur.rowcount
    con.close()
    return bool(changed)


def recruiting_pipeline_html(prefill_service="", prefill_city="", prefill_count=""):
    con = db()
    rows = execute(
        con,
        "SELECT * FROM provider_prospects ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    con.close()

    counts = {s: 0 for s in PROSPECT_STATUSES}
    for r in rows:
        status = (r["status"] or "Prospect").strip()
        counts[status] = counts.get(status, 0) + 1

    cards = ""
    for r in rows:
        status = (r["status"] or "Prospect").strip()
        status_options = "".join(
            f'<option value="{html.escape(s)}" {"selected" if s == status else ""}>{html.escape(s)}</option>'
            for s in PROSPECT_STATUSES
        )
        place = ", ".join(x for x in [
            (r["city"] or "").strip(),
            (r["county"] or "").strip()
        ] if x) or "Area not set"
        contact_parts = [x for x in [
            (r["contact_name"] or "").strip(),
            (r["phone"] or "").strip(),
            (r["email"] or "").strip()
        ] if x]
        contact = " · ".join(contact_parts) or "No contact details yet"
        cards += f"""
        <div class="prospect">
          <div class="prospect-top">
            <div>
              <span class="eyebrow">{html.escape(r['service'] or 'General Repair')}</span>
              <h3>{html.escape(r['business_name'] or 'Unnamed prospect')}</h3>
              <p>{html.escape(place)}{(' · ' + html.escape(r['zip'])) if r['zip'] else ''}</p>
            </div>
            <span class="stage stage-{status.lower().replace(' ','-')}">{html.escape(status)}</span>
          </div>
          <div class="contact">{html.escape(contact)}</div>
          {f'<div class="notes">{html.escape(r["notes"])}</div>' if r["notes"] else ''}
          <form method="POST" action="/recruiting/status">
            <input type="hidden" name="prospect_id" value="{r['id']}">
            <label>Pipeline stage</label>
            <div class="status-row">
              <select name="status">{status_options}</select>
              <button type="submit">Update</button>
            </div>
          </form>
        </div>
        """

    if not cards:
        cards = '<div class="empty">No provider prospects yet. Use Coverage Demand to decide who to recruit first.</div>'

    prefill_note = ""
    if prefill_count:
        prefill_note = f"{prefill_count} customer(s) currently waiting in this market."

    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot Provider Recruiting</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}
.wrap{{max-width:950px;margin:auto;padding:18px}}
a{{color:#3448c5;text-decoration:none;font-weight:800}}
.nav{{display:flex;gap:16px;flex-wrap:wrap;margin:14px 0 20px}}
h1{{margin:8px 0 4px}} .sub{{color:#667085;margin-bottom:18px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}}
.stat{{background:#fff;border-radius:14px;padding:14px;box-shadow:0 4px 14px rgba(0,0,0,.04)}}
.stat span{{font-size:11px;color:#667085}} .stat strong{{display:block;font-size:25px;margin-top:4px}}
.card,.prospect{{background:#fff;border-radius:16px;padding:18px;margin-bottom:12px;box-shadow:0 5px 18px rgba(0,0,0,.05)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
label{{display:block;font-size:12px;font-weight:800;margin:10px 0 5px;color:#475467}}
input,textarea,select{{width:100%;padding:11px;border:1px solid #d0d5dd;border-radius:10px;font-size:15px;background:#fff}}
button{{border:0;border-radius:10px;background:#172033;color:#fff;font-weight:800;padding:11px 15px}}
.create-btn{{width:100%;margin-top:14px;padding:13px}}
.prospect-top{{display:flex;justify-content:space-between;gap:12px}}
.eyebrow{{font-size:11px;text-transform:uppercase;color:#667085;font-weight:900}}
h3{{margin:5px 0;font-size:21px}} .prospect p{{margin:0;color:#667085;font-size:13px}}
.stage{{white-space:nowrap;height:max-content;padding:7px 10px;border-radius:999px;background:#eef2f6;font-size:11px;font-weight:900}}
.stage-live,.stage-approved{{background:#dcfae6;color:#05603a}}
.stage-interested,.stage-verification{{background:#fff0c2;color:#93370d}}
.stage-passed{{background:#f2f4f7;color:#667085}}
.contact{{margin-top:12px;font-weight:700;font-size:13px}}
.notes{{margin-top:10px;padding:10px;background:#f8fafc;border-radius:9px;color:#475467;font-size:13px}}
.status-row{{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center}}
.empty{{background:#fff;border-radius:14px;padding:22px;color:#667085}}
@media(max-width:700px){{
 .stats{{grid-template-columns:1fr 1fr}}
 .grid{{grid-template-columns:1fr}}
 .prospect-top{{display:block}}
 .stage{{display:inline-block;margin-top:8px}}
}}
</style>
</head>
<body>
<div class="wrap">
<div class="nav">
<a href="/dashboard">Dashboard</a>
<a href="/coverage-demand">Coverage Demand</a> <a href="/recruiting">Provider Recruiting</a>
<a href="/businesses">Businesses</a>
<a href="/">Customer page</a>
<a href="/logout">Log out</a>
</div>

<h1>Provider Recruiting</h1>
<div class="sub">Turn unmet customer demand into a provider recruiting pipeline.</div>

<div class="stats">
  <div class="stat"><span>Prospects</span><strong>{counts.get('Prospect',0)}</strong></div>
  <div class="stat"><span>Interested</span><strong>{counts.get('Interested',0)}</strong></div>
  <div class="stat"><span>Verification</span><strong>{counts.get('Verification',0)}</strong></div>
  <div class="stat"><span>Live providers</span><strong>{counts.get('Live',0)}</strong></div>
</div>

<div class="card">
<h2 style="margin-top:0">Add provider prospect</h2>
<form method="POST" action="/recruiting">
<div class="grid">
<div><label>Business name</label><input name="business_name" placeholder="Lake City Roofing Co." required></div>
<div><label>Service</label><input name="service" value="{html.escape(prefill_service, quote=True)}" placeholder="Roofing" required></div>
<div><label>City</label><input name="city" value="{html.escape(prefill_city, quote=True)}"></div>
<div><label>County</label><input name="county"></div>
<div><label>ZIP</label><input name="zip"></div>
<div><label>Contact name</label><input name="contact_name"></div>
<div><label>Phone</label><input name="phone"></div>
<div><label>Email</label><input name="email" type="email"></div>
</div>
<label>Website</label><input name="website">
<label>Recruiting notes</label>
<textarea name="notes" rows="3" placeholder="Why this market matters, outreach notes, etc.">{html.escape(prefill_note)}</textarea>
<button class="create-btn" type="submit">Add to recruiting pipeline</button>
</form>
</div>

<h2>Recruiting pipeline</h2>
{cards}
</div>
</body>
</html>"""


def marketplace_reply(message, context=None):
    """Business-neutral LeadPilot flow: problem -> location -> match -> contact info."""
    context = context or {}
    msg = (message or "").strip()
    msg_lower = msg.lower()

    step = (context.get("intake_step") or "").strip()
    service = (context.get("service") or "").strip()
    urgency = (context.get("urgency") or "").strip()
    issue = (context.get("issue") or "").strip()
    customer_name = (context.get("customer_name") or "").strip()
    customer_phone = (context.get("customer_phone") or "").strip()
    customer_email = (context.get("customer_email") or "").strip()
    customer_zip = (context.get("customer_zip") or "").strip()
    customer_location = (context.get("customer_location") or "").strip()
    waitlist_name = (context.get("waitlist_name") or "").strip()
    waitlist_phone = (context.get("waitlist_phone") or "").strip()
    waitlist_email = (context.get("waitlist_email") or "").strip()
    matched_business_id = int(context.get("matched_business_id") or 0)
    matched_business_name = (context.get("business_name") or "").strip()

    if matched_business_id:
        current_business = get_business_settings(matched_business_id)
        if not business_can_receive_leads(current_business):
            matched_business_id = 0
            matched_business_name = ""
            if customer_location and service and service != "General Repair":
                step = "location"

    # Coverage waitlist flow for areas with no current provider.
    if step == "coverage_waitlist_offer":
        # If the customer simply enters another valid Florida city/ZIP, treat it as
        # a new location search rather than forcing them into the waitlist.
        alternate = resolve_florida_location(msg)
        if alternate and msg_lower not in ("yes", "yeah", "yep", "sure", "ok", "okay"):
            matched, resolved = match_business_for_lead(service, msg)
            customer_location = msg
            customer_zip = (resolved or {}).get("postcode") or _extract_zip(msg)

            if matched:
                matched_business_id = int(matched["id"])
                matched_business_name = matched["name"] or "a local provider"
                place = (resolved or {}).get("display") or msg
                return {
                    "reply": f"I found {matched_business_name}, which covers {place} and offers {service}. What's your name?",
                    "service": service, "urgency": urgency, "issue": issue,
                    "intake_step": "name",
                    "matched_business_id": matched_business_id,
                    "business_name": matched_business_name,
                    "customer_zip": customer_zip,
                    "customer_location": customer_location
                }

            place = (resolved or {}).get("display") or msg
            return {
                "reply": (
                    f"I still don't have a verified {service.lower()} provider serving {place}. "
                    "I can notify you when coverage becomes available. If you'd like that, type YES."
                ),
                "service": service, "urgency": urgency, "issue": issue,
                "intake_step": "coverage_waitlist_offer",
                "matched_business_id": 0, "business_name": "",
                "customer_zip": customer_zip,
                "customer_location": customer_location
            }

        if msg_lower in ("no", "nope", "not now", "no thanks", "cancel"):
            return {
                "reply": "No problem. You can send another Florida city or ZIP code and I'll check that area.",
                "service": service, "urgency": urgency, "issue": issue,
                "intake_step": "location",
                "matched_business_id": 0, "business_name": "",
                "customer_zip": customer_zip,
                "customer_location": customer_location
            }

        if msg_lower in ("yes", "yeah", "yep", "sure", "ok", "okay", "please", "yes please"):
            return {
                "reply": "Absolutely. What's your name?",
                "service": service, "urgency": urgency, "issue": issue,
                "intake_step": "waitlist_name",
                "matched_business_id": 0, "business_name": "",
                "customer_zip": customer_zip,
                "customer_location": customer_location
            }

        # A natural name answer is also accepted.
        parsed_name = _extract_name(msg)
        if parsed_name:
            waitlist_name = parsed_name
            return {
                "reply": f"Thanks, {waitlist_name}. What's the best 10-digit phone number to notify you?",
                "service": service, "urgency": urgency, "issue": issue,
                "intake_step": "waitlist_phone",
                "waitlist_name": waitlist_name,
                "matched_business_id": 0, "business_name": "",
                "customer_zip": customer_zip,
                "customer_location": customer_location
            }

        return {
            "reply": "If you'd like LeadPilot to notify you when a provider becomes available, type YES. Otherwise, send another Florida city or ZIP code.",
            "service": service, "urgency": urgency, "issue": issue,
            "intake_step": "coverage_waitlist_offer",
            "matched_business_id": 0, "business_name": "",
            "customer_zip": customer_zip,
            "customer_location": customer_location
        }

    if step == "waitlist_name":
        parsed = _extract_name(msg)
        if not parsed:
            reply = "What name should I put on the coverage notification?"
        else:
            waitlist_name = parsed
            step = "waitlist_phone"
            reply = f"Thanks, {waitlist_name}. What's the best 10-digit phone number to notify you?"

        return {
            "reply": reply, "service": service, "urgency": urgency, "issue": issue,
            "intake_step": step, "waitlist_name": waitlist_name,
            "waitlist_phone": waitlist_phone, "waitlist_email": waitlist_email,
            "matched_business_id": 0, "business_name": "",
            "customer_zip": customer_zip, "customer_location": customer_location
        }

    if step == "waitlist_phone":
        parsed = _extract_phone(msg)
        if not parsed:
            reply = "Please send a 10-digit phone number, or type SKIP if you'd rather use email only."
        else:
            waitlist_phone = parsed
            step = "waitlist_email"
            reply = "Got it. What's your email address? You can type SKIP if you only want a phone notification."

        if msg_lower == "skip":
            waitlist_phone = ""
            step = "waitlist_email"
            reply = "No problem. What's your email address?"

        return {
            "reply": reply, "service": service, "urgency": urgency, "issue": issue,
            "intake_step": step, "waitlist_name": waitlist_name,
            "waitlist_phone": waitlist_phone, "waitlist_email": waitlist_email,
            "matched_business_id": 0, "business_name": "",
            "customer_zip": customer_zip, "customer_location": customer_location
        }

    if step == "waitlist_email":
        if msg_lower == "skip":
            waitlist_email = ""
        else:
            parsed = _extract_email(msg)
            if not parsed:
                return {
                    "reply": "That doesn't look like an email address. Try again, or type SKIP.",
                    "service": service, "urgency": urgency, "issue": issue,
                    "intake_step": "waitlist_email", "waitlist_name": waitlist_name,
                    "waitlist_phone": waitlist_phone, "waitlist_email": waitlist_email,
                    "matched_business_id": 0, "business_name": "",
                    "customer_zip": customer_zip, "customer_location": customer_location
                }
            waitlist_email = parsed

        if not waitlist_phone and not waitlist_email:
            return {
                "reply": "I need either a phone number or email so LeadPilot can notify you when coverage becomes available.",
                "service": service, "urgency": urgency, "issue": issue,
                "intake_step": "waitlist_phone", "waitlist_name": waitlist_name,
                "waitlist_phone": "", "waitlist_email": "",
                "matched_business_id": 0, "business_name": "",
                "customer_zip": customer_zip, "customer_location": customer_location
            }

        save_coverage_waitlist(
            service, customer_location, customer_zip,
            waitlist_name, waitlist_phone, waitlist_email, issue
        )

        return {
            "reply": (
                f"You're on the list, {waitlist_name}. LeadPilot will use the contact information "
                f"you provided to notify you when a verified {service.lower()} provider becomes "
                "available for your area."
            ),
            "service": service, "urgency": urgency, "issue": issue,
            "intake_step": "waitlist_complete", "waitlist_name": waitlist_name,
            "waitlist_phone": waitlist_phone, "waitlist_email": waitlist_email,
            "matched_business_id": 0, "business_name": "",
            "customer_zip": customer_zip, "customer_location": customer_location,
            "waitlist_saved": True
        }

    if step == "waitlist_complete":
        return {
            "reply": "Your coverage notification request is saved. You can also start a new search for another service or location.",
            "service": service, "urgency": urgency, "issue": issue,
            "intake_step": "waitlist_complete",
            "matched_business_id": 0, "business_name": "",
            "customer_zip": customer_zip, "customer_location": customer_location
        }

    # Let the customer change service naturally at any point.
    switched_service, switched_urgency = classify(msg)
    service_words = {
        "HVAC": ["hvac", "ac", "a/c", "air conditioning", "heat", "furnace"],
        "Plumbing": ["plumber", "plumbing", "pipe", "toilet", "sink", "drain", "water leak"],
        "Electrical": ["electrician", "electrical", "electric", "outlet", "breaker", "wiring", "power"],
        "Roofing": ["roofer", "roofing", "roof", "shingle"]
    }

    explicit_service_change = False
    for candidate, words in service_words.items():
        if candidate != service and any(word in msg_lower for word in words):
            switched_service = candidate
            explicit_service_change = True
            break

    if explicit_service_change and service:
        service = switched_service
        urgency = switched_urgency if switched_urgency != "Normal" else urgency

        # If we already know the customer's location, re-run matching immediately.
        if customer_location:
            matched, resolved = match_business_for_lead(service, customer_location)

            if not matched:
                place = (resolved or {}).get("display") or customer_location
                return {
                    "reply": (
                        f"I checked for {service.lower()} in {place}, but LeadPilot doesn't currently "
                        "have a verified provider serving that area. I can notify you when coverage "
                        "becomes available. Would you like me to save a coverage notification?"
                    ),
                    "service": service,
                    "urgency": urgency,
                    "issue": issue or msg,
                    "intake_step": "coverage_waitlist_offer",
                    "matched_business_id": 0,
                    "business_name": "",
                    "customer_zip": (resolved or {}).get("postcode") or customer_zip,
                    "customer_location": customer_location
                }

            matched_business_id = int(matched["id"])
            matched_business_name = matched["name"] or "a local provider"
            place = (resolved or {}).get("display") or customer_location
            customer_zip = (resolved or {}).get("postcode") or customer_zip

            return {
                "reply": f"Yes — I found {matched_business_name}, which covers {place} and offers {service}. What's your name?",
                "service": service,
                "urgency": urgency,
                "issue": issue or msg,
                "intake_step": "name",
                "matched_business_id": matched_business_id,
                "business_name": matched_business_name,
                "customer_zip": customer_zip,
                "customer_location": customer_location
            }

        # If location is not known yet, ask for it for the new service.
        return {
            "reply": f"Sure — I'll switch this to {service}. What Florida city or ZIP code is the job in?",
            "service": service,
            "urgency": urgency,
            "issue": issue or msg,
            "intake_step": "location",
            "matched_business_id": 0,
            "business_name": "",
            "customer_zip": customer_zip,
            "customer_location": ""
        }

    # Marketplace rule: never collect a name until a business has been matched.
    # This also repairs stale browser chat state from older deployments.
    if not matched_business_id and step in ("name", "phone", "email", "ready"):
        step = "location" if service and service != "General Repair" else ""

    if not step:
        service, urgency = classify(msg)
        issue = msg

        if service == "General Repair":
            return {
                "reply": "I can help find the right local business. What type of work do you need — HVAC, plumbing, electrical, roofing, or something else?",
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "",
                "matched_business_id": 0,
                "business_name": ""
            }

        return {
            "reply": f"Got it — that sounds like {service}. What Florida city or ZIP code is the job in?",
            "service": service,
            "urgency": urgency,
            "issue": issue,
            "intake_step": "location",
            "matched_business_id": 0,
            "business_name": "",
            "customer_location": ""
        }

    if step == "location":
        location = msg
        customer_location = location
        matched, resolved = match_business_for_lead(service, location)

        if not resolved:
            return {
                "reply": "I couldn't verify that as a Florida city or ZIP code. Please send a Florida city or 5-digit ZIP code.",
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "location",
                "matched_business_id": 0,
                "customer_zip": "",
                "customer_location": customer_location
            }

        if not matched:
            place = resolved.get("display") or location
            return {
                "reply": (
                    f"I recognize {place}, but LeadPilot doesn't currently have a verified "
                    f"{service.lower()} provider serving that area. I can notify you when coverage "
                    "becomes available. Would you like me to save a coverage notification for you?"
                ),
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "coverage_waitlist_offer",
                "matched_business_id": 0,
                "business_name": "",
                "customer_zip": resolved.get("postcode") or _extract_zip(location),
                "customer_location": customer_location
            }

        matched_business_id = int(matched["id"])
        matched_business_name = matched["name"] or "a local provider"
        customer_zip = resolved.get("postcode") or _extract_zip(location) or location
        place = resolved.get("display") or location

        return {
            "reply": f"I found {matched_business_name}, which covers {place} and offers {service}. What's your name?",
            "service": service,
            "urgency": urgency,
            "issue": issue,
            "intake_step": "name",
            "matched_business_id": matched_business_id,
            "business_name": matched_business_name,
            "customer_zip": customer_zip,
            "customer_location": customer_location
        }

    if step == "name":
        parsed = _extract_name(msg)
        if not parsed:
            reply = "What name should I put on the request?"
        else:
            customer_name = parsed
            step = "phone"
            reply = f"Thanks, {customer_name}. What's the best 10-digit phone number to reach you?"

    elif step == "phone":
        parsed = _extract_phone(msg)
        if not parsed:
            reply = "Please send a 10-digit phone number."
        else:
            customer_phone = parsed
            step = "email"
            reply = "Got it. What's your email address? You can type SKIP if you'd rather not provide one."

    elif step == "email":
        if msg_lower == "skip":
            customer_email = ""
            step = "details"
            reply = "No problem. Briefly describe what you need fixed or done."
        else:
            parsed = _extract_email(msg)
            if not parsed:
                reply = "That doesn't look like an email address. Try again, or type SKIP."
            else:
                customer_email = parsed
                step = "details"
                reply = "Thanks. Briefly describe what you need fixed or done."

    elif step == "details":
        issue = msg

        # Re-evaluate the customer's FINAL problem description before saving.
        # Earlier chat turns may only contain a broad service name such as
        # "Plumbing", which defaults to Normal urgency. The detailed problem
        # is the best source for urgency and buying intent.
        final_service, final_urgency = classify(issue)

        # Preserve the service we already matched unless the final description
        # clearly identifies another supported trade.
        if final_service != "General Repair":
            service = final_service

        # Always refresh urgency from the actual job description.
        urgency = final_urgency

        step = "submitted"
        reply = (
            f"Got it. I'm sending your {service.lower()} request to "
            f"{matched_business_name} now."
        )

    elif step == "submitted":
        reply = f"Your request has already been sent to {matched_business_name}."

    else:
        reply = "Tell me briefly what you need fixed or done."
        step = "details"

    return {
        "reply": reply,
        "service": service,
        "urgency": urgency,
        "issue": issue,
        "intake_step": step,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "customer_zip": customer_zip,
        "matched_business_id": matched_business_id,
        "business_name": matched_business_name,
        "customer_location": customer_location,
        "submit_ready": step == "submitted"
    }


def classify(text):
    t = (text or "").lower()

    if any(x in t for x in ["ac ", "ac.", "my ac", "a/c", "air condition", "hvac", "heat", "furnace"]):
        service = "HVAC"
    elif any(x in t for x in ["pipe", "plumb", "toilet", "sink", "drain", "water leak", "leak"]):
        service = "Plumbing"
    elif any(x in t for x in ["electric", "outlet", "breaker", "power", "wire", "wiring", "sparking"]):
        service = "Electrical"
    elif any(x in t for x in ["roof", "shingle", "roof leak", "ceiling leak"]):
        service = "Roofing"
    else:
        service = "General Repair"

    emergency_signals = [
        "gas leak", "smell gas", "fire", "sparking", "electrical arcing",
        "burst pipe", "major flooding", "water pouring", "ceiling collapsing"
    ]

    high_time_signals = [
        "today", "asap", "urgent", "right now", "immediately",
        "need it fixed now", "need someone now", "same day"
    ]

    active_problem_signals = [
        "not working", "stopped working", "no ac", "no heat",
        "leaking", "leak", "flooding", "overflowing", "broken",
        "won't turn on", "wont turn on", "no power"
    ]

    if any(x in t for x in emergency_signals):
        urgency = "Emergency"
    elif any(x in t for x in high_time_signals) or any(x in t for x in active_problem_signals):
        urgency = "High"
    else:
        urgency = "Normal"

    return service, urgency

def qualify_lead(name, phone, email, zip_code, service, urgency, message):
    """Lead Scoring V2.1 — scoring-only upgrade; chat/intake behavior unchanged."""
    vals = locals()
    def val(*keys):
        for key in keys:
            if key in vals and vals[key] is not None:
                return str(vals[key])
        return ""

    name_v = val("name", "customer_name")
    phone_v = val("phone", "customer_phone")
    email_v = val("email", "customer_email")
    zip_v = val("zip_code", "zip", "customer_zip")
    service_v = val("service").strip()
    urgency_v = val("urgency").strip()
    message_v = val("message", "details", "issue").strip()
    t = message_v.lower()

    score = 20
    if urgency_v.lower() in ("emergency", "urgent"):
        score += 35
    elif urgency_v.lower() == "high":
        score += 25
    else:
        score += 5

    immediate = ("today","right now","asap","immediately","emergency","need someone","send someone","need it fixed","can you come","appointment","schedule","book","quote","estimate")
    research = ("thinking about","later this year","sometime","just curious","price range","researching","considering")
    severe = ("not working","stopped working","no ac","no heat","leaking","burst","flooding","sparking","smell gas","roof leaking","ceiling leaking","won\'t turn on","broken")
    projects = ("replace","replacement","install","installation","new system","new roof","repiping","panel upgrade","water heater","whole house")

    if any(x in t for x in immediate): score += 18
    if any(x in t for x in research): score -= 10
    if any(x in t for x in severe): score += 15
    if any(x in t for x in projects): score += 7
    if urgency_v.lower() == "high" and any(x in t for x in severe): score += 8
    if service_v and service_v.lower() != "general repair": score += 7
    if phone_v: score += 8
    if email_v: score += 3
    if zip_v: score += 5
    if name_v: score += 2
    if len(message_v) >= 80: score += 5
    elif len(message_v) >= 30: score += 3

    score = max(0, min(int(score), 100))
    if score >= 90:
        qualification = "Hot"
        action = "Call immediately. Strong urgency and buying intent."
    elif score >= 75:
        qualification = "Strong"
        action = "Contact within 5-10 minutes and try to book the job."
    elif score >= 55:
        qualification = "Qualified"
        action = "Contact soon and offer the next available appointment."
    else:
        qualification = "Standard"
        action = "Follow up and continue qualifying the customer."

    return {"lead_score": score, "qualification": qualification, "recommended_action": action}

def _clean_phone(value):
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits

def _extract_phone(value):
    digits = _clean_phone(value)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return ""

def _extract_email(value):
    for token in (value or "").replace(",", " ").split():
        token = token.strip(" <>[](){};:")
        if "@" in token and "." in token.split("@")[-1]:
            return token
    return ""

def _extract_zip(value):
    m = re.search(r"\b\d{5}(?:-\d{4})?\b", value or "")
    return m.group(0) if m else ""

def _extract_name(value):
    value = (value or "").strip()
    low = value.lower()
    for prefix in ["my name is ", "i'm ", "im ", "i am "]:
        if low.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    if 1 <= len(value.split()) <= 4 and not any(ch.isdigit() for ch in value):
        return value.title()
    return ""

def assistant_reply(message, context=None, business_id=BUSINESS_ID):
    """
    Dedicated business-page flow.

    Important rule:
    Problem -> location verification -> confirm this business -> name -> phone -> email.

    The chat must NOT tell a customer that the request is "for" the business until
    LeadPilot confirms that the business is eligible, offers the service, and covers
    the customer's location.
    """
    business = get_business_settings(business_id)
    context = context or {}

    if not business_can_receive_leads(business):
        return {
            "reply": "This provider is not currently eligible to receive new LeadPilot requests. Please return to LeadPilot to find another available provider.",
            "service": context.get("service", ""),
            "urgency": context.get("urgency", "Normal"),
            "issue": context.get("issue", ""),
            "intake_step": "blocked",
            "customer_name": "",
            "customer_phone": "",
            "customer_email": "",
            "customer_zip": "",
            "customer_location": "",
            "matched_business_id": 0,
            "business_name": ""
        }

    business_name = business.get("name") or BUSINESS_NAME
    services_raw = business.get("services") or ""
    services = [s.strip() for s in services_raw.split(",") if s.strip()]
    services_lower = [s.lower() for s in services]

    msg = (message or "").strip()
    msg_lower = msg.lower()

    intake_step = (context.get("intake_step") or "").strip()
    service = (context.get("service") or "").strip()
    urgency = (context.get("urgency") or "Normal").strip()
    issue = (context.get("issue") or "").strip()
    customer_name = (context.get("customer_name") or "").strip()
    customer_phone = (context.get("customer_phone") or "").strip()
    customer_email = (context.get("customer_email") or "").strip()
    customer_zip = (context.get("customer_zip") or "").strip()
    customer_location = (context.get("customer_location") or "").strip()

    if intake_step == "location":
        resolved = resolve_florida_location(msg)
        if not resolved:
            return {
                "reply": "I couldn't verify that as a Florida city or ZIP code. Please send the city or 5-digit ZIP code where the job is located.",
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "location",
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "customer_email": customer_email,
                "customer_zip": "",
                "customer_location": msg,
                "matched_business_id": 0,
                "business_name": ""
            }

        customer_location = msg
        customer_zip = resolved.get("postcode") or msg
        place = resolved.get("display") or msg

        if not business_serves_location(business, resolved):
            return {
                "reply": (
                    f"I recognize {place}, but this provider does not currently list that area "
                    "as part of its LeadPilot service territory. Please return to LeadPilot and "
                    "I'll match you with another available provider."
                ),
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "outside_area",
                "customer_name": "",
                "customer_phone": "",
                "customer_email": "",
                "customer_zip": customer_zip,
                "customer_location": customer_location,
                "matched_business_id": 0,
                "business_name": ""
            }

        return {
            "reply": (
                f"Yes — {business_name} serves {place} and offers {service}. "
                "What's your name?"
            ),
            "service": service,
            "urgency": urgency,
            "issue": issue,
            "intake_step": "name",
            "customer_name": "",
            "customer_phone": "",
            "customer_email": "",
            "customer_zip": customer_zip,
            "customer_location": customer_location,
            "matched_business_id": business_id,
            "business_name": business_name
        }

    if intake_step == "name":
        parsed = _extract_name(msg)
        if not parsed:
            reply = "I just need your name first. What name should I put on the request?"
        else:
            customer_name = parsed
            intake_step = "phone"
            reply = f"Thanks, {customer_name}. What's the best 10-digit phone number to reach you?"

    elif intake_step == "phone":
        parsed = _extract_phone(msg)
        if not parsed:
            reply = "Please send a 10-digit phone number so the business can contact you."
        else:
            customer_phone = parsed
            intake_step = "email"
            reply = "Got it. What's your email address? You can type SKIP if you'd rather not provide one."

    elif intake_step == "email":
        if msg_lower == "skip":
            customer_email = ""
            intake_step = "ready"
            reply = (
                f"Perfect. Your {service.lower()} request is ready for {business_name}. "
                "Your information is filled into the request form below. Tap Submit Request to send it."
            )
        else:
            parsed = _extract_email(msg)
            if not parsed:
                reply = "That doesn't look like an email address. Please try again, or type SKIP."
            else:
                customer_email = parsed
                intake_step = "ready"
                reply = (
                    f"Perfect. Your {service.lower()} request is ready for {business_name}. "
                    "Your information is filled into the request form below. Tap Submit Request to send it."
                )

    elif intake_step in ("ready", "outside_area", "blocked"):
        if intake_step == "outside_area":
            reply = "Please return to LeadPilot so I can match you with another provider that serves your area."
        elif intake_step == "blocked":
            reply = "This provider is not currently eligible to receive new requests."
        else:
            reply = f"Your request is ready to submit to {business_name}."

    else:
        detected_service, detected_urgency = classify(msg)
        service = detected_service
        urgency = detected_urgency
        issue = msg

        if service == "General Repair":
            return {
                "reply": "What type of work do you need — HVAC, plumbing, electrical, roofing, or something else?",
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "",
                "customer_name": "",
                "customer_phone": "",
                "customer_email": "",
                "customer_zip": "",
                "customer_location": "",
                "matched_business_id": 0,
                "business_name": ""
            }

        service_supported = any(
            service.lower() in s or s in service.lower()
            for s in services_lower
        ) if services else True

        if not service_supported:
            offered = ", ".join(services) or "its listed services"
            return {
                "reply": (
                    f"This provider currently lists {offered}. Your request sounds like {service}. "
                    "Please return to LeadPilot and I'll match you with a provider for that service."
                ),
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "blocked",
                "customer_name": "",
                "customer_phone": "",
                "customer_email": "",
                "customer_zip": "",
                "customer_location": "",
                "matched_business_id": 0,
                "business_name": ""
            }

        # Do NOT name the business yet. Location comes first.
        return {
            "reply": f"Got it — that sounds like {service}. What Florida city or ZIP code is the job in?",
            "service": service,
            "urgency": urgency,
            "issue": issue,
            "intake_step": "location",
            "customer_name": "",
            "customer_phone": "",
            "customer_email": "",
            "customer_zip": "",
            "customer_location": "",
            "matched_business_id": 0,
            "business_name": ""
        }

    return {
        "reply": reply,
        "service": service,
        "urgency": urgency,
        "issue": issue,
        "intake_step": intake_step,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "customer_zip": customer_zip,
        "customer_location": customer_location,
        "matched_business_id": business_id if intake_step not in ("outside_area","blocked") else 0,
        "business_name": business_name if intake_step not in ("outside_area","blocked") else ""
    }


def send_twilio_body(to_phone, body):
    """Send a raw Twilio SMS body. Returns True on success."""
    if not all([to_phone, TWILIO_PHONE_NUMBER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN]):
        return False

    endpoint = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Messages.json"
    )

    payload = urlencode({
        "To": to_phone,
        "From": TWILIO_PHONE_NUMBER,
        "Body": body
    }).encode()

    import base64
    token = base64.b64encode(
        f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()
    ).decode()

    req = Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )

    try:
        with urlopen(req, timeout=15) as resp:
            return 200 <= getattr(resp, "status", 0) < 300
    except Exception as e:
        detail = ""
        try:
            if hasattr(e, "read"):
                detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass

        # Trial accounts may only allow predefined bodies.
        if "572006" in detail:
            try:
                payload = urlencode({
                    "To": to_phone,
                    "From": TWILIO_PHONE_NUMBER,
                    "Body": "sms_internal_alerts"
                }).encode()
                req = Request(
                    endpoint,
                    data=payload,
                    method="POST",
                    headers={
                        "Authorization": f"Basic {token}",
                        "Content-Type": "application/x-www-form-urlencoded"
                    }
                )
                with urlopen(req, timeout=15) as resp:
                    return 200 <= getattr(resp, "status", 0) < 300
            except Exception as e2:
                print("Twilio fallback chase error:", repr(e2), flush=True)
                return False

        print("Twilio chase error:", repr(e), detail[:600], flush=True)
        return False


def run_lead_chase_once():
    """Send reminder alerts for overdue Hot leads across all businesses."""
    try:
        for business, _metrics in list_businesses():
            business_id = int(business["id"])
            alert_phone = (business["alert_phone"] or NOTIFY_PHONE or "").strip()
            if not alert_phone:
                continue

            con = db()
            rows = execute(
                con,
                """SELECT * FROM leads
                   WHERE business_id=? AND status='New'
                   ORDER BY id DESC""",
                (business_id,)
            ).fetchall()

            for r in rows:
                score = int(r["lead_score"] or 0)
                quality = (r["qualification"] or "").strip()
                if quality != "Hot" and score < 90:
                    continue

                mins = lead_wait_minutes(r)
                chase10 = int(r["chase_10_sent"] or 0)
                chase30 = int(r["chase_30_sent"] or 0)

                if mins >= 10 and not chase10:
                    name = (r["name"] or "Customer").strip()
                    phone = (r["phone"] or "No phone").strip()
                    service = (r["service"] or "Service").strip()
                    body = (
                        f"🔥 LeadPilot follow-up: {service} lead {name} "
                        f"({phone}) has been waiting {mins} minutes. Contact now."
                    )
                    if send_twilio_body(alert_phone, body):
                        execute(
                            con,
                            "UPDATE leads SET chase_10_sent=1 WHERE id=? AND business_id=?",
                            (r["id"], business_id)
                        )
                        con.commit()
                        chase10 = 1
                        print("Lead chase 10-min sent:", business_id, r["id"], flush=True)

                if mins >= 30 and not chase30:
                    name = (r["name"] or "Customer").strip()
                    phone = (r["phone"] or "No phone").strip()
                    service = (r["service"] or "Service").strip()
                    body = (
                        f"🚨 URGENT LeadPilot: Hot {service} lead {name} "
                        f"({phone}) is still New after {mins} minutes."
                    )
                    if send_twilio_body(alert_phone, body):
                        execute(
                            con,
                            "UPDATE leads SET chase_30_sent=1 WHERE id=? AND business_id=?",
                            (r["id"], business_id)
                        )
                        con.commit()
                        print("Lead chase 30-min sent:", business_id, r["id"], flush=True)

            con.close()

    except Exception as e:
        print("Lead chase worker error:", repr(e), flush=True)

def lead_chase_worker():
    """Background MVP worker. Checks about once per minute while the web service is awake."""
    while True:
        run_lead_chase_once()
        time.sleep(60)


def send_hot_lead_sms(lead_id, name, phone, service, urgency, message, qualification, business_id=BUSINESS_ID):
    """Send a Hot-lead SMS. On Twilio trial error 572006, fall back to a permitted trial template."""
    if qualification.get("qualification") != "Hot":
        return False

    business = get_business_settings(business_id)
    alert_phone = (business.get("alert_phone") or NOTIFY_PHONE).strip()

    if not all([
        alert_phone,
        TWILIO_PHONE_NUMBER,
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN
    ]):
        print("SMS skipped: Twilio environment variables are incomplete.", flush=True)
        return False

    score = qualification.get("lead_score", 0)
    action = qualification.get(
        "recommended_action",
        "Call the customer as soon as possible."
    )

    customer_name = (name or "Not provided").strip()
    customer_phone = (phone or "Not provided").strip()
    service_name = (service or "General Repair").strip()
    urgency_name = (urgency or "Normal").strip()
    issue = " ".join((message or "").split()).strip()
    if len(issue) > 180:
        issue = issue[:177] + "..."

    detailed_body = (
        f"🔥 HOT LEAD — {score}/100\n"
        f"{service_name} · {urgency_name} urgency\n"
        f"Customer: {customer_name}\n"
        f"Phone: {customer_phone}\n"
        f"Issue: {issue or 'Not provided'}\n"
        f"Next step: {action}"
    )

    endpoint = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Messages.json"
    )

    import base64
    token = base64.b64encode(
        f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()
    ).decode()

    def twilio_send(body):
        payload = urlencode({
            "To": alert_phone,
            "From": TWILIO_PHONE_NUMBER,
            "Body": body
        }).encode()

        req = Request(
            endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )

        with urlopen(req, timeout=15) as resp:
            return 200 <= getattr(resp, "status", 0) < 300

    try:
        ok = twilio_send(detailed_body)
        print("Twilio hot-lead SMS:", "sent" if ok else "failed", flush=True)
        return ok

    except Exception as e:
        detail = ""
        try:
            if hasattr(e, "read"):
                detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""

        # Twilio trial accounts reject custom bodies with error 572006.
        if "572006" in detail:
            print(
                "Twilio trial restriction detected; sending permitted fallback template.",
                flush=True
            )
            try:
                ok = twilio_send("sms_internal_alerts")
                print(
                    "Twilio fallback SMS:",
                    "sent" if ok else "failed",
                    flush=True
                )
                return ok
            except Exception as fallback_error:
                fallback_detail = ""
                try:
                    if hasattr(fallback_error, "read"):
                        fallback_detail = fallback_error.read().decode(
                            "utf-8",
                            errors="replace"
                        )
                except Exception:
                    fallback_detail = ""

                print(
                    "Twilio fallback SMS error:",
                    repr(fallback_error),
                    fallback_detail[:1000],
                    flush=True
                )
                return False

        print("Twilio SMS error:", repr(e), detail[:1000], flush=True)
        return False

def make_session(username):
    sig = hmac.new(
        SESSION_SECRET.encode(),
        username.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"{username}.{sig}"

def session_valid(value):
    if not value or "." not in value:
        return False

    username, sig = value.rsplit(".", 1)

    expected = hmac.new(
        SESSION_SECRET.encode(),
        username.encode(),
        hashlib.sha256
    ).hexdigest()

    return (
        username == ADMIN_USERNAME
        and hmac.compare_digest(sig, expected)
    )

def logged_in(headers):
    cookie = SimpleCookie()
    cookie.load(headers.get("Cookie", ""))

    token = cookie.get("leadpilot_session")

    return bool(token and session_valid(token.value))

INDEX = r"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot AI</title>
<style>
body{font-family:Arial,sans-serif;margin:0;background:#f4f7fb;color:#172033}
.wrap{max-width:720px;margin:auto;padding:24px}
.card{background:#fff;border-radius:18px;padding:22px;box-shadow:0 8px 30px rgba(0,0,0,.08);margin-bottom:18px}
h1{margin:0 0 8px;font-size:30px}.muted{color:#667085}
.chat{min-height:180px;background:#f7f9fc;border-radius:14px;padding:14px;overflow:auto}
.msg{padding:10px 12px;border-radius:12px;margin:8px 0;max-width:85%}
.bot{background:#e9eefb}.user{background:#172033;color:#fff;margin-left:auto}
.row{display:flex;gap:8px;margin-top:12px}
input,textarea,button{font:inherit}
input,textarea{width:100%;box-sizing:border-box;padding:12px;border:1px solid #d0d5dd;border-radius:10px;margin:6px 0}
button{padding:12px 16px;border:0;border-radius:10px;background:#172033;color:#fff;font-weight:700}
.success{color:#067647;font-weight:bold}a{color:#3448c5}
</style>
</head>
<body>
<div class="wrap">

<div class="card">
<h1>LeadPilot AI</h1>
<div class="muted">24/7 lead assistant for local service businesses</div>
</div>

<div class="card">
<h2>How can we help?</h2>
<div id="chat" class="chat">
<div class="msg bot">Hi! Tell me what you need help with.</div>
</div>
<div class="row">
<input id="message" placeholder="Describe the problem...">
<button onclick="sendChat()">Send</button>
</div>
</div>

<div class="card">
<h2>Request summary</h2>
<input id="name" placeholder="Name">
<input id="phone" placeholder="Phone">
<input id="email" placeholder="Email">
<input id="zip" placeholder="ZIP / location">
<input id="service" placeholder="Service type" readonly>
<input id="urgency" placeholder="Urgency" readonly>
<textarea id="details" rows="4" placeholder="Describe what you need"></textarea>
<button onclick="submitLead()">Send Request</button>
<p id="result"></p>
</div>

<div class="card">
<strong>Business owner?</strong>
<a href="/login">Business login</a>
</div>

</div>

<script>
let chatContext = {
  service: "",
  urgency: "",
  issue: "",
  intake_step: "",
  customer_name: "",
  customer_phone: "",
  customer_email: "",
  customer_zip: "",
  matched_business_id: 0,
  business_name: "",
  customer_location: "",
  waitlist_name: "",
  waitlist_phone: "",
  waitlist_email: "",
  marketplace_mode: __MARKETPLACE_MODE__,
  lead_submitted: false
};

function add(text,cls){
 const c=document.getElementById('chat');
 const d=document.createElement('div');
 d.className='msg '+cls;
 d.textContent=text;
 c.appendChild(d);
 c.scrollTop=c.scrollHeight;
}

async function sendChat(){
 const el=document.getElementById('message');
 const message=el.value.trim();
 if(!message)return;

 add(message,'user');
 el.value='';

 const r=await fetch('/api/chat',{
   method:'POST',
   headers:{'Content-Type':'application/json'},
   body:JSON.stringify({
     message,
     context: chatContext,
     business_id: __BUSINESS_ID__,
     marketplace_mode: chatContext.marketplace_mode
   })
 });

 const j=await r.json();

 add(j.reply,'bot');
 chatContext.service=j.service||chatContext.service;
 chatContext.urgency=j.urgency||chatContext.urgency;
 chatContext.issue=j.issue||chatContext.issue;
 if(j.intake_step!==undefined) chatContext.intake_step=j.intake_step;
 chatContext.customer_name=j.customer_name||chatContext.customer_name;
 chatContext.customer_phone=j.customer_phone||chatContext.customer_phone;
 if(j.customer_email!==undefined) chatContext.customer_email=j.customer_email;
 chatContext.customer_zip=j.customer_zip||chatContext.customer_zip;
 chatContext.matched_business_id=j.matched_business_id||chatContext.matched_business_id;
 chatContext.business_name=j.business_name||chatContext.business_name;
 if(j.customer_location!==undefined) chatContext.customer_location=j.customer_location;
 if(j.waitlist_name!==undefined) chatContext.waitlist_name=j.waitlist_name;
 if(j.waitlist_phone!==undefined) chatContext.waitlist_phone=j.waitlist_phone;
 if(j.waitlist_email!==undefined) chatContext.waitlist_email=j.waitlist_email;

 document.getElementById('service').value=chatContext.service;
 document.getElementById('urgency').value=chatContext.urgency;
 if(j.issue) document.getElementById('details').value=j.issue;

 const nameEl=document.getElementById('name');
 const phoneEl=document.getElementById('phone');
 const emailEl=document.getElementById('email');
 const zipEl=document.getElementById('zip');

 if(nameEl && chatContext.customer_name) nameEl.value=chatContext.customer_name;
 if(phoneEl && chatContext.customer_phone) phoneEl.value=chatContext.customer_phone;
 if(emailEl) emailEl.value=chatContext.customer_email||'';
 if(zipEl){
   zipEl.value=chatContext.customer_zip||chatContext.customer_location||'';
 }

 if(j.submit_ready && chatContext.marketplace_mode && !chatContext.lead_submitted){
   await submitLead(true);
 }
}

async function submitLead(auto=false){
 if(chatContext.lead_submitted)return;
 const data={
   business_id: chatContext.matched_business_id || __BUSINESS_ID__,
   name:document.getElementById('name').value,
   phone:document.getElementById('phone').value,
   email:document.getElementById('email').value,
   zip:document.getElementById('zip').value,
   service:document.getElementById('service').value||'General Repair',
   urgency:document.getElementById('urgency').value||'Normal',
   message:document.getElementById('details').value
 };

 const result=document.getElementById('result');

 if(!data.name || !data.phone){
   result.textContent='Please complete the chat so I can collect your name and phone number.';
   return;
 }

 const r=await fetch('/api/leads',{
   method:'POST',
   headers:{'Content-Type':'application/json'},
   body:JSON.stringify(data)
 });

 const j=await r.json();

 if(r.ok){
   chatContext.lead_submitted=true;
   const sendButton=document.querySelector('button[onclick="submitLead()"]');
   if(sendButton){
     sendButton.disabled=true;
     sendButton.textContent='Request Sent ✓';
   }

   const businessName = chatContext.business_name || '__BUSINESS_NAME__';
   const firstName = (data.name || '').trim().split(/\s+/)[0] || 'there';
   result.className='success';
   result.textContent =
     `Thanks, ${firstName}. Your ${data.service.toLowerCase()} request has been sent to ${businessName}. ` +
     `They'll contact you as soon as possible.`;

   if(!auto){
     add(
       `Thanks, ${firstName}. Your request has been sent to ${businessName}. ` +
       `They'll contact you as soon as possible.`,
       'bot'
     );
   } else {
     add(
       `✓ Sent to ${businessName}. They'll contact you as soon as possible.`,
       'bot'
     );
   }

   chatContext.intake_step='complete';
 } else {
   result.className='';
   result.textContent='Something went wrong. Please try again.';
 }
}
</script>
</body>
</html>"""

LOGIN = r"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot Business Login</title>
<style>
body{font-family:Arial,sans-serif;margin:0;background:#f4f7fb;color:#172033}
.wrap{max-width:430px;margin:60px auto;padding:18px}
.card{background:#fff;border-radius:20px;padding:26px;box-shadow:0 8px 30px rgba(0,0,0,.08)}
h1{margin-top:0}.muted{color:#667085;margin-bottom:18px}
input{width:100%;box-sizing:border-box;padding:13px;border:1px solid #d0d5dd;border-radius:10px;margin:7px 0;font-size:16px}
button{width:100%;padding:13px;border:0;border-radius:10px;background:#172033;color:#fff;font-weight:800;font-size:16px;margin-top:10px}
.error{color:#b42318;margin-top:12px}.back{display:inline-block;margin-top:18px;color:#3448c5;text-decoration:none;font-weight:700}
</style>
</head>
<body>
<div class="wrap">
<div class="card">
<h1>Business Login</h1>
<div class="muted">Sign in to your LeadPilot dashboard.</div>

<form method="POST" action="/login">
<input name="username" placeholder="Username" autocomplete="username" required>
<input name="password" type="password" placeholder="Password" autocomplete="current-password" required>
<button type="submit">Sign In</button>
<div class="error">__ERROR__</div>
</form>

<a class="back" href="/">← Customer page</a>
</div>
</div>
</body>
</html>"""

def customer_page_html(business_id=BUSINESS_ID):
    business = get_business_settings(business_id)
    business_name = business.get("name") or BUSINESS_NAME

    if not business_can_receive_leads(business):
        status = effective_verification_status(business)
        return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(business_name)} — LeadPilot</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}
.wrap{{max-width:720px;margin:auto;padding:22px}}
.card{{background:#fff;border-radius:18px;padding:22px;box-shadow:0 6px 20px rgba(0,0,0,.06);margin-top:40px}}
.status{{display:inline-block;margin-top:8px;padding:8px 12px;border-radius:999px;background:#fff0c2;color:#93370d;font-weight:800}}
p{{color:#667085;line-height:1.5}}
a{{display:inline-block;margin-top:14px;color:#3448c5;font-weight:800;text-decoration:none}}
</style></head>
<body><div class="wrap"><div class="card">
<h1>{html.escape(business_name)}</h1>
<div class="status">{html.escape(status)}</div>
<p>This provider is not currently eligible to receive new LeadPilot requests.</p>
<p>Please return to LeadPilot to find another available provider for your service and location.</p>
<a href="/">Find another provider</a>
</div></div></body></html>"""

    page = INDEX
    page = page.replace("LeadPilot Demo Services", html.escape(business_name))
    page = page.replace(
        "__BUSINESS_NAME__",
        business_name.replace("\\", "\\\\").replace("'", "\\'")
    )
    page = page.replace("__BUSINESS_ID__", str(business_id))
    page = page.replace("__MARKETPLACE_MODE__", "false")
    return page


def marketplace_page_html():
    page = INDEX
    page = page.replace("LeadPilot Demo Services", "LeadPilot AI")
    page = page.replace("24/7 lead assistant for local service businesses", "Find a local service business matched to your job and location")
    page = page.replace("__BUSINESS_NAME__", "LeadPilot AI")
    page = page.replace("__BUSINESS_ID__", "0")
    page = page.replace("__MARKETPLACE_MODE__", "true")
    return page

def dashboard_score_reasons(row):
    """Create a short explanation from stored lead data."""
    t = (row["message"] or "").lower()
    reasons = []

    urgency = (row["urgency"] or "Normal").lower()
    if urgency in ("emergency", "urgent"):
        reasons.append("Emergency urgency")
    elif urgency == "high":
        reasons.append("High urgency")

    if any(x in t for x in [
        "today", "right now", "asap", "immediately",
        "need someone", "need it fixed", "appointment", "schedule", "book"
    ]):
        reasons.append("Ready to act")

    if any(x in t for x in [
        "not working", "stopped working", "no ac", "no heat",
        "leaking", "burst", "flooding", "sparking", "broken"
    ]):
        reasons.append("Active problem")

    if row["phone"]:
        reasons.append("Phone provided")

    if row["zip"]:
        reasons.append("Location provided")

    if any(x in t for x in [
        "replace", "replacement", "install", "installation",
        "new system", "new roof", "water heater", "panel upgrade"
    ]):
        reasons.append("Larger-project signal")

    if any(x in t for x in [
        "thinking about", "later this year", "sometime",
        "just curious", "price range", "researching", "considering"
    ]):
        reasons.append("Research-stage timing")

    return reasons[:4] or ["Basic lead information"]


def lead_wait_minutes(row):
    """Minutes since the lead was created. created_at is stored in UTC."""
    raw = (row["created_at"] or "").strip()
    if not raw:
        return 0

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            created = datetime.strptime(raw, fmt)
            return max(0, int((datetime.utcnow() - created).total_seconds() // 60))
        except ValueError:
            pass

    return 0


def format_wait_time(minutes):
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    days = hours // 24
    rem_hours = hours % 24
    return f"{days}d {rem_hours}h" if rem_hours else f"{days}d"


def lead_followup_status(row):
    """Timer-aware follow-up recommendation for the dashboard."""
    status = (row["status"] or "New").strip()
    score = int(row["lead_score"] or 0)
    qualification = (row["qualification"] or "Standard").strip()
    wait_minutes = lead_wait_minutes(row)

    if status == "Closed":
        return ("done", "Closed — no follow-up needed", wait_minutes, False)
    if status == "Booked":
        return ("booked", "Booked — customer is scheduled", wait_minutes, False)
    if status == "Contacted":
        return ("contacted", "Contacted — continue follow-up as needed", wait_minutes, False)

    # Response-time goals by lead quality.
    if qualification == "Hot" or score >= 90:
        limit = 10
        label = "Hot lead"
    elif qualification == "Strong" or score >= 75:
        limit = 20
        label = "Strong lead"
    elif qualification == "Qualified" or score >= 55:
        limit = 60
        label = "Qualified lead"
    else:
        limit = 120
        label = "Standard lead"

    overdue = wait_minutes >= limit

    if overdue:
        return (
            "overdue",
            f"🚨 OVERDUE — {label} waiting {format_wait_time(wait_minutes)}. Contact now.",
            wait_minutes,
            True
        )

    remaining = max(1, limit - wait_minutes)

    if qualification == "Hot" or score >= 90:
        text = f"🔥 Call now — {format_wait_time(wait_minutes)} waiting · goal under {limit} min"
        css = "urgent"
    elif qualification == "Strong" or score >= 75:
        text = f"Follow up within {remaining} min · waiting {format_wait_time(wait_minutes)}"
        css = "soon"
    elif qualification == "Qualified" or score >= 55:
        text = f"Follow up within {remaining} min · waiting {format_wait_time(wait_minutes)}"
        css = "today"
    else:
        text = f"Standard follow-up · waiting {format_wait_time(wait_minutes)}"
        css = "normal"

    return (css, text, wait_minutes, False)

def dashboard_html(business_id=BUSINESS_ID):
    business = get_business_settings(business_id)
    con = db()

    rows = execute(
        con,
        """SELECT * FROM leads
           WHERE business_id=?
           ORDER BY lead_score DESC, id DESC""",
        (business_id,)
    ).fetchall()

    routing_metrics = business_routing_metrics(con, business_id)
    con.close()

    counts = {"New":0, "Contacted":0, "Booked":0, "Closed":0}
    quality_counts = {"Hot":0, "Strong":0, "Qualified":0, "Standard":0}
    followup_count = 0
    overdue_count = 0

    for r in rows:
        status = r["status"] or "New"
        counts[status] = counts.get(status, 0) + 1

        quality = r["qualification"] or "Standard"
        quality_counts[quality] = quality_counts.get(quality, 0) + 1

        if status == "New":
            followup_count += 1
            _, _, _, is_overdue = lead_followup_status(r)
            if is_overdue:
                overdue_count += 1

    cards = ""

    for r in rows:
        phone = (r["phone"] or "").strip()
        email = (r["email"] or "").strip()
        status = r["status"] or "New"
        urgency = r["urgency"] or "Normal"
        lead_score = r["lead_score"] or 0
        qualification = r["qualification"] or "Standard"
        recommended_action = r["recommended_action"] or "Follow up and confirm the job details."
        followup_class, followup_text, wait_minutes, is_overdue = lead_followup_status(r)
        wait_text = format_wait_time(wait_minutes)
        score_reasons = dashboard_score_reasons(r)
        reason_chips = "".join(
            f'<span class="reason-chip">{html.escape(reason)}</span>'
            for reason in score_reasons
        )

        options = "".join(
            f'<option value="{s}" {"selected" if s == status else ""}>{s}</option>'
            for s in ["New","Contacted","Booked","Closed"]
        )

        cards += f"""
        <section class="lead-card">
          <div class="lead-top">
            <div>
              <div class="lead-name">{r['name'] or 'Unnamed lead'}</div>
              <div class="lead-time">{r['created_at']} · Waiting {wait_text}</div>
            </div>
            <div class="badges">
              <span class="badge score-badge">{lead_score}/100</span>
              <span class="badge qual-{qualification.lower()}">{qualification}</span>
              <span class="badge urgency-{urgency.lower()}">{urgency}</span>
            </div>
          </div>

          <div class="details">
            <div><span>Service</span><strong>{r['service'] or 'General Repair'}</strong></div>
            <div><span>Location</span><strong>{r['zip'] or '—'}</strong></div>
            <div><span>Phone</span><strong>{phone or '—'}</strong></div>
            <div><span>Email</span><strong>{email or '—'}</strong></div>
          </div>

          <div class="message">{r['message'] or 'No message provided.'}</div>

          <div class="ai-box">
            <div class="ai-title">LeadPilot Qualification</div>
            <div><strong>{qualification} lead · {lead_score}/100</strong></div>
            <div class="reason-row">{reason_chips}</div>
            <div class="next-label">Recommended next step</div>
            <div class="ai-action">{recommended_action}</div>
          </div>

          <div class="followup-banner followup-{followup_class}">
            <strong>Follow-up:</strong> {followup_text}
          </div>

          <div class="actions">
            <a class="action primary" href="tel:{phone}">📞 Call</a>
            <a class="action" href="sms:{phone}">💬 Text</a>
            <a class="action" href="mailto:{email}">✉️ Email</a>
          </div>

          <div class="status-row">
            <label>Lead status</label>
            <div class="status-actions">
              <button class="status-btn {"active" if status == "New" else ""}" onclick="updateStatus({r['id']}, 'New')">New</button>
              <button class="status-btn {"active" if status == "Contacted" else ""}" onclick="updateStatus({r['id']}, 'Contacted')">Contacted</button>
              <button class="status-btn {"active" if status == "Booked" else ""}" onclick="updateStatus({r['id']}, 'Booked')">Booked</button>
              <button class="status-btn {"active" if status == "Closed" else ""}" onclick="updateStatus({r['id']}, 'Closed')">Closed</button>
            </div>
            <span id="saved-{r['id']}" class="saved"></span>
          </div>
        </section>
        """

    if not cards:
        cards = '<div class="empty">No leads yet. New customer requests will appear here.</div>'

    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot Dashboard</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}
.wrap{{max-width:980px;margin:auto;padding:20px}}
header{{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:18px}}
h1{{font-size:28px;margin:0}}
.sub{{color:#667085;margin-top:5px}}
.toplinks a{{margin-left:12px;text-decoration:none;color:#3448c5;font-weight:700}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}}
.stat{{background:#fff;padding:16px;border-radius:14px;box-shadow:0 5px 18px rgba(0,0,0,.06)}}
.stat b{{display:block;font-size:27px;margin-top:5px}}
.stat span{{font-size:13px;color:#667085}}
.leads{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.lead-card{{background:#fff;border-radius:18px;padding:18px;box-shadow:0 7px 24px rgba(0,0,0,.07)}}
.lead-top{{display:flex;justify-content:space-between;gap:12px}}
.lead-name{{font-size:21px;font-weight:800}}
.lead-time{{font-size:12px;color:#667085;margin-top:5px}}
.badges{{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}}
.badge{{padding:7px 10px;border-radius:999px;font-size:12px;font-weight:800;background:#eef2f6}}
.score-badge{{background:#172033;color:#fff}}
.qual-hot{{background:#dcfae6;color:#05603a}}
.qual-strong{{background:#e0e7ff;color:#3730a3}}
.qual-qualified{{background:#eaf2ff;color:#175cd3}}
.qual-standard{{background:#f2f4f7;color:#344054}}
.urgency-emergency{{background:#fee4e2;color:#b42318}}
.urgency-high{{background:#fff0c2;color:#93370d}}
.details{{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:16px 0}}
.details div{{background:#f8fafc;padding:10px;border-radius:10px;overflow:hidden}}
.details span{{display:block;font-size:11px;color:#667085;margin-bottom:4px}}
.details strong{{font-size:14px;word-break:break-word}}
.message{{border-left:4px solid #172033;background:#f7f9fc;padding:12px;border-radius:8px;line-height:1.4}}
.ai-box{{margin-top:12px;padding:12px;border-radius:12px;background:#eef4ff;border:1px solid #d6e4ff}}
.ai-title{{font-size:12px;color:#475467;font-weight:800;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px}}
.ai-action{{font-size:13px;color:#475467;margin-top:4px;line-height:1.35}}
.reason-row{{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}}
.reason-chip{{background:#fff;border:1px solid #dbe3ef;border-radius:999px;padding:5px 8px;font-size:11px;font-weight:700;color:#475467}}
.next-label{{margin-top:11px;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:#667085}}
.priority-summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:0 0 16px}}
.priority-pill{{background:#fff;border-radius:12px;padding:11px 12px;box-shadow:0 4px 14px rgba(0,0,0,.04)}}
.priority-pill strong{{display:block;font-size:20px}}
.priority-pill span{{font-size:11px;color:#667085}}
.priority-note{{font-size:12px;color:#667085;margin:-5px 0 14px}}
.routing-health{{display:flex;align-items:center;justify-content:space-between;gap:16px;background:#fff;border-radius:14px;padding:14px 16px;margin:0 0 14px;box-shadow:0 4px 14px rgba(0,0,0,.04)}}
.routing-health span{{display:block;font-size:12px;color:#667085}}
.routing-health strong{{font-size:28px}}
.routing-health p{{margin:0;color:#667085;font-size:12px;text-align:right}}
.followup-summary{{display:flex;align-items:center;justify-content:space-between;gap:16px;background:#fff;border-radius:14px;padding:14px 16px;margin:0 0 14px;box-shadow:0 4px 14px rgba(0,0,0,.04)}}
.followup-summary span{{display:block;font-size:12px;color:#667085}}
.followup-summary strong{{font-size:28px}}
.followup-summary p{{margin:0;color:#667085;font-size:12px;max-width:460px}}
.followup-banner{{margin:12px 0;padding:10px 12px;border-radius:10px;font-size:12px;font-weight:700}}
.followup-urgent{{background:#fee4e2;color:#b42318}}
.followup-overdue{{background:#b42318;color:#fff;box-shadow:0 0 0 3px rgba(180,35,24,.10)}}
.overdue-total{{padding:0 18px;border-left:1px solid #eaecf0;border-right:1px solid #eaecf0}}
.overdue-total span{{display:block;font-size:12px;color:#667085}}
.overdue-total strong{{font-size:28px;color:#b42318}}
.followup-soon{{background:#fff0c2;color:#93370d}}
.followup-today{{background:#eaf2ff;color:#175cd3}}
.followup-normal{{background:#f2f4f7;color:#344054}}
.followup-contacted{{background:#eef4ff;color:#3448c5}}
.followup-booked{{background:#dcfae6;color:#05603a}}
.followup-done{{background:#f2f4f7;color:#667085}}
.actions{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}}
.action{{display:block;text-align:center;text-decoration:none;border:1px solid #d0d5dd;color:#172033;padding:11px 8px;border-radius:10px;font-weight:800}}
.action.primary{{background:#172033;color:#fff;border-color:#172033}}
.status-row{{display:grid;grid-template-columns:1fr;gap:9px;border-top:1px solid #eaecf0;padding-top:14px}}
.status-row label{{font-weight:800;font-size:13px}}
.status-actions{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}}
.status-btn{{padding:10px 6px;border:1px solid #d0d5dd;border-radius:9px;background:#fff;color:#344054;font-weight:800;font-size:11px}}
.status-btn.active{{background:#172033;color:#fff;border-color:#172033}}
.saved{{color:#067647;font-size:12px;min-height:14px}}
.empty{{background:#fff;padding:25px;border-radius:16px}}

@media(max-width:700px){{
 .wrap{{padding:14px}}
 header{{display:block}}
 .toplinks{{margin-top:10px}}
 .toplinks a{{margin:0 12px 0 0}}
 .stats{{grid-template-columns:1fr 1fr}}
 .priority-summary{{grid-template-columns:1fr 1fr}}
 .followup-summary{{display:block}}
 .followup-summary p{{margin-top:8px}}
 .overdue-total{{border:0;padding:10px 0 0}}
 .leads{{grid-template-columns:1fr}}
 .status-actions{{grid-template-columns:1fr 1fr}}
 h1{{font-size:25px}}
}}
</style>
</head>
<body>

<div class="wrap">

<header>
<div>
<h1>LeadPilot AI — Lead Dashboard</h1>
<div class="sub">{html.escape(business["name"])}</div>
</div>

<div class="toplinks">
<a href="/b/{business_id}">Customer page</a>
<a href="/settings?business={business_id}">Settings</a> <a href="/businesses">Businesses</a> <a href="/coverage-demand">Coverage Demand</a>
<a href="/logout">Log out</a>
</div>
</header>

<div class="stats">
<div class="stat"><span>New Leads</span><b>{counts.get('New',0)}</b></div>
<div class="stat"><span>Contacted</span><b>{counts.get('Contacted',0)}</b></div>
<div class="stat"><span>Booked</span><b>{counts.get('Booked',0)}</b></div>
<div class="stat"><span>Closed</span><b>{counts.get('Closed',0)}</b></div>
</div>

<div class="routing-health">
  <div>
    <span>Marketplace routing health</span>
    <strong>{routing_metrics["health"]}/100</strong>
  </div>
  <p>{routing_metrics["today_count"]} lead(s) today · {routing_metrics["new_count"]} still New · {routing_metrics["overdue_new"]} overdue</p>
</div>

<div class="followup-summary">
  <div>
    <span>Needs follow-up</span>
    <strong>{followup_count}</strong>
  </div>
  <div class="overdue-total">
    <span>Overdue</span>
    <strong>{overdue_count}</strong>
  </div>
  <p>Timers stop when a lead is marked Contacted, Booked, or Closed.</p>
</div>

<div class="priority-summary">
  <div class="priority-pill"><strong>{quality_counts['Hot']}</strong><span>🔥 Hot leads</span></div>
  <div class="priority-pill"><strong>{quality_counts['Strong']}</strong><span>Strong leads</span></div>
  <div class="priority-pill"><strong>{quality_counts['Qualified']}</strong><span>Qualified leads</span></div>
  <div class="priority-pill"><strong>{quality_counts['Standard']}</strong><span>Standard leads</span></div>
</div>
<div class="priority-note">New leads are automatically ordered by score so the best opportunities appear first.</div>

<div class="leads">{cards}</div>

</div>

<script>
setTimeout(()=>location.reload(),60000);

async function updateStatus(id,status){{
 const s=document.getElementById('saved-'+id);
 s.textContent='Saving '+status+'...';

 const r=await fetch('/api/leads/'+id+'/status?business={business_id}',{{
   method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{status}})
 }});

 if(r.ok){{
   const row=s.closest('.status-row');
   const buttons=row.querySelectorAll('.status-btn');

   buttons.forEach(btn=>{{
     btn.classList.toggle(
       'active',
       btn.textContent.trim() === status
     );
   }});

   s.textContent='✓ '+status;
   setTimeout(()=>location.reload(),900);
 }}else{{
   s.textContent='Could not save';
 }}
}}
</script>

</body>
</html>"""

class Handler(BaseHTTPRequestHandler):

    def send_bytes(self, data, status=200, content_type="text/html; charset=utf-8", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if content_type.startswith("text/html"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")

        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)

        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location, headers=None):
        self.send_response(302)
        self.send_header("Location", location)

        if headers:
            for k, v in headers:
                self.send_header(k, v)

        self.end_headers()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        p = parsed_url.path
        query = parse_qs(parsed_url.query)

        if p == "/":
            self.send_bytes(marketplace_page_html().encode())

        elif p.startswith("/b/"):
            try:
                business_id = int(p.strip("/").split("/")[1])
            except Exception:
                self.send_bytes(b"Bad business page", 400, "text/plain")
                return

            business = get_business_settings(business_id)
            if not business or not business.get("name"):
                self.send_bytes(b"Business not found", 404, "text/plain")
                return

            self.send_bytes(customer_page_html(business_id).encode())

        elif p == "/businesses":
            if not logged_in(self.headers):
                self.redirect("/login")
                return
            created = query.get("created", [None])[0]
            self.send_bytes(businesses_html(created_id=created).encode())

        elif p == "/coverage-demand":
            if not logged_in(self.headers):
                self.redirect("/login")
                return
            self.send_bytes(coverage_demand_html().encode())

        elif p == "/recruiting":
            if not logged_in(self.headers):
                self.redirect("/login")
                return
            self.send_bytes(
                recruiting_pipeline_html(
                    prefill_service=query.get("service", [""])[0],
                    prefill_city=query.get("city", [""])[0],
                    prefill_count=query.get("count", [""])[0]
                ).encode()
            )

        elif p == "/login":
            if logged_in(self.headers):
                self.redirect("/dashboard")
            else:
                self.send_bytes(LOGIN.replace("__ERROR__", "").encode())

        elif p == "/logout":
            self.redirect(
                "/login",
                [("Set-Cookie", "leadpilot_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")]
            )

        elif p == "/dashboard":
            if not logged_in(self.headers):
                self.redirect("/login")
                return

            try:
                business_id = int(query.get("business", [BUSINESS_ID])[0])
            except Exception:
                business_id = BUSINESS_ID
            self.send_bytes(dashboard_html(business_id).encode())

        elif p == "/settings":
            if not logged_in(self.headers):
                self.redirect("/login")
                return

            try:
                business_id = int(query.get("business", [BUSINESS_ID])[0])
            except Exception:
                business_id = BUSINESS_ID
            self.send_bytes(
                settings_html(
                    saved=query.get("saved") == ["1"],
                    business_id=business_id
                ).encode()
            )

        elif p == "/health":
            payload = json.dumps({
                "ok": True,
                "database": "postgres" if USE_POSTGRES else "sqlite"
            }).encode()

            self.send_bytes(payload, content_type="application/json")

        else:
            self.send_bytes(b"Not found", 404, "text/plain")

    def read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n) or b"{}")

    def read_form(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n).decode()
        parsed = parse_qs(raw)
        return {k: v[0] for k, v in parsed.items()}

    def do_POST(self):
        parsed_url = urlparse(self.path)
        p = parsed_url.path
        query = parse_qs(parsed_url.query)

        try:
            if p == "/login":
                data = self.read_form()

                good_user = hmac.compare_digest(
                    data.get("username", ""),
                    ADMIN_USERNAME
                )

                good_pass = hmac.compare_digest(
                    data.get("password", ""),
                    ADMIN_PASSWORD
                )

                if good_user and good_pass:
                    token = make_session(ADMIN_USERNAME)

                    self.redirect(
                        "/dashboard",
                        [(
                            "Set-Cookie",
                            f"leadpilot_session={token}; Path=/; HttpOnly; SameSite=Lax"
                        )]
                    )
                else:
                    self.send_bytes(
                        LOGIN.replace(
                            "__ERROR__",
                            "Incorrect username or password."
                        ).encode(),
                        401
                    )

                return

            if p == "/businesses":
                if not logged_in(self.headers):
                    self.redirect("/login")
                    return

                form = self.read_form()
                business_id = create_business(
                    form.get("name", ""),
                    form.get("services", ""),
                    form.get("service_area", ""),
                    form.get("email", ""),
                    form.get("alert_phone", "")
                )
                self.redirect(f"/businesses?created={business_id}")
                return

            if p == "/recruiting":
                if not logged_in(self.headers):
                    self.redirect("/login")
                    return
                form = self.read_form()
                create_provider_prospect(
                    form.get("business_name", ""),
                    form.get("service", ""),
                    city=form.get("city", ""),
                    county=form.get("county", ""),
                    zip_code=form.get("zip", ""),
                    contact_name=form.get("contact_name", ""),
                    phone=form.get("phone", ""),
                    email=form.get("email", ""),
                    website=form.get("website", ""),
                    notes=form.get("notes", "")
                )
                self.redirect("/recruiting")
                return

            if p == "/recruiting/status":
                if not logged_in(self.headers):
                    self.redirect("/login")
                    return
                form = self.read_form()
                try:
                    prospect_id = int(form.get("prospect_id", "0"))
                except Exception:
                    prospect_id = 0
                update_provider_prospect_status(
                    prospect_id,
                    form.get("status", "Prospect")
                )
                self.redirect("/recruiting")
                return

            if p == "/settings":
                if not logged_in(self.headers):
                    self.redirect("/login")
                    return

                form = self.read_form()
                try:
                    business_id = int(query.get("business", [BUSINESS_ID])[0])
                except Exception:
                    business_id = BUSINESS_ID

                save_business_settings(
                    form.get("name", ""), form.get("services", ""),
                    form.get("service_area", ""), form.get("email", ""),
                    form.get("alert_phone", ""),
                    routing_enabled=form.get("routing_enabled", "1"),
                    routing_priority=form.get("routing_priority", "0"),
                    daily_lead_cap=form.get("daily_lead_cap", "0"),
                    verification_status=form.get("verification_status", "Pending"),
                    test_business=form.get("test_business", "0"),
                    legal_business_name=form.get("legal_business_name", ""),
                    dba_name=form.get("dba_name", ""),
                    owner_contact_name=form.get("owner_contact_name", ""),
                    business_phone=form.get("business_phone", ""),
                    business_address=form.get("business_address", ""),
                    license_number=form.get("license_number", ""),
                    license_type=form.get("license_type", ""),
                    insurance_provider=form.get("insurance_provider", ""),
                    insurance_expiration=form.get("insurance_expiration", ""),
                    business_registration=form.get("business_registration", ""),
                    identity_verified=form.get("identity_verified", "0"),
                    license_verified=form.get("license_verified", "0"),
                    license_active_verified=form.get("license_active_verified", "0"),
                    insurance_verified=form.get("insurance_verified", "0"),
                    registration_verified=form.get("registration_verified", "0"),
                    terms_accepted=form.get("terms_accepted", "0"),
                    business_id=business_id
                )
                self.redirect(f"/settings?business={business_id}&saved=1")
                return

            data = self.read_json()

            if p == "/api/chat":
                marketplace_mode = bool(data.get("marketplace_mode"))
                try:
                    business_id = int(data.get("business_id"))
                except Exception:
                    business_id = BUSINESS_ID

                if marketplace_mode or business_id == 0:
                    out = marketplace_reply(
                        data.get("message", ""),
                        data.get("context") or {}
                    )
                else:
                    out = assistant_reply(
                        data.get("message", ""),
                        data.get("context") or {},
                        business_id=business_id
                    )

                self.send_bytes(
                    json.dumps(out).encode(),
                    content_type="application/json"
                )

                return

            if p == "/api/leads":
                try:
                    business_id = int(data.get("business_id"))
                except Exception:
                    business_id = BUSINESS_ID

                if business_id <= 0:
                    self.send_bytes(
                        json.dumps({"error":"no matching business selected"}).encode(),
                        400,
                        "application/json"
                    )
                    return

                selected_business = get_business_settings(business_id)
                if not business_can_receive_leads(selected_business):
                    self.send_bytes(
                        json.dumps({
                            "error":"business is not currently eligible to receive leads",
                            "verification_status": effective_verification_status(selected_business)
                        }).encode(),
                        403,
                        "application/json"
                    )
                    return

                con = db()
                now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

                # Always classify on the server from the customer's actual message.
                # This prevents blank/default form fields from turning an HVAC,
                # plumbing, electrical, or roofing lead into "General Repair".
                message = data.get("message") or ""
                detected_service, detected_urgency = classify(message)

                supplied_service = (data.get("service") or "").strip()
                supplied_urgency = (data.get("urgency") or "").strip()

                valid_services = {"HVAC", "Plumbing", "Electrical", "Roofing", "General Repair"}
                valid_urgencies = {"Normal", "High", "Emergency"}

                service = supplied_service if supplied_service in valid_services else detected_service
                urgency = supplied_urgency if supplied_urgency in valid_urgencies else detected_urgency

                qualification = qualify_lead(
                    data.get("name"),
                    data.get("phone"),
                    data.get("email"),
                    data.get("zip"),
                    service,
                    urgency,
                    message
                )

                if USE_POSTGRES:
                    cur = execute(
                        con,
                        """INSERT INTO leads
                        (business_id,created_at,name,phone,email,zip,service,urgency,message,status,lead_score,qualification,recommended_action)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                        RETURNING id""",
                        (
                            business_id,
                            now,
                            data.get("name"),
                            data.get("phone"),
                            data.get("email"),
                            data.get("zip"),
                            service,
                            urgency,
                            message,
                            "New",
                            qualification["lead_score"],
                            qualification["qualification"],
                            qualification["recommended_action"]
                        )
                    )

                    lead_id = cur.fetchone()["id"]

                else:
                    cur = execute(
                        con,
                        """INSERT INTO leads
                        (business_id,created_at,name,phone,email,zip,service,urgency,message,status,lead_score,qualification,recommended_action)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            business_id,
                            now,
                            data.get("name"),
                            data.get("phone"),
                            data.get("email"),
                            data.get("zip"),
                            service,
                            urgency,
                            message,
                            "New",
                            qualification["lead_score"],
                            qualification["qualification"],
                            qualification["recommended_action"]
                        )
                    )

                    lead_id = cur.lastrowid

                con.commit()
                con.close()

                # Notify the business immediately when LeadPilot marks the lead Hot.
                send_hot_lead_sms(
                    lead_id,
                    data.get("name"),
                    data.get("phone"),
                    service,
                    urgency,
                    message,
                    qualification,
                    business_id=business_id
                )

                self.send_bytes(
                    json.dumps({
                        "ok": True,
                        "id": lead_id,
                        "lead_score": qualification["lead_score"],
                        "qualification": qualification["qualification"],
                        "service": service,
                        "urgency": urgency
                    }).encode(),
                    content_type="application/json"
                )

                return

            if p.startswith("/api/leads/") and p.endswith("/status"):

                if not logged_in(self.headers):
                    self.send_bytes(
                        b'{"error":"unauthorized"}',
                        401,
                        "application/json"
                    )
                    return

                parts = p.strip("/").split("/")
                lead_id = int(parts[2])
                status = data.get("status", "")
                try:
                    business_id = int(query.get("business", [BUSINESS_ID])[0])
                except Exception:
                    business_id = BUSINESS_ID

                if status not in ["New", "Contacted", "Booked", "Closed"]:
                    self.send_bytes(
                        b'{"error":"bad status"}',
                        400,
                        "application/json"
                    )
                    return

                con = db()

                cur = execute(
                    con,
                    "UPDATE leads SET status=? WHERE id=? AND business_id=?",
                    (status, lead_id, business_id)
                )

                con.commit()
                changed = cur.rowcount
                con.close()

                if not changed:
                    self.send_bytes(
                        b'{"error":"lead not found"}',
                        404,
                        "application/json"
                    )
                    return

                self.send_bytes(
                    json.dumps({
                        "ok": True,
                        "id": lead_id,
                        "status": status
                    }).encode(),
                    content_type="application/json"
                )

                return

            self.send_bytes(
                b'{"error":"not found"}',
                404,
                "application/json"
            )

        except Exception as e:
            print("ERROR:", repr(e))

            self.send_bytes(
                json.dumps({"error":"server error"}).encode(),
                500,
                "application/json"
            )

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))

if __name__ == "__main__":
    init_db()

# Start automatic lead-chasing reminders.
if os.environ.get("LEAD_CHASE_WORKER", "1") == "1":
    threading.Thread(target=lead_chase_worker, daemon=True).start()

    print(
        "LeadPilot AI running on "
        f"http://{HOST}:{PORT} using "
        f"{'Postgres' if USE_POSTGRES else 'SQLite'}"
    )

    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
