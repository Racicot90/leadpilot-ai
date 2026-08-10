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
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
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
                status TEXT DEFAULT 'Waiting',
                matched_business_id INTEGER DEFAULT 0,
                notified_at TEXT DEFAULT ''
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
                notes TEXT DEFAULT '',
                business_id INTEGER DEFAULT 0
            )
        """)
        execute(con, """
            CREATE TABLE IF NOT EXISTS sms_delivery_log(
                id BIGSERIAL PRIMARY KEY,
                created_at TEXT NOT NULL,
                business_id INTEGER DEFAULT 0,
                lead_id INTEGER DEFAULT 0,
                waitlist_id INTEGER DEFAULT 0,
                recipient TEXT DEFAULT '',
                message_type TEXT DEFAULT '',
                status TEXT DEFAULT '',
                error TEXT DEFAULT ''
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
                status TEXT DEFAULT 'Waiting',
                matched_business_id INTEGER DEFAULT 0,
                notified_at TEXT DEFAULT ''
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
                notes TEXT DEFAULT '',
                business_id INTEGER DEFAULT 0
            )
        """)
        execute(con, """
            CREATE TABLE IF NOT EXISTS sms_delivery_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                business_id INTEGER DEFAULT 0,
                lead_id INTEGER DEFAULT 0,
                waitlist_id INTEGER DEFAULT 0,
                recipient TEXT DEFAULT '',
                message_type TEXT DEFAULT '',
                status TEXT DEFAULT '',
                error TEXT DEFAULT ''
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
        execute(con, "ALTER TABLE provider_prospects ADD COLUMN IF NOT EXISTS business_id INTEGER DEFAULT 0")
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

    if USE_POSTGRES:
        try:
            execute(con, "ALTER TABLE coverage_waitlist ADD COLUMN IF NOT EXISTS matched_business_id INTEGER DEFAULT 0")
            execute(con, "ALTER TABLE coverage_waitlist ADD COLUMN IF NOT EXISTS notified_at TEXT DEFAULT ''")
        except Exception:
            pass
    else:
        for stmt in [
            "ALTER TABLE coverage_waitlist ADD COLUMN matched_business_id INTEGER DEFAULT 0",
            "ALTER TABLE coverage_waitlist ADD COLUMN notified_at TEXT DEFAULT ''",
        ]:
            try:
                execute(con, stmt)
            except Exception:
                pass

    # V9 — contractor lead pipeline + opportunity value
    try:
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS estimated_value_low REAL DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS estimated_value_high REAL DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS final_job_value REAL DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS outcome_note TEXT DEFAULT ''")
    except Exception:
        for stmt in [
            "ALTER TABLE leads ADD COLUMN estimated_value_low REAL DEFAULT 0",
            "ALTER TABLE leads ADD COLUMN estimated_value_high REAL DEFAULT 0",
            "ALTER TABLE leads ADD COLUMN final_job_value REAL DEFAULT 0",
            "ALTER TABLE leads ADD COLUMN outcome_note TEXT DEFAULT ''"
        ]:
            try:
                execute(con, stmt)
            except Exception:
                pass

    execute(con, """
        CREATE TABLE IF NOT EXISTS service_pricing(
            business_id INTEGER NOT NULL,
            service TEXT NOT NULL,
            low_value REAL DEFAULT 0,
            high_value REAL DEFAULT 0,
            PRIMARY KEY (business_id, service)
        )
    """)

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
            (service_area or "").strip(), (email or "").strip(), normalize_phone(alert_phone),
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


def create_business(name, services="", service_area="", email="", alert_phone="", routing_enabled=1, verification_status="Pending", test_business=0):
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
            normalize_phone(alert_phone),
            1 if routing_enabled else 0, 0, 0, "", "",
            verification_status if verification_status in ("Pending","Verified","Rejected","Expired") else "Pending",
            1 if test_business else 0
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

/* V13 visual polish - cosmetic only */
html{{scroll-behavior:smooth}}
body{{background:radial-gradient(circle at top right,rgba(52,72,197,.07),transparent 28%),linear-gradient(180deg,#f8faff 0,#f3f6fa 380px,#f4f7fb 100%)}}
.wrap{{max-width:1040px;padding:22px 18px 40px}}
header{{background:rgba(255,255,255,.92);border:1px solid #e2e8f0;border-radius:18px;padding:16px 18px;box-shadow:0 8px 30px rgba(20,32,51,.07)}}
header h1{{font-size:28px;letter-spacing:-.035em}}
header h1:before{{content:"LP";display:inline-grid;place-items:center;width:38px;height:38px;margin-right:10px;border-radius:11px;background:linear-gradient(145deg,#172033,#3448c5);color:#fff;font-size:13px;vertical-align:4px;box-shadow:0 7px 16px rgba(52,72,197,.25)}}
.sub{{font-size:13px;margin-left:52px}}
.toplinks{{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px}}
.toplinks a{{margin:0;padding:8px 10px;border-radius:9px;color:#475467}}
.toplinks a:hover{{background:#f2f4f7;color:#172033}}
.priority-card{{position:relative;overflow:hidden;border:1px solid rgba(255,255,255,.08);background:radial-gradient(circle at 92% 0,rgba(78,97,180,.35),transparent 32%),linear-gradient(135deg,#101827 0%,#1c2941 58%,#243453 100%);box-shadow:0 18px 42px rgba(20,32,51,.18)}}
.priority-card:after{{content:"";position:absolute;width:180px;height:180px;right:-75px;bottom:-100px;border-radius:50%;border:28px solid rgba(255,255,255,.035);pointer-events:none}}
.priority-kicker{{display:inline-block;padding:6px 9px;border-radius:999px;background:rgba(255,214,107,.10);border:1px solid rgba(255,214,107,.18)}}
.priority-name{{letter-spacing:-.03em}}
.priority-value strong{{color:#fff}}
.priority-facts div{{border:1px solid rgba(255,255,255,.06)}}
.priority-call,.priority-contact,.priority-status-btn{{transition:transform .15s ease,background .15s ease}}
.priority-call:active,.priority-contact:active,.priority-status-btn:active{{transform:scale(.98)}}
.money-grid{{gap:12px}}
.money-card{{border:1px solid #e2e8f0;box-shadow:0 8px 24px rgba(20,32,51,.065)}}
.money-card strong{{letter-spacing:-.035em}}
.money-card.risk{{border-top:3px solid #f79009;background:linear-gradient(180deg,#fff8f1,#fff4ed)}}
.money-card.risk strong{{color:#b54708}}
.money-card:first-child{{background:linear-gradient(145deg,#172033,#22314d);border-color:#263754}}
.stat{{border:1px solid #e6eaf0;box-shadow:0 5px 18px rgba(20,32,51,.045)}}
.attention{{border:1px solid #e6eaf0;box-shadow:0 10px 30px rgba(20,32,51,.07)}}
.attention-title h2:before{{content:"!";display:inline-grid;place-items:center;width:26px;height:26px;margin-right:7px;border-radius:8px;background:#fff1f0;color:#d92d20;font-size:15px;vertical-align:2px}}
.folder{{cursor:pointer;transition:transform .15s ease,box-shadow .15s ease}}
.folder:hover{{transform:translateY(-1px);box-shadow:0 7px 18px rgba(20,32,51,.08)}}
.folder.active{{background:linear-gradient(145deg,#172033,#273752);box-shadow:0 8px 18px rgba(20,32,51,.16)}}
.folder[data-folder="Estimate"] b{{color:#b54708}}
.folder[data-folder="Won"] b{{color:#067647}}
.folder[data-folder="Lost"] b{{color:#b42318}}
.folder.active b{{color:#fff}}
.folder-heading{{background:rgba(255,255,255,.62);border:1px solid #e6eaf0;border-radius:12px;padding:10px 12px}}
.lead-card{{border:1px solid #e6eaf0;box-shadow:0 8px 26px rgba(20,32,51,.065);transition:transform .16s ease,box-shadow .16s ease}}
.lead-card:hover{{transform:translateY(-2px);box-shadow:0 12px 32px rgba(20,32,51,.095)}}
.opportunity{{background:linear-gradient(180deg,#f2fdf6,#ecfdf3);border-color:#c8f1d8}}
.message{{background:#f8fafc;border-left-color:#3448c5}}
.ai-box{{background:linear-gradient(180deg,#f2f6ff,#eef4ff);border-color:#d8e2ff}}
.action,.status-btn,.won-input button{{cursor:pointer;transition:transform .15s ease}}
.action:active,.status-btn:active,.won-input button:active{{transform:scale(.98)}}
@media(max-width:700px){{
.wrap{{padding:10px 10px 32px}}
header{{padding:14px;margin-bottom:14px}}
header h1{{font-size:24px}}
header h1:before{{width:34px;height:34px}}
.sub{{margin-left:46px}}
.toplinks{{justify-content:flex-start;margin-top:12px}}
.toplinks a{{font-size:12px;background:#f7f8fa}}
.priority-card{{padding:17px;border-radius:18px}}
.money-card{{padding:17px}}
.attention{{padding:15px}}
.lead-card{{padding:16px}}
}}

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
        # IMPORTANT: Do NOT add the state ("Florida") to city/county/ZIP aliases.
        # Every Florida location shares that state token, which would make a
        # Miami-only provider appear to serve Lake City, Tampa, Orlando, etc.
        for item in [raw, city, county, postcode]:
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
        fallback_aliases = sorted(canonical_place_aliases(raw))
        if zip_match:
            fallback_aliases.extend(sorted(canonical_place_aliases(zip_match.group(0))))

        fallback = {
            "input": raw,
            "city": "",
            "county": "",
            "postcode": zip_match.group(0) if zip_match else "",
            "state": "Florida",
            "aliases": sorted(set(fallback_aliases)),
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


def canonical_place_aliases(value):
    norm = normalize_place(value)
    aliases = set()
    if not norm:
        return aliases

    aliases.add(norm)
    if norm.endswith(" county"):
        bare = norm[:-7].strip()
        if bare:
            aliases.add(bare)
    return aliases


def resolved_location_aliases(resolved):
    aliases = set()
    if not resolved:
        return aliases

    for value in [
        resolved.get("input", ""),
        resolved.get("city", ""),
        resolved.get("county", ""),
        resolved.get("postcode", ""),
    ]:
        aliases.update(canonical_place_aliases(value))

    for value in resolved.get("aliases") or []:
        aliases.update(canonical_place_aliases(value))

    return {a for a in aliases if a}


def _normalize_service_name(value):
    s = (value or "").strip().lower()
    aliases = {
        "hvac repair": "hvac",
        "air conditioning": "hvac",
        "air conditioner": "hvac",
        "ac repair": "hvac",
        "a/c": "hvac",
        "plumber": "plumbing",
        "plumbing repair": "plumbing",
        "roofer": "roofing",
        "roof repair": "roofing",
        "electrician": "electrical",
        "electrical repair": "electrical",
    }
    return aliases.get(s, s)


def business_supports_service(business, service):
    raw = ""
    try:
        raw = business.get("services", "") or ""
    except AttributeError:
        raw = business["services"] or ""

    offered = {
        _normalize_service_name(s)
        for s in raw.split(",")
        if s.strip()
    }
    requested = _normalize_service_name(service)

    if not offered or not requested or requested == "general repair":
        return False

    return requested in offered


def business_service_area_aliases(business):
    """
    Expand each explicitly configured Florida service-area token into safe
    city/county/ZIP aliases.

    "Florida" is treated as statewide ONLY when the business owner explicitly
    entered Florida/statewide in Service area.
    """
    service_area = ""
    try:
        service_area = business.get("service_area", "") or ""
    except AttributeError:
        service_area = business["service_area"] or ""

    raw_parts = [
        p.strip()
        for p in re.split(r"[,;\n]+", service_area)
        if p.strip()
    ]

    aliases = set()

    for part in raw_parts:
        normalized = normalize_place(part)

        # Explicit statewide opt-in only.
        if normalized in ("florida", "statewide", "all florida", "florida statewide"):
            aliases.add("florida statewide")
            continue

        aliases.update(canonical_place_aliases(part))

        resolved_part = resolve_florida_location(part)
        if resolved_part:
            # resolved_location_aliases intentionally excludes the state token.
            aliases.update(resolved_location_aliases(resolved_part))

    # Never allow a generic "florida" token to leak in from geocoding.
    aliases.discard("florida")
    return {a for a in aliases if a}


def business_serves_location(business, resolved_location):
    """
    Strict geographic eligibility.

    Rules:
      - Explicit "Florida"/statewide configuration matches anywhere in Florida.
      - Otherwise, provider and customer must share a canonical city, county,
        or ZIP alias.
      - No fuzzy substring fallback.
    """
    if not resolved_location:
        return False

    configured_aliases = business_service_area_aliases(business)
    if not configured_aliases:
        return False

    if "florida statewide" in configured_aliases:
        return True

    customer_aliases = resolved_location_aliases(resolved_location)
    customer_aliases.discard("florida")

    if not customer_aliases:
        return False

    return bool(configured_aliases.intersection(customer_aliases))



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
    LeadPilot Intelligent Routing V7 — strict service + canonical Florida territory matching.

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
            (name or "").strip(), normalize_phone(phone),
            (email or "").strip(), (issue or "").strip(), "Waiting"
        )
    )
    con.commit()
    con.close()


def reconcile_coverage_waitlist(limit=200):
    """
    Revalidate both Waiting and Provider Available records using current strict
    service + geography rules.

    This repairs historical bad matches created by older routing logic.
    """
    con = db()
    rows = execute(
        con,
        """SELECT *
           FROM coverage_waitlist
           WHERE status IN ('Waiting','Provider Available')
           ORDER BY id
           LIMIT ?""",
        (limit,)
    ).fetchall()
    con.close()

    changed = 0

    for r in rows:
        service = (r["service"] or "General Repair").strip()

        # Prefer the original human-entered location/city/county before ZIP.
        # All resolve to canonical aliases under the strict matcher.
        location_value = (
            (r["location"] or "").strip()
            or (r["city"] or "").strip()
            or (r["county"] or "").strip()
            or (r["zip"] or "").strip()
        )
        if not location_value:
            continue

        matched, _resolved = match_business_for_lead(
            service,
            location_value,
            reserve=False
        )

        current_status = (r["status"] or "Waiting").strip()
        current_business_id = int(r["matched_business_id"] or 0)

        # No valid provider now: bad/expired old match returns to Waiting.
        if not matched:
            if current_status == "Provider Available":
                con = db()
                cur = execute(
                    con,
                    """UPDATE coverage_waitlist
                       SET status='Waiting', matched_business_id=0
                       WHERE id=?""",
                    (int(r["id"]),)
                )
                con.commit()
                changed += int(bool(cur.rowcount))
                con.close()
            continue

        new_business_id = int(matched["id"])

        # Valid provider exists: mark/repair the match.
        if current_status != "Provider Available" or current_business_id != new_business_id:
            con = db()
            cur = execute(
                con,
                """UPDATE coverage_waitlist
                   SET status='Provider Available', matched_business_id=?
                   WHERE id=?""",
                (new_business_id, int(r["id"]))
            )
            con.commit()
            changed += int(bool(cur.rowcount))
            con.close()

    return changed



def sms_status_html():
    con = db()
    rows = execute(
        con,
        """SELECT * FROM sms_delivery_log
           ORDER BY id DESC
           LIMIT 100"""
    ).fetchall()
    con.close()

    sent = sum(1 for r in rows if (r["status"] or "") == "Sent")
    failed = sum(1 for r in rows if (r["status"] or "") == "Failed")

    cards = ""
    for r in rows:
        status = (r["status"] or "Unknown").strip()
        cls = "sent" if status == "Sent" else "failed"
        cards += f"""
        <div class="sms-card">
          <div class="sms-top">
            <strong>{html.escape(r["message_type"] or "SMS")}</strong>
            <span class="{cls}">{html.escape(status)}</span>
          </div>
          <div>{html.escape(r["recipient"] or "—")}</div>
          <small>{html.escape(r["created_at"] or "")}</small>
          {f'<div class="err">{html.escape(r["error"])}</div>' if r["error"] else ''}
        </div>
        """

    if not cards:
        cards = '<div class="sms-card">No SMS attempts logged yet.</div>'

    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot SMS Status</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}
.wrap{{max-width:900px;margin:auto;padding:18px}}
.nav{{display:flex;gap:14px;flex-wrap:wrap;margin:12px 0 20px}}
a{{color:#3448c5;font-weight:800;text-decoration:none}}
.stats{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 0}}
.stat,.sms-card{{background:#fff;border-radius:16px;padding:17px;box-shadow:0 5px 18px rgba(0,0,0,.05)}}
.stat strong{{display:block;font-size:34px;margin-top:6px}}
.sms-card{{margin-bottom:10px}}
.sms-top{{display:flex;justify-content:space-between;gap:10px}}
.sent{{color:#087443;font-weight:900}}
.failed{{color:#b42318;font-weight:900}}
small{{color:#667085;display:block;margin-top:5px}}
.err{{margin-top:9px;background:#fff1f0;color:#b42318;padding:10px;border-radius:9px;font-size:12px}}
</style>
</head>
<body><div class="wrap">
<div class="nav">
<a href="/dashboard">Dashboard</a>
<a href="/coverage-demand">Coverage Demand</a> <a href="/sms-status">SMS Status</a>
<a href="/recruiting">Provider Recruiting</a>
<a href="/businesses">Businesses</a>
<a href="/logout">Log out</a>
</div>
<h1>SMS Status</h1>
<p>Beta-safe delivery log. Failed messages now show Twilio's actual error code and message when available.</p>
<div class="stats">
<div class="stat">Sent<strong>{sent}</strong></div>
<div class="stat">Failed<strong>{failed}</strong></div>
</div>
{cards}
</div></body></html>"""


def coverage_demand_html(message=""):
    """Admin view of unmet demand, ranked to show where provider recruiting matters most."""
    reconciled = reconcile_coverage_waitlist(limit=100)
    if reconciled and not message:
        message = f"{reconciled} waiting request(s) matched to newly available coverage."

    con = db()
    rows = execute(con, """SELECT * FROM coverage_waitlist ORDER BY id DESC""").fetchall()
    con.close()

    groups = {}
    waiting_total = 0
    ready_to_notify = 0
    notified_total = 0
    for r in rows:
        status = (r["status"] or "Waiting").strip()
        if status == "Provider Available":
            ready_to_notify += 1
        elif status == "Notified":
            notified_total += 1
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
        # Carry normalized geography into the recruiting form.
        sample = next(
            (
                r for r in rows
                if (r["status"] or "Waiting").strip() == "Waiting"
                and (r["service"] or "General Repair").strip() == g["service"]
                and ((r["county"] or r["city"] or r["location"] or "Unknown area").strip() == g["area"])
            ),
            None
        )
        recruit_url = (
            "/recruiting?service=" + quote(g["service"]) +
            "&city=" + quote((sample["city"] if sample else g["city"]) or "") +
            "&county=" + quote((sample["county"] if sample else g["county"]) or "") +
            "&zip=" + quote((sample["zip"] if sample else "") or "") +
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
        contact = (display_phone(r["phone"]) if (r["phone"] or "").strip() else (r["email"] or "—").strip())
        status = (r["status"] or "Waiting").strip()
        business_id = int(r["matched_business_id"] or 0) if "matched_business_id" in r.keys() else 0
        provider_name = ""
        if business_id:
            provider_name = get_business_settings(business_id).get("name") or ""

        notify_action = ""
        if status == "Provider Available":
            if (r["phone"] or "").strip():
                notify_action = f"""
                <form method="POST" action="/coverage-demand/notify">
                  <input type="hidden" name="waitlist_id" value="{r['id']}">
                  <button class="notify-btn" type="submit">Notify customer</button>
                </form>
                """
            else:
                notify_action = '<span class="email-note">Ready to notify — email delivery not configured yet.</span>'

        provider_line = f"<span>Matched provider: {html.escape(provider_name)}</span>" if provider_name else ""
        request_rows += f"""
        <div class="request">
          <div>
            <strong>{html.escape(r['service'] or 'General Repair')}</strong>
            <span>{html.escape(place)} · {html.escape(r['zip'] or '')}</span>
            <span>{html.escape(r['created_at'] or '')} · {html.escape(status)}</span>
            {provider_line}
          </div>
          <div class="contact">
            {html.escape(r['name'] or 'Unnamed')}
            <span>{html.escape(contact)}</span>
            {notify_action}
          </div>
        </div>
        """

    opportunity = (f"Top recruiting opportunity: {top['service']} in {top['area']} — {top['count']} waiting customer(s)." if top else "LeadPilot will rank recruiting opportunities as waitlist demand comes in.")
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>LeadPilot Coverage Demand</title><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}.wrap{{max-width:900px;margin:auto;padding:18px}}a{{color:#3448c5;text-decoration:none;font-weight:800}}h1{{margin:8px 0 4px}}.sub{{color:#667085}}.nav{{display:flex;gap:16px;flex-wrap:wrap;margin:14px 0 20px}}.summary{{background:#172033;color:#fff;border-radius:18px;padding:20px;margin-bottom:16px}}.summary span{{opacity:.75;font-size:13px}}.summary strong{{display:block;font-size:36px;margin:4px 0}}.summary-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.summary p{{margin:8px 0 0;line-height:1.4}}.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.demand-card{{background:#fff;border-radius:16px;padding:18px;display:flex;justify-content:space-between;gap:14px;align-items:center;box-shadow:0 5px 18px rgba(0,0,0,.05)}}.demand-card.hot{{border:2px solid #fda29b}}.demand-card.warm{{border:2px solid #fedf89}}.eyebrow{{font-size:11px;text-transform:uppercase;font-weight:900;color:#667085}}h3{{font-size:21px;margin:5px 0}}.demand-card p{{margin:0;color:#667085}}.demand-count{{font-size:32px;font-weight:900;text-align:center;min-width:78px}}.recruit-btn{{display:inline-block;margin-top:12px;background:#172033;color:#fff!important;padding:9px 12px;border-radius:9px;font-size:12px}}.demand-count small{{display:block;font-size:11px;color:#667085}}h2{{margin-top:28px}}.request{{background:#fff;border-radius:14px;padding:14px 16px;margin:9px 0;display:flex;justify-content:space-between;gap:14px;box-shadow:0 4px 14px rgba(0,0,0,.04)}}.request span{{display:block;color:#667085;font-size:12px;margin-top:4px}}.contact{{text-align:right;font-weight:700}}.notify-btn{{margin-top:8px;border:0;border-radius:9px;background:#087443;color:#fff;padding:9px 11px;font-weight:800}}.email-note{{margin-top:8px;color:#93370d!important;font-size:11px!important}}.flash{{margin:12px 0;padding:12px;border-radius:10px;background:#e0e7ff;color:#29339b;font-weight:700}}.empty{{background:#fff;border-radius:14px;padding:22px;color:#667085}}@media(max-width:650px){{.grid{{grid-template-columns:1fr}}.summary-grid{{grid-template-columns:1fr 1fr 1fr}}.request{{display:block}}.contact{{text-align:left;margin-top:10px}}}}
</style></head><body><div class="wrap"><div class="nav"><a href="/dashboard">Dashboard</a><a href="/recruiting">Provider Recruiting</a><a href="/businesses">Businesses</a><a href="/">Customer page</a><a href="/logout">Log out</a></div><h1>Coverage Demand</h1><div class="sub">Live unmet customer demand tells LeadPilot where to recruit verified providers next.</div>{"" if APP_BASE_URL else '<div class="flash">Beta setup: add APP_BASE_URL in Render so SMS notifications include a clickable LeadPilot link.</div>'}{f'<div class="flash">{html.escape(message)}</div>' if message else ''}<div class="summary">
<div class="summary-grid">
<div><span>Still waiting</span><strong>{waiting_total}</strong></div>
<div><span>Ready to notify</span><strong>{ready_to_notify}</strong></div>
<div><span>Notified</span><strong>{notified_total}</strong></div>
</div>
<p>{html.escape(opportunity)}</p>
</div><div class="grid">{demand_cards}</div><h2>Recent coverage requests</h2>{request_rows or '<div class="empty">No requests yet.</div>'}</div></body></html>"""



PROSPECT_STATUSES = ["Prospect", "Contacted", "Interested", "Verification", "Approved", "Passed"]


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


def _service_area_from_prospect(prospect):
    parts = []
    for value in [
        prospect["city"] if "city" in prospect.keys() else "",
        prospect["county"] if "county" in prospect.keys() else "",
        prospect["zip"] if "zip" in prospect.keys() else ""
    ]:
        value = (value or "").strip()
        if value and value.lower() not in [x.lower() for x in parts]:
            parts.append(value)
    return ", ".join(parts)


def ensure_prospect_business(prospect_id):
    """Create a real, blocked business record when recruiting reaches Verification."""
    con = db()
    prospect = execute(
        con, "SELECT * FROM provider_prospects WHERE id=?", (prospect_id,)
    ).fetchone()
    con.close()
    if not prospect:
        return 0

    existing_id = int(prospect["business_id"] or 0) if "business_id" in prospect.keys() else 0
    if existing_id:
        return existing_id

    service_area = _service_area_from_prospect(prospect)
    business_id = create_business(
        prospect["business_name"],
        services=prospect["service"],
        service_area=service_area,
        email=prospect["email"] or "",
        alert_phone=prospect["phone"] or "",
        routing_enabled=0,
        verification_status="Pending",
        test_business=0
    )

    con = db()
    execute(
        con,
        "UPDATE provider_prospects SET business_id=?, updated_at=? WHERE id=?",
        (business_id, datetime.utcnow().strftime("%Y-%m-%d %H:%M"), prospect_id)
    )
    con.commit()
    con.close()
    return business_id


def provider_verification_ready(business):
    """Strict beta gate before a recruited provider can be activated."""
    if not business:
        return False, ["Missing business record"]

    missing = []
    if effective_verification_status(business) != "Verified":
        missing.append("Verification status must be Verified")

    checks = [
        ("identity_verified", "Business identity"),
        ("license_verified", "Trade license"),
        ("license_active_verified", "Active license"),
        ("insurance_verified", "Insurance"),
        ("registration_verified", "Business registration"),
        ("terms_accepted", "Provider terms"),
    ]
    for key, label in checks:
        if int(business.get(key) or 0) != 1:
            missing.append(label)

    if not (business.get("insurance_expiration") or "").strip():
        missing.append("Insurance expiration date")

    return len(missing) == 0, missing


def update_provider_prospect_status(prospect_id, status):
    if status not in PROSPECT_STATUSES:
        return False

    # Reaching Verification automatically creates a real business record,
    # but routing stays OFF until activation.
    if status == "Verification":
        ensure_prospect_business(prospect_id)

    # Approved cannot be used to bypass verification.
    if status == "Approved":
        business_id = ensure_prospect_business(prospect_id)
        business = get_business_settings(business_id) if business_id else None
        ready, _missing = provider_verification_ready(business)
        if not ready:
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


def mark_waitlist_provider_available(business_id):
    """
    Connect historical unmet demand to a newly activated provider.
    We do NOT auto-send the customer message here; this creates a reviewable
    'Provider Available' notification queue.
    """
    business = get_business_settings(business_id)
    if not business_can_receive_leads(business):
        return 0

    con = db()
    rows = execute(
        con,
        """SELECT * FROM coverage_waitlist
           WHERE status='Waiting'
           ORDER BY id"""
    ).fetchall()

    matched = 0
    for r in rows:
        service = (r["service"] or "General Repair").strip()
        if not business_supports_service(business, service):
            continue

        location_value = (
            (r["zip"] or "").strip()
            or (r["city"] or "").strip()
            or (r["location"] or "").strip()
        )
        resolved = resolve_florida_location(location_value)
        if not resolved:
            continue

        if not business_serves_location(business, resolved):
            continue

        execute(
            con,
            """UPDATE coverage_waitlist
               SET status='Provider Available', matched_business_id=?
               WHERE id=? AND status='Waiting'""",
            (business_id, r["id"])
        )
        matched += 1

    con.commit()
    con.close()
    return matched


def activate_provider_prospect(prospect_id):
    """
    Final activation:
    Approved + fully verified prospect -> Live routable business.
    """
    con = db()
    prospect = execute(
        con, "SELECT * FROM provider_prospects WHERE id=?", (prospect_id,)
    ).fetchone()
    con.close()

    if not prospect:
        return False, "Provider prospect was not found."

    if (prospect["status"] or "").strip() != "Approved":
        return False, "Move the provider to Approved before activation."

    business_id = ensure_prospect_business(prospect_id)
    if not business_id:
        return False, "Could not create the linked business."

    business = get_business_settings(business_id)
    ready, missing = provider_verification_ready(business)
    if not ready:
        return False, "Still needed: " + ", ".join(missing)

    con = db()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    execute(
        con,
        "UPDATE businesses SET routing_enabled=1, verification_status='Verified' WHERE id=?",
        (business_id,)
    )
    execute(
        con,
        "UPDATE provider_prospects SET status='Live', updated_at=? WHERE id=?",
        (now, prospect_id)
    )
    con.commit()
    con.close()

    matched_waiting = mark_waitlist_provider_available(business_id)
    return True, {"business_id": business_id, "waiting_matches": matched_waiting}



def recruiting_pipeline_html(prefill_service="", prefill_city="", prefill_count="", prefill_county="", prefill_zip="", message=""):
    con = db()
    rows = execute(
        con,
        "SELECT * FROM provider_prospects ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    con.close()

    counts = {s: 0 for s in PROSPECT_STATUSES + ["Live"]}
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

        business_id = int(r["business_id"] or 0) if "business_id" in r.keys() else 0
        verification_panel = ""
        activation_panel = ""

        if business_id:
            linked_business = get_business_settings(business_id)
            ready, missing = provider_verification_ready(linked_business)
            effective_status = effective_verification_status(linked_business)
            verification_panel = f"""
              <div class="verification-box">
                <strong>Linked LeadPilot business #{business_id}</strong>
                <span>Verification: {html.escape(effective_status)}</span>
                <span>Routing: {"Enabled" if linked_business.get("routing_enabled") else "Blocked until activation"}</span>
                <a href="/settings?business={business_id}">Open verification settings →</a>
              </div>
            """
            if status == "Approved" and ready:
                activation_panel = f"""
                  <form method="POST" action="/recruiting/activate">
                    <input type="hidden" name="prospect_id" value="{r['id']}">
                    <button class="activate-btn" type="submit">✓ Activate Provider</button>
                  </form>
                """
            elif status == "Approved" and not ready:
                activation_panel = '<div class="not-ready">Activation locked — finish verification first.</div>'
            elif status not in ("Live", "Passed"):
                activation_panel = '<div class="not-ready">Complete the pipeline through Approved before activation.</div>'

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
          {verification_panel}
          {activation_panel}
          {"<div class='live-box'>🟢 LIVE — LeadPilot Verified and eligible for routing</div>" if status == "Live" else ""}
          {"" if status == "Live" else f"""
          <form method="POST" action="/recruiting/status">
            <input type="hidden" name="prospect_id" value="{r['id']}">
            <label>Pipeline stage</label>
            <div class="status-row">
              <select name="status">{status_options}</select>
              <button type="submit">Update</button>
            </div>
          </form>
          """}
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
.verification-box{{margin-top:12px;padding:12px;background:#f8fafc;border-radius:10px}}
.verification-box span{{display:block;color:#667085;font-size:12px;margin-top:4px}}
.verification-box a{{display:inline-block;margin-top:8px;font-size:12px}}
.activate-btn{{width:100%;margin-top:10px;background:#087443}}
.not-ready{{margin-top:10px;padding:10px;border-radius:9px;background:#fff0c2;color:#93370d;font-size:12px;font-weight:800}}
.live-box{{margin-top:10px;padding:10px;border-radius:9px;background:#dcfae6;color:#05603a;font-size:12px;font-weight:800}}
.flash{{margin-bottom:14px;padding:12px;border-radius:10px;background:#e0e7ff;color:#29339b;font-weight:700}}
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
<a href="/coverage-demand">Coverage Demand</a> <a href="/sms-status">SMS Status</a> <a href="/recruiting">Provider Recruiting</a>
<a href="/businesses">Businesses</a>
<a href="/">Customer page</a>
<a href="/logout">Log out</a>
</div>

<h1>Provider Recruiting</h1>
<div class="sub">Turn unmet customer demand into a provider recruiting pipeline.</div>
{"" if APP_BASE_URL else '<div class="flash">Beta setup: add APP_BASE_URL in Render so customer/provider SMS messages contain clickable LeadPilot links.</div>'}
{f'<div class="flash">{html.escape(message)}</div>' if message else ''}

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
<div><label>County</label><input name="county" value="{html.escape(prefill_county, quote=True)}"></div>
<div><label>ZIP</label><input name="zip" value="{html.escape(prefill_zip, quote=True)}"></div>
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


def _normalize_marketplace_location_input(text):
    """Strip conversational wrappers so phrases like 'in Lake City' resolve as locations."""
    value = " ".join((text or "").strip().split())
    lower = value.lower()
    prefixes = (
        "i am in ", "i'm in ", "im in ", "we are in ", "we're in ",
        "the job is in ", "job is in ", "it is in ", "it's in ", "its in ",
        "located in ", "location is ", "in ", "near ", "around ", "at "
    )
    for prefix in prefixes:
        if lower.startswith(prefix) and len(value) > len(prefix):
            return value[len(prefix):].strip(" ,.-")
    return value


def _explicit_marketplace_service(message, current_service=""):
    """Return an explicitly named trade without treating symptoms as trade names."""
    msg_lower = (message or "").lower()
    service_words = {
        "Plumbing": [
            "water heater", "hot water heater", "tankless", "plumber", "plumbing",
            "pipe", "toilet", "sink", "faucet", "drain", "sewer",
            "garbage disposal", "septic"
        ],
        "HVAC": [
            "hvac", "air conditioning", "a/c", "ac unit", "my ac", "furnace",
            "heat pump", "central heat", "heating system", "thermostat"
        ],
        "Electrical": [
            "electrician", "electrical", "electric", "outlet", "breaker", "wiring",
            "wire", "run power", "ran power", "power to my", "power to the",
            "power ran", "power run", "panel box", "electrical panel"
        ],
        "Roofing": [
            "roofer", "roofing", "roof", "shingle", "shingles", "flashing", "skylight"
        ]
    }
    for candidate, words in service_words.items():
        if candidate != current_service and any(word in msg_lower for word in words):
            return candidate
    return ""


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

    # Conversation interrupt handling (V18): customers do not always answer
    # the exact question LeadPilot just asked. If they clearly name a different
    # trade while in a no-coverage/waitlist branch, treat that as a NEW service
    # search and reset the old location + notification state.
    interrupted_service = _explicit_marketplace_service(msg, service)
    if interrupted_service and step in (
        "coverage_waitlist_offer", "waitlist_name", "waitlist_phone",
        "waitlist_email", "waitlist_complete", "location"
    ):
        service = interrupted_service
        detected_service, detected_urgency = classify(msg)
        urgency = detected_urgency
        issue = msg
        return {
            "reply": f"Got it — you need {service.lower()} help. What Florida city or ZIP code is the job in?",
            "service": service,
            "urgency": urgency,
            "issue": issue,
            "intake_step": "location",
            "matched_business_id": 0,
            "business_name": "",
            "customer_zip": "",
            "customer_location": "",
            "waitlist_name": "",
            "waitlist_phone": "",
            "waitlist_email": ""
        }

    # Coverage waitlist flow for areas with no current provider.
    if step == "coverage_waitlist_offer":
        # If the customer simply enters another valid Florida city/ZIP, treat it as
        # a new location search rather than forcing them into the waitlist.
        normalized_location = _normalize_marketplace_location_input(msg)
        alternate = resolve_florida_location(normalized_location)
        if alternate and msg_lower not in ("yes", "yeah", "yep", "sure", "ok", "okay"):
            matched, resolved = match_business_for_lead(service, normalized_location)
            customer_location = normalized_location
            customer_zip = (resolved or {}).get("postcode") or _extract_zip(normalized_location)

            if matched:
                matched_business_id = int(matched["id"])
                matched_business_name = matched["name"] or "a local provider"
                place = (resolved or {}).get("display") or normalized_location
                return {
                    "reply": f"I found {matched_business_name}, which covers {place} and offers {service}. What's your name?",
                    "service": service, "urgency": urgency, "issue": issue,
                    "intake_step": "name",
                    "matched_business_id": matched_business_id,
                    "business_name": matched_business_name,
                    "customer_zip": customer_zip,
                    "customer_location": customer_location
                }

            place = (resolved or {}).get("display") or normalized_location
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
                "reply": "No problem. Send another Florida city or ZIP code and I'll check that area.",
                "service": service, "urgency": urgency, "issue": issue,
                "intake_step": "location",
                "matched_business_id": 0, "business_name": "",
                "customer_zip": "",
                "customer_location": "",
                "waitlist_name": "",
                "waitlist_phone": "",
                "waitlist_email": ""
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
    explicit_candidate = _explicit_marketplace_service(msg, service)
    explicit_service_change = bool(explicit_candidate)
    if explicit_service_change:
        switched_service = explicit_candidate

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
    if not matched_business_id and step in ("name", "phone", "email", "details", "ready"):
        step = "location" if service and service != "General Repair" else ""

    if not step:
        service, urgency = classify(msg)
        issue = msg

        if service == "General Repair":
            return {
                "reply": "I want to make sure I send this to the right type of professional. Is this HVAC, plumbing, electrical, roofing, or something else?",
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
        location = _normalize_marketplace_location_input(msg)
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
            if issue and len(issue.strip()) >= 8:
                final_service, final_urgency = classify(issue)
                if final_service != "General Repair":
                    service = final_service
                urgency = final_urgency
                step = "ready"
                reply = (
                    f"Perfect. Your {service.lower()} request is ready for "
                    f"{matched_business_name}. Review the details below and tap Send My Request."
                )
            else:
                step = "details"
                reply = "No problem. Briefly describe what you need fixed or done."
        else:
            parsed = _extract_email(msg)
            if not parsed:
                reply = "That doesn't look like an email address. Try again, or type SKIP."
            else:
                customer_email = parsed
                if issue and len(issue.strip()) >= 8:
                    final_service, final_urgency = classify(issue)
                    if final_service != "General Repair":
                        service = final_service
                    urgency = final_urgency
                    step = "ready"
                    reply = (
                        f"Perfect. Your {service.lower()} request is ready for "
                        f"{matched_business_name}. Review the details below and tap Send My Request."
                    )
                else:
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

        step = "ready"
        reply = (
            f"Got it. Your {service.lower()} request is ready for "
            f"{matched_business_name}. Review the details below and tap Send My Request."
        )

    elif step == "ready":
        reply = f"Your request is ready to send to {matched_business_name}."

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
        "submit_ready": step == "ready"
    }


def classify(text):
    """
    LeadPilot Service Classifier V3.

    Important rule:
    A symptom such as "leak", "broken", or "not working" does NOT identify
    the trade by itself. We classify from the object/system causing the
    problem (roof, pipe, AC, outlet, etc.) and use symptom words only for
    urgency.

    The classifier uses weighted context instead of first-keyword-wins.
    Strong, specific equipment/structure terms outweigh broad words.
    """
    t = " ".join((text or "").lower().replace("-", " ").split())
    padded = f" {t} "

    scores = {
        "Plumbing": 0,
        "HVAC": 0,
        "Electrical": 0,
        "Roofing": 0,
    }

    def hit(phrase):
        return phrase in t

    def add(service, phrases, weight):
        for phrase in phrases:
            if hit(phrase):
                scores[service] += weight

    # -------------------------------------------------------------
    # STRONG TRADE ANCHORS
    # These identify the physical system involved.
    # -------------------------------------------------------------
    add("Roofing", [
        "roof", "roofing", "roofer", "shingle", "shingles",
        "roof tile", "roof tiles", "flashing", "soffit", "fascia",
        "ridge vent", "roof vent", "skylight", "underlayment",
        "roof hole", "hole in my roof", "hole on my roof",
        "missing shingles", "damaged shingles"
    ], 7)

    add("Plumbing", [
        "plumbing", "plumber", "water heater", "hot water heater",
        "tankless water heater", "toilet", "sink", "faucet",
        "garbage disposal", "sewer", "septic", "drain", "drain line",
        "water line", "supply line", "pipe", "pipes", "hose bib",
        "spigot", "shower valve", "tub", "bathtub", "water softener"
    ], 7)

    add("HVAC", [
        "hvac", "air conditioner", "air conditioning", "a/c",
        "ac unit", "my ac", "furnace", "heat pump", "thermostat",
        "air handler", "condenser", "evaporator", "ductwork", "duct work",
        "central air", "central heat", "heating system", "cooling system",
        "mini split", "minisplit"
    ], 7)

    add("Electrical", [
        "electrician", "electrical", "breaker", "circuit breaker",
        "electrical panel", "panel box", "outlet", "receptacle",
        "light switch", "wiring", "wire", "junction box",
        "gfci", "gfi", "ceiling fan", "light fixture",
        "meter base", "service panel"
    ], 7)

    # -------------------------------------------------------------
    # SUPPORTING CONTEXT
    # Useful when the customer describes a system less directly.
    # -------------------------------------------------------------
    add("Roofing", [
        "attic after rain", "rain coming in", "rain water coming in",
        "storm damage", "hail damage", "wind damage",
        "water coming through roof", "leaking roof",
        "roof is leaking", "roof leak"
    ], 5)

    add("Plumbing", [
        "clogged", "backed up", "won't flush", "wont flush",
        "no hot water", "low water pressure", "water pressure",
        "water leak from pipe", "pipe leak", "leaking pipe",
        "under sink leak", "toilet leaking", "faucet leaking",
        "drain leaking", "sewer smell"
    ], 5)

    add("HVAC", [
        "no ac", "no a/c", "not cooling", "won't cool", "wont cool",
        "not heating", "no heat", "blowing warm air", "blowing hot air",
        "blowing cold air", "outside unit", "inside unit",
        "air not blowing", "ac leaking", "a/c leaking",
        "condensate drain"
    ], 5)

    add("Electrical", [
        "no power", "power outage in", "keeps tripping", "breaker tripping",
        "sparking outlet", "burning outlet", "lights flickering",
        "flickering lights", "electrical smell", "buzzing outlet"
    ], 5)

    # -------------------------------------------------------------
    # DISAMBIGUATION RULES
    # A generic word like "leak" is NEVER a plumbing vote by itself.
    # -------------------------------------------------------------
    if "leak" in t or "leaking" in t:
        if any(x in t for x in ("roof", "shingle", "flashing", "skylight", "rain", "storm", "attic")):
            scores["Roofing"] += 6
        if any(x in t for x in ("pipe", "sink", "toilet", "faucet", "drain", "water heater", "shower", "tub", "sewer")):
            scores["Plumbing"] += 6
        if any(x in t for x in ("ac", "a/c", "air conditioner", "air handler", "condensate", "hvac")):
            scores["HVAC"] += 6

    # "Water" alone is not plumbing. Roof leaks and AC condensate both
    # involve water, so it only supports a trade when paired with an anchor.
    if "water" in t:
        if any(x in t for x in ("pipe", "sink", "toilet", "faucet", "drain", "water heater", "sewer", "shower", "tub")):
            scores["Plumbing"] += 2
        if any(x in t for x in ("roof", "shingle", "flashing", "skylight", "rain", "attic")):
            scores["Roofing"] += 2
        if any(x in t for x in ("ac", "a/c", "air conditioner", "air handler", "condensate")):
            scores["HVAC"] += 2

    # "Power" can be colloquial. Require electrical context unless it is
    # the explicit phrase "no power".
    if "no power" in t:
        scores["Electrical"] += 5

    # -------------------------------------------------------------
    # PICK A TRADE
    # -------------------------------------------------------------
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_service, best_score = ranked[0]
    second_score = ranked[1][1]

    # If there is no real trade signal, or two trades are effectively tied,
    # do not guess. The chat will ask the customer what type of work it is.
    if best_score < 5:
        service = "General Repair"
    elif best_score == second_score and best_score > 0:
        service = "General Repair"
    elif best_score - second_score <= 1 and second_score >= 5:
        service = "General Repair"
    else:
        service = best_service

    # -------------------------------------------------------------
    # URGENCY IS SEPARATE FROM TRADE CLASSIFICATION
    # -------------------------------------------------------------
    emergency_signals = [
        "smell gas", "gas leak", "fire", "on fire",
        "electrical arcing", "sparking", "smoke coming from",
        "burst pipe", "pipe burst", "major flooding", "water pouring",
        "ceiling collapsing", "roof collapsing",
        "live wire", "exposed live wire"
    ]
    high_time_signals = [
        "today", "asap", "urgent", "right now", "immediately",
        "need it fixed now", "need someone now", "same day",
        "as soon as possible", "this morning", "this afternoon",
        "this evening", "tonight"
    ]
    active_problem_signals = [
        "not working", "stopped working", "no ac", "no a/c", "no heat",
        "leaking", "leak", "flooding", "overflowing", "broken",
        "won't turn on", "wont turn on", "no power",
        "hole in", "missing shingles", "keeps tripping", "rain coming through", "water coming through roof"
    ]

    if any(x in t for x in emergency_signals):
        urgency = "Emergency"
    elif (
        any(x in t for x in high_time_signals)
        or any(x in t for x in active_problem_signals)
        or ("rain" in t and any(x in t for x in ("roof", "shingle", "flashing", "skylight", "attic")))
    ):
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

def normalize_phone(value):
    """
    Normalize US phone numbers to E.164 for database storage and Twilio.
    Examples:
      9048061012       -> +19048061012
      904-806-1012     -> +19048061012
      (904) 806-1012   -> +19048061012
      +19048061012     -> +19048061012
    """
    raw = (value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())

    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if raw.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    return ""


def display_phone(value):
    """Pretty display only; never use this value for Twilio."""
    e164 = normalize_phone(value)
    digits = "".join(ch for ch in e164 if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return value or ""


def _clean_phone(value):
    normalized = normalize_phone(value)
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _extract_phone(value):
    # Conversation state/database keeps E.164, not pretty formatting.
    return normalize_phone(value)



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
                "Review the details below and tap Send My Request."
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


def log_sms_delivery(recipient, message_type, status, error="",
                     business_id=0, lead_id=0, waitlist_id=0):
    try:
        con = db()
        execute(
            con,
            """INSERT INTO sms_delivery_log
               (created_at,business_id,lead_id,waitlist_id,recipient,message_type,status,error)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                int(business_id or 0),
                int(lead_id or 0),
                int(waitlist_id or 0),
                (recipient or "").strip(),
                (message_type or "").strip(),
                (status or "").strip(),
                (error or "")[:1000]
            )
        )
        con.commit()
        con.close()
    except Exception as e:
        print("SMS log error:", repr(e), flush=True)


def send_twilio_body(to_phone, body, return_error=False):
    """
    Beta-safe Twilio sender.
    Never raises into the user flow. Returns False on failure, or (ok,error)
    when return_error=True.
    """
    try:
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
            err = "Twilio is not fully configured."
            print("Twilio skipped:", err, flush=True)
            return (False, err) if return_error else False

        import urllib.parse
        import urllib.request
        import urllib.error
        import json
        import base64

        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{TWILIO_ACCOUNT_SID}/Messages.json"
        )
        normalized_to = normalize_phone(to_phone)
        normalized_from = normalize_phone(TWILIO_PHONE_NUMBER)

        if not normalized_to:
            err = "Recipient phone number is invalid."
            return (False, err) if return_error else False

        payload = urllib.parse.urlencode({
            "To": normalized_to,
            "From": normalized_from or TWILIO_PHONE_NUMBER,
            "Body": body,
        }).encode()

        req = urllib.request.Request(url, data=payload, method="POST")
        token = base64.b64encode(
            f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()
        ).decode()
        req.add_header("Authorization", f"Basic {token}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=12) as resp:
            resp.read()

        return (True, "") if return_error else True

    except urllib.error.HTTPError as e:
        raw_body = ""
        try:
            raw_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            raw_body = ""

        twilio_code = ""
        twilio_message = ""
        more_info = ""

        if raw_body:
            try:
                payload = json.loads(raw_body)
                twilio_code = str(payload.get("code", "") or "")
                twilio_message = str(payload.get("message", "") or "")
                more_info = str(payload.get("more_info", "") or "")
            except Exception:
                pass

        parts = [f"HTTP {e.code} {e.reason}"]
        if twilio_code:
            parts.append(f"Twilio code {twilio_code}")
        if twilio_message:
            parts.append(twilio_message)
        elif raw_body:
            parts.append(raw_body[:700])

        err = " | ".join(parts)

        print("Twilio send failed:", err, flush=True)
        if more_info:
            print("Twilio more info:", more_info, flush=True)

        return (False, err) if return_error else False

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print("Twilio send failed:", err, flush=True)
        return (False, err) if return_error else False


def notify_waitlist_customer(waitlist_id):
    """
    Send a customer the coverage-available SMS they opted into.
    Does not create a lead automatically; customer returns to LeadPilot to submit.
    """
    con = db()
    row = execute(
        con, "SELECT * FROM coverage_waitlist WHERE id=?", (waitlist_id,)
    ).fetchone()
    con.close()

    if not row:
        return False, "Coverage request not found."

    if (row["status"] or "").strip() != "Provider Available":
        return False, "This request is not ready for notification."

    phone = (row["phone"] or "").strip()
    business_id = int(row["matched_business_id"] or 0)
    if not phone or not business_id:
        return False, "A phone number and matched provider are required."

    business = get_business_settings(business_id)
    if not business_can_receive_leads(business):
        return False, "The matched provider is no longer eligible for leads."

    service = (row["service"] or "service").strip()
    location = (row["city"] or row["location"] or "your area").strip()
    provider_name = business.get("name") or "a verified local provider"

    return_url = APP_BASE_URL or ""
    body = (
        f"LeadPilot update: {provider_name} is now available for {service} "
        f"in {location}. "
        + (f"Return to LeadPilot to submit your request: {return_url}" if return_url
           else "Return to LeadPilot to submit your request.")
    )

    ok, err = send_twilio_body(phone, body, return_error=True)
    log_sms_delivery(
        phone,
        "coverage_available",
        "Sent" if ok else "Failed",
        err,
        business_id=business_id,
        waitlist_id=waitlist_id
    )
    if not ok:
        return False, "SMS failed. Customer remains in Ready to notify."

    con = db()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    execute(
        con,
        """UPDATE coverage_waitlist
           SET status='Notified', notified_at=?
           WHERE id=?""",
        (now, waitlist_id)
    )
    con.commit()
    con.close()
    return True, provider_name


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


def send_new_lead_sms(lead_id, name, phone, service, urgency, message,
                      qualification, business_id=BUSINESS_ID):
    """
    Notify the matched provider immediately for every new marketplace lead.
    Hot leads receive stronger wording, but only one initial SMS is sent.
    """
    business = get_business_settings(business_id)
    alert_phone = (business.get("alert_phone") or NOTIFY_PHONE or "").strip()

    if not alert_phone:
        print("Provider SMS skipped: no alert phone configured.", flush=True)
        return False

    score = int(qualification.get("lead_score", 0))
    quality = (qualification.get("qualification") or "Standard").strip()
    customer_name = (name or "Customer").strip()
    customer_phone = (phone or "No phone").strip()
    service_name = (service or "General Repair").strip()
    urgency_name = (urgency or "Normal").strip()

    if quality == "Hot" or score >= 90:
        lead_label = "🔥 HOT LEAD"
        action = "Call now."
    elif quality == "Strong" or score >= 70:
        lead_label = "⚡ NEW STRONG LEAD"
        action = "Contact within 5-10 minutes."
    else:
        lead_label = "📥 NEW LEAD"
        action = "Review and contact promptly."

    dashboard_url = ""
    if APP_BASE_URL:
        dashboard_url = f"{APP_BASE_URL}/dashboard?business={business_id}"

    body = (
        f"{lead_label} — {score}/100\\n"
        f"{service_name} · {urgency_name} urgency\\n"
        f"Customer: {customer_name}\\n"
        f"Phone: {customer_phone}\\n"
        f"{action}"
    )
    if dashboard_url:
        body += f"\\nDashboard: {dashboard_url}"

    ok, err = send_twilio_body(alert_phone, body, return_error=True)
    log_sms_delivery(
        alert_phone,
        "provider_new_lead",
        "Sent" if ok else "Failed",
        err,
        business_id=business_id,
        lead_id=lead_id
    )
    print(
        "Provider new-lead SMS:",
        "sent" if ok else "failed",
        "business", business_id,
        "lead", lead_id,
        flush=True
    )
    return ok


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
*{box-sizing:border-box}
:root{
  --navy:#172033;
  --navy2:#243453;
  --blue:#3448c5;
  --ink:#172033;
  --muted:#667085;
  --line:#e2e8f0;
  --soft:#f7f9fc;
  --green:#067647;
  --green-soft:#ecfdf3;
}
body{
  font-family:Arial,sans-serif;
  margin:0;
  color:var(--ink);
  background:
    radial-gradient(circle at top right,rgba(52,72,197,.08),transparent 26%),
    linear-gradient(180deg,#f8faff,#f3f6fa 420px,#f4f7fb);
}
.wrap{max-width:760px;margin:auto;padding:20px 16px 42px}
.card{
  background:#fff;
  border:1px solid rgba(226,232,240,.9);
  border-radius:22px;
  padding:22px;
  box-shadow:0 10px 30px rgba(20,32,51,.07);
  margin-bottom:18px;
}
.brand-card{
  position:relative;
  overflow:hidden;
  background:linear-gradient(145deg,#fff,#fbfcff);
}
.brand-row{display:flex;align-items:center;gap:13px}
.logo{
  width:48px;height:48px;border-radius:14px;
  display:grid;place-items:center;
  background:linear-gradient(145deg,var(--navy),var(--blue));
  color:#fff;font-size:15px;font-weight:900;
  box-shadow:0 8px 18px rgba(52,72,197,.23);
}
h1,h2,h3{letter-spacing:-.03em}
h1{font-size:31px;margin:0}
h2{font-size:27px;margin:0 0 8px}
h3{font-size:20px;margin:0}
.muted{color:var(--muted);line-height:1.45}
.eyebrow{
  color:var(--blue);font-size:11px;font-weight:900;
  letter-spacing:.07em;text-transform:uppercase;margin-bottom:6px
}
.business-banner{
  margin-top:17px;padding:11px 13px;border-radius:12px;
  background:#f3f6ff;border:1px solid #e0e7ff;
  color:#344054;font-size:13px;font-weight:700;
}
.assistant-head{margin-bottom:18px}
.chat{
  min-height:210px;
  max-height:410px;
  overflow:auto;
  background:linear-gradient(180deg,#f8faff,#f5f7fb);
  border:1px solid #edf0f5;
  border-radius:18px;
  padding:14px;
}
.msg{
  padding:12px 14px;border-radius:14px;margin:9px 0;
  max-width:87%;line-height:1.42;font-size:15px
}
.bot{
  background:#e9eefb;color:var(--ink);
  border-bottom-left-radius:5px;
}
.user{
  background:linear-gradient(145deg,var(--navy),#22314d);
  color:#fff;margin-left:auto;border-bottom-right-radius:5px
}
.row{display:grid;grid-template-columns:1fr auto;gap:9px;margin-top:13px}
input,textarea,button{font:inherit}
input,textarea{
  width:100%;padding:14px;border:1px solid #d0d5dd;
  border-radius:12px;background:#fff;color:var(--ink);font-size:16px
}
input:focus,textarea:focus{outline:2px solid rgba(52,72,197,.13);border-color:#8090e6}
button{
  border:0;border-radius:12px;background:var(--navy);color:#fff;
  font-weight:800;cursor:pointer
}
.send-chat{padding:0 20px;min-height:50px}
.summary-card{display:none}
.summary-card.visible{display:block}
.summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}
.summary-item{
  background:#f8fafc;border:1px solid #edf0f4;border-radius:13px;
  padding:13px;min-height:75px
}
.summary-item span{
  display:block;color:var(--muted);font-size:11px;
  text-transform:uppercase;letter-spacing:.05em;font-weight:800
}
.summary-item strong{display:block;margin-top:5px;font-size:16px}
.problem-row{grid-column:1/-1}
.contact-block{margin-top:18px;padding-top:18px;border-top:1px solid #eef1f5}
.contact-block h3{margin-bottom:5px}
.contact-grid{display:grid;gap:8px;margin-top:12px}
.contact-review{
  margin-top:13px;padding:14px;border:1px solid #e2e8f0;border-radius:14px;
  background:#f8fafc;align-items:center;justify-content:space-between;gap:12px
}
.contact-review span{display:block;color:#667085;font-size:11px;text-transform:uppercase;letter-spacing:.05em;font-weight:800}
.contact-review strong{display:block;font-size:17px;margin-top:4px}
.contact-review small{display:block;color:#667085;margin-top:3px}
.edit-contact{background:#fff;color:#172033;border:1px solid #d0d5dd;padding:9px 12px;white-space:nowrap}
.ready-note{color:#067647;font-weight:700;margin-top:7px;font-size:13px}
.field-label{font-size:12px;font-weight:800;color:#344054;margin:5px 0 0}
.optional{font-weight:400;color:var(--muted)}
.primary-submit{
  width:100%;padding:16px;margin-top:14px;
  background:linear-gradient(145deg,var(--navy),#22314d);
  font-size:16px;box-shadow:0 7px 16px rgba(20,32,51,.15)
}
.primary-submit:disabled{opacity:.65}
.result{margin:11px 0 0;color:#b42318;font-size:13px}
.confirmation{
  display:none;
  background:linear-gradient(180deg,#fff,#fbfffc);
  border-color:#ccebd8;
}
.confirmation.visible{display:block}
.success-icon{
  width:52px;height:52px;border-radius:50%;
  display:grid;place-items:center;background:var(--green-soft);
  color:var(--green);font-size:25px;font-weight:900;margin-bottom:14px
}
.confirmation h2{color:#102a1e}
.confirm-summary{margin:18px 0;display:grid;gap:8px}
.confirm-row{
  display:flex;justify-content:space-between;gap:16px;
  padding:11px 0;border-bottom:1px solid #edf0f4
}
.confirm-row span{color:var(--muted)}
.confirm-row strong{text-align:right}
.next-box{
  background:#f7f9fc;border-radius:14px;padding:16px;margin-top:18px
}
.next-box h3{font-size:17px;margin-bottom:10px}
.next-step{display:flex;gap:10px;margin:9px 0;color:#475467;line-height:1.4}
.step-num{
  flex:0 0 24px;height:24px;border-radius:50%;
  background:var(--navy);color:#fff;display:grid;place-items:center;
  font-size:11px;font-weight:900
}
.owner-card{text-align:center;padding:17px}
.owner-card a{color:var(--blue);font-weight:800;text-decoration:none}
.trust-note{
  display:flex;gap:9px;align-items:flex-start;margin-top:14px;
  font-size:12px;color:var(--muted);line-height:1.4
}
.trust-shield{
  width:24px;height:24px;border-radius:8px;background:#eef3ff;
  color:var(--blue);display:grid;place-items:center;flex:0 0 24px
}
@media(max-width:600px){
  .wrap{padding:12px 10px 34px}
  .card{padding:18px;border-radius:19px}
  h1{font-size:28px}
  h2{font-size:25px}
  .logo{width:44px;height:44px}
  .summary-grid{grid-template-columns:1fr 1fr}
  .row{grid-template-columns:1fr auto}
  .send-chat{padding:0 17px}
}
</style>
</head>
<body>
<div class="wrap">

<div class="card brand-card">
  <div class="brand-row">
    <div class="logo">LP</div>
    <div>
      <div class="eyebrow">Local service request</div>
      <h1>LeadPilot AI</h1>
    </div>
  </div>
  <p class="muted" style="margin:15px 0 0;font-size:16px">Fast help from a local service professional.</p>
  <p class="muted" style="margin:4px 0 0">Tell us what you need. We'll get your request to the right person.</p>
  <div id="businessBanner" class="business-banner" style="display:none"></div>
</div>

<div id="assistantCard" class="card">
  <div class="assistant-head">
    <div class="eyebrow">Request assistant</div>
    <h2>How can we help?</h2>
    <div class="muted">Describe what's going on in your own words.</div>
  </div>

  <div id="chat" class="chat">
    <div class="msg bot">Hi! Tell me what you need help with today.</div>
  </div>

  <div class="row">
    <input id="message" autocomplete="off" placeholder="Describe the problem...">
    <button class="send-chat" onclick="sendChat()">Send</button>
  </div>

  <div class="trust-note">
    <div class="trust-shield">✓</div>
    <div>Your request details are used to connect you with the service business handling your request.</div>
  </div>
</div>

<div id="summaryCard" class="card summary-card">
  <div class="eyebrow">Review before sending</div>
  <h2>Your request</h2>
  <div class="muted">Check the details LeadPilot collected so far.</div>

  <div class="summary-grid">
    <div id="sumServiceWrap" class="summary-item" style="display:none">
      <span>Service</span><strong id="sumService"></strong>
    </div>
    <div id="sumLocationWrap" class="summary-item" style="display:none">
      <span>Location</span><strong id="sumLocation"></strong>
    </div>
    <div id="sumUrgencyWrap" class="summary-item" style="display:none">
      <span>Urgency</span><strong id="sumUrgency"></strong>
    </div>
    <div id="sumProblemWrap" class="summary-item problem-row" style="display:none">
      <span>Problem</span><strong id="sumProblem"></strong>
    </div>
  </div>

  <div id="contactBlock" class="contact-block">
    <h3>How should the business reach you?</h3>
    <div id="contactHelp" class="muted">LeadPilot will fill this in as you answer the assistant.</div>

    <div id="contactReview" class="contact-review" style="display:none">
      <div>
        <span>Contact</span>
        <strong id="contactReviewName"></strong>
        <small id="contactReviewPhone"></small>
        <small id="contactReviewEmail"></small>
      </div>
      <button type="button" class="edit-contact" onclick="editContact()">Edit</button>
    </div>

    <div id="contactFields" class="contact-grid">
      <div class="field-label">Name</div>
      <input id="name" autocomplete="name" placeholder="Your name">

      <div class="field-label">Phone</div>
      <input id="phone" inputmode="tel" autocomplete="tel" placeholder="Best phone number">

      <div class="field-label">Email <span class="optional">(optional)</span></div>
      <input id="email" inputmode="email" autocomplete="email" placeholder="Email address">

      <input id="zip" type="hidden">
      <input id="service" type="hidden">
      <input id="urgency" type="hidden">
      <textarea id="details" style="display:none"></textarea>
    </div>

    <button id="submitButton" class="primary-submit" onclick="submitLead()">SEND MY REQUEST →</button>
    <p id="result" class="result"></p>
  </div>
</div>

<div id="waitlistConfirmation" class="card confirmation">
  <div class="success-icon">✓</div>
  <div class="eyebrow" style="color:#067647">Coverage notification saved</div>
  <h2 id="waitlistTitle">You're on the list.</h2>
  <p id="waitlistText" class="muted"></p>

  <div class="confirm-summary">
    <div class="confirm-row"><span>Service</span><strong id="waitlistService"></strong></div>
    <div class="confirm-row"><span>Area</span><strong id="waitlistLocation"></strong></div>
    <div class="confirm-row"><span>Contact</span><strong id="waitlistContact"></strong></div>
  </div>

  <div class="next-box">
    <h3>What happens next?</h3>
    <div class="next-step"><div class="step-num">1</div><div>LeadPilot keeps your coverage request saved.</div></div>
    <div class="next-step"><div class="step-num">2</div><div>When a verified provider becomes available for this service area, LeadPilot can notify you using the contact information you provided.</div></div>
    <div class="next-step"><div class="step-num">3</div><div>You can return anytime to start a request for another service or location.</div></div>
  </div>
</div>

<div id="confirmationCard" class="card confirmation">
  <div class="success-icon">✓</div>
  <div class="eyebrow" style="color:#067647">Request sent</div>
  <h2 id="confirmTitle">You're all set.</h2>
  <p id="confirmText" class="muted"></p>

  <div class="confirm-summary">
    <div id="confirmServiceRow" class="confirm-row"><span>Service</span><strong id="confirmService"></strong></div>
    <div id="confirmLocationRow" class="confirm-row"><span>Location</span><strong id="confirmLocation"></strong></div>
    <div id="confirmUrgencyRow" class="confirm-row"><span>Urgency</span><strong id="confirmUrgency"></strong></div>
  </div>

  <div class="next-box">
    <h3>What happens next?</h3>
    <div class="next-step"><div class="step-num">1</div><div>The business reviews your request.</div></div>
    <div class="next-step"><div class="step-num">2</div><div>They'll contact you using the information you provided.</div></div>
    <div class="next-step"><div class="step-num">3</div><div>You can discuss pricing, scheduling, and job details directly with them.</div></div>
  </div>
</div>

<div class="card owner-card">
  <strong>Business owner?</strong>
  <a href="/login"> Business login →</a>
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
  lead_submitted: false,
  waitlist_saved: false,
  service_locked: false
};

const configuredBusinessName = '__BUSINESS_NAME__';

function add(text,cls){
 const c=document.getElementById('chat');
 const d=document.createElement('div');
 d.className='msg '+cls;
 d.textContent=text;
 c.appendChild(d);
 c.scrollTop=c.scrollHeight;
}

function setText(id,value){
 const el=document.getElementById(id);
 if(el) el.textContent=value||'';
}

function showSummaryItem(wrapId,textId,value){
 const wrap=document.getElementById(wrapId);
 if(!wrap)return;
 if(value){
   wrap.style.display='';
   setText(textId,value);
 }else{
   wrap.style.display='none';
 }
}

function refreshBusinessBanner(){
 const banner=document.getElementById('businessBanner');
 let name='';

 if(chatContext.marketplace_mode){
   name=chatContext.business_name||'';
 }else{
   name=chatContext.business_name||configuredBusinessName||'';
 }

 if(name && name!=='LeadPilot AI'){
   banner.textContent='Requesting service from '+name;
   banner.style.display='block';
 }else{
   banner.style.display='none';
 }
}

function contactIsComplete(){
 return !!((chatContext.customer_name||chatContext.waitlist_name) &&
           (chatContext.customer_phone||chatContext.waitlist_phone||chatContext.customer_email||chatContext.waitlist_email));
}

function editContact(){
 document.getElementById('contactReview').style.display='none';
 document.getElementById('contactFields').style.display='grid';
 document.getElementById('contactHelp').textContent='Update anything that needs correcting before you send the request.';
}

function refreshContactReview(){
 const name=chatContext.customer_name||chatContext.waitlist_name||'';
 const phone=chatContext.customer_phone||chatContext.waitlist_phone||'';
 const email=chatContext.customer_email||chatContext.waitlist_email||'';

 const ready=!!(name && (phone||email));
 const review=document.getElementById('contactReview');
 const fields=document.getElementById('contactFields');
 const help=document.getElementById('contactHelp');

 if(ready){
   document.getElementById('name').value=name;
   document.getElementById('phone').value=phone;
   document.getElementById('email').value=email;

   setText('contactReviewName',name);
   setText('contactReviewPhone',phone);
   setText('contactReviewEmail',email);

   document.getElementById('contactReviewPhone').style.display=phone?'block':'none';
   document.getElementById('contactReviewEmail').style.display=email?'block':'none';

   review.style.display='flex';
   fields.style.display='none';
   help.innerHTML='<span class="ready-note">✓ Contact information collected by LeadPilot.</span>';
 }else{
   review.style.display='none';
   fields.style.display='grid';
   help.textContent='LeadPilot will fill this in as you answer the assistant.';
 }
}

function showWaitlistConfirmation(){
 const name=chatContext.waitlist_name||'there';
 const firstName=(name||'').trim().split(/\s+/)[0]||'there';
 const contact=chatContext.waitlist_phone||chatContext.waitlist_email||'Saved';

 setText('waitlistTitle',`You're on the list, ${firstName}.`);
 setText('waitlistText',`LeadPilot saved your request and will use the contact information you provided when verified ${String(chatContext.service||'service').toLowerCase()} coverage becomes available in your area.`);
 setText('waitlistService',chatContext.service||'Service request');
 setText('waitlistLocation',chatContext.customer_location||chatContext.customer_zip||'Your area');
 setText('waitlistContact',contact);

 document.getElementById('assistantCard').style.display='none';
 document.getElementById('summaryCard').style.display='none';
 document.getElementById('waitlistConfirmation').classList.add('visible');
 window.scrollTo({top:0,behavior:'smooth'});
}

function refreshSummary(){
 const location=chatContext.customer_zip||chatContext.customer_location||'';

 showSummaryItem('sumServiceWrap','sumService',chatContext.service);
 showSummaryItem('sumLocationWrap','sumLocation',location);
 showSummaryItem('sumUrgencyWrap','sumUrgency',chatContext.urgency);
 showSummaryItem('sumProblemWrap','sumProblem',chatContext.issue);

 const usefulInfo=chatContext.service||location||chatContext.issue||chatContext.customer_name||chatContext.customer_phone;
 document.getElementById('summaryCard').classList.toggle('visible',!!usefulInfo);

 const nameEl=document.getElementById('name');
 const phoneEl=document.getElementById('phone');
 const emailEl=document.getElementById('email');
 const zipEl=document.getElementById('zip');

 if(nameEl && chatContext.customer_name) nameEl.value=chatContext.customer_name;
 if(phoneEl && chatContext.customer_phone) phoneEl.value=chatContext.customer_phone;
 if(emailEl && chatContext.customer_email!==undefined) emailEl.value=chatContext.customer_email||'';
 if(zipEl) zipEl.value=location;

 document.getElementById('service').value=chatContext.service||'';
 document.getElementById('urgency').value=chatContext.urgency||'';
 document.getElementById('details').value=chatContext.issue||'';

 refreshContactReview();

 const submitButton=document.getElementById('submitButton');
 const readyToSend = chatContext.intake_step==='ready' && !!chatContext.matched_business_id;
 if(submitButton){
   submitButton.style.display=readyToSend?'block':'none';
 }
 const contactBlock=document.getElementById('contactBlock');
 if(contactBlock){
   contactBlock.style.display=(chatContext.matched_business_id || !chatContext.marketplace_mode)?'block':'none';
 }

 refreshBusinessBanner();
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
     context:chatContext,
     business_id:__BUSINESS_ID__,
     marketplace_mode:chatContext.marketplace_mode
   })
 });

 const j=await r.json();

 add(j.reply,'bot');
 if(j.service){
   if(!chatContext.service_locked || chatContext.service==='General Repair' || j.service===chatContext.service){
     chatContext.service=j.service;
     if(j.service!=='General Repair') chatContext.service_locked=true;
   }
 }
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
 if(j.waitlist_saved!==undefined) chatContext.waitlist_saved=!!j.waitlist_saved;

 refreshSummary();

 if(chatContext.waitlist_saved || chatContext.intake_step==='waitlist_complete'){
   showWaitlistConfirmation();
   return;
 }
}

async function submitLead(auto=false){
 if(chatContext.lead_submitted)return;

 const data={
   business_id:chatContext.matched_business_id||__BUSINESS_ID__,
   name:(document.getElementById('name').value||chatContext.customer_name||chatContext.waitlist_name||'').trim(),
   phone:(document.getElementById('phone').value||chatContext.customer_phone||chatContext.waitlist_phone||'').trim(),
   email:(document.getElementById('email').value||chatContext.customer_email||chatContext.waitlist_email||'').trim(),
   zip:(chatContext.customer_zip||chatContext.customer_location||document.getElementById('zip').value||'').trim(),
   service:chatContext.service||document.getElementById('service').value||'General Repair',
   urgency:chatContext.urgency||document.getElementById('urgency').value||'Normal',
   message:chatContext.issue||document.getElementById('details').value||''
 };

 const result=document.getElementById('result');

 if(!data.name||!data.phone){
   result.textContent='Please provide your name and phone number so the business can reach you.';
   document.getElementById('summaryCard').classList.add('visible');
   return;
 }

 const button=document.getElementById('submitButton');
 if(button){
   button.disabled=true;
   button.textContent='SENDING...';
 }

 const r=await fetch('/api/leads',{
   method:'POST',
   headers:{'Content-Type':'application/json'},
   body:JSON.stringify(data)
 });

 const j=await r.json();

 if(r.ok){
   chatContext.lead_submitted=true;
   chatContext.intake_step='complete';

   const businessName=chatContext.business_name||configuredBusinessName||'the service business';
   const firstName=(data.name||'').trim().split(/\s+/)[0]||'there';

   setText('confirmTitle',`You're all set, ${firstName}.`);
   setText('confirmText',`${businessName} received your request and will contact you using the information you provided.`);

   const acceptedService=j.service||data.service;
   const acceptedUrgency=j.urgency||data.urgency;
   chatContext.service=acceptedService;
   chatContext.urgency=acceptedUrgency;
   chatContext.service_locked=acceptedService && acceptedService!=='General Repair';

   const location=data.zip||chatContext.customer_location||'';
   setText('confirmService',acceptedService);
   setText('confirmLocation',location);
   setText('confirmUrgency',acceptedUrgency);

   document.getElementById('confirmLocationRow').style.display=location?'flex':'none';
   document.getElementById('confirmServiceRow').style.display=acceptedService?'flex':'none';
   document.getElementById('confirmUrgencyRow').style.display=acceptedUrgency?'flex':'none';

   document.getElementById('assistantCard').style.display='none';
   document.getElementById('summaryCard').style.display='none';
   document.getElementById('confirmationCard').classList.add('visible');
   refreshBusinessBanner();

   window.scrollTo({top:0,behavior:'smooth'});
 }else{
   if(button){
     button.disabled=false;
     button.textContent='SEND MY REQUEST →';
   }
   if(j && j.message){
     result.textContent=j.message;
   }else{
     result.textContent='Something went wrong. Please try again.';
   }
 }
}

document.getElementById('message').addEventListener('keydown',e=>{
 if(e.key==='Enter'){
   e.preventDefault();
   sendChat();
 }
});

refreshBusinessBanner();
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


def money(value):
    try:
        value = float(value or 0)
    except Exception:
        value = 0
    return "${:,.0f}".format(value)


def get_service_pricing(business_id):
    con = db()
    rows = execute(
        con,
        """SELECT service,low_value,high_value
           FROM service_pricing
           WHERE business_id=?
           ORDER BY service""",
        (business_id,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _pricing_category(label):
    t = (label or "").strip().lower()
    if any(x in t for x in [
        "sink", "faucet", "toilet", "drain", "pipe", "sewer",
        "plumb", "water heater", "tankless", "garbage disposal", "water line"
    ]):
        return "plumbing"
    if any(x in t for x in [
        "hvac", "air condition", "a/c", "ac service", "furnace",
        "heat pump", "heating system"
    ]):
        return "hvac"
    if any(x in t for x in ["roof", "shingle"]):
        return "roofing"
    if any(x in t for x in ["electric", "outlet", "breaker", "panel", "wiring"]):
        return "electrical"
    return ""


def _pricing_keywords(label):
    t = (label or "").strip().lower()
    groups = {
        "sink": ["sink"],
        "faucet": ["faucet"],
        "toilet": ["toilet"],
        "drain": ["drain", "clog"],
        "sewer": ["sewer"],
        "pipe": ["pipe"],
        "garbage disposal": ["garbage disposal", "disposal"],
        "water heater": ["water heater", "hot water", "tankless"],
        "replacement": ["replacement", "replace", "replacing", "new system", "new roof"],
        "repair": ["repair", "repaired", "fix", "fixed", "broken"],
        "service": ["service", "maintenance", "tune up", "tune-up"],
        "leak": ["leak", "leaking"],
        "panel": ["panel"],
        "outlet": ["outlet"],
        "breaker": ["breaker"],
        "shingle": ["shingle"],
    }
    return [(concept, variants) for concept, variants in groups.items() if any(v in t for v in variants)]


def pricing_for_service(business_id, service):
    service_norm = (service or "").strip().lower()
    if not service_norm:
        return (0.0, 0.0)

    con = db()
    rows = execute(
        con,
        """SELECT service,low_value,high_value FROM service_pricing WHERE business_id=?""",
        (business_id,)
    ).fetchall()
    con.close()

    for r in rows:
        configured = (r["service"] or "").strip().lower()
        if configured == service_norm:
            return (float(r["low_value"] or 0), float(r["high_value"] or 0))

    category = _normalize_service_name(service_norm)
    for r in rows:
        configured = (r["service"] or "").strip().lower()
        if _pricing_category(configured) == category and not _pricing_keywords(configured):
            return (float(r["low_value"] or 0), float(r["high_value"] or 0))

    return (0.0, 0.0)


def pricing_for_lead(business_id, service, message):
    requested_category = _normalize_service_name(service)
    message_text = (message or "").strip().lower()

    con = db()
    rows = execute(
        con,
        """SELECT service,low_value,high_value FROM service_pricing WHERE business_id=?""",
        (business_id,)
    ).fetchall()
    con.close()

    best = None
    best_score = -1
    generic = None

    for r in rows:
        label = (r["service"] or "").strip()
        label_lower = label.lower()
        category = _pricing_category(label_lower)
        normalized_label = _normalize_service_name(label_lower)

        if normalized_label in ("plumbing", "hvac", "roofing", "electrical"):
            category = normalized_label

        if category != requested_category:
            continue

        keyword_groups = _pricing_keywords(label_lower)

        if not keyword_groups:
            generic = r
            continue

        score = 0
        matched_specific = False

        for concept, variants in keyword_groups:
            if any(v in message_text for v in variants):
                if concept in (
                    "sink", "faucet", "toilet", "drain", "sewer", "pipe",
                    "garbage disposal", "water heater", "panel", "outlet",
                    "breaker", "shingle"
                ):
                    score += 8
                    matched_specific = True
                elif concept == "replacement":
                    score += 6
                    matched_specific = True
                elif concept in ("repair", "service", "leak"):
                    score += 2

        if matched_specific and score > best_score:
            best = r
            best_score = score

    chosen = best or generic
    if chosen:
        return (float(chosen["low_value"] or 0), float(chosen["high_value"] or 0))

    return (0.0, 0.0)


def lead_value_range(row, business_id):
    low = float(row["estimated_value_low"] or 0) if "estimated_value_low" in row.keys() else 0
    high = float(row["estimated_value_high"] or 0) if "estimated_value_high" in row.keys() else 0

    if low > 0 or high > 0:
        return (low, high)

    return pricing_for_lead(
        business_id,
        row["service"] or "",
        row["message"] or ""
    )


def revenue_estimates_html(business_id=BUSINESS_ID, message=""):
    business = get_business_settings(business_id)
    pricing = get_service_pricing(business_id)

    rows = ""
    for p in pricing:
        service = html.escape(p["service"] or "")
        rows += f"""
        <div class="price-row">
          <div><strong>{service}</strong><span>{money(p["low_value"])}–{money(p["high_value"])}</span></div>
          <form method="POST" action="/revenue-estimates/delete">
            <input type="hidden" name="business_id" value="{business_id}">
            <input type="hidden" name="service" value="{html.escape(p["service"] or "", quote=True)}">
            <button class="delete">Remove</button>
          </form>
        </div>"""

    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot Revenue Estimates</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}
.wrap{{max-width:720px;margin:auto;padding:18px}} .nav{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}}
.nav a{{font-weight:800;color:#3448c5;text-decoration:none}} .card{{background:#fff;border-radius:20px;padding:22px;box-shadow:0 8px 28px rgba(0,0,0,.07);margin-bottom:16px}}
h1{{margin:0 0 6px;font-size:30px}} h2{{margin-top:0}} .sub,.hint{{color:#667085;line-height:1.45}}
label{{display:block;font-weight:800;margin:14px 0 6px}} input{{width:100%;padding:13px;border:1px solid #d0d5dd;border-radius:10px;font-size:16px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}} button{{border:0;border-radius:10px;padding:13px 16px;background:#172033;color:#fff;font-weight:800;font-size:15px}}
.flash{{background:#dcfae6;color:#05603a;padding:12px;border-radius:10px;font-weight:800;margin:12px 0}}
.price-row{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 0;border-bottom:1px solid #eaecf0}}
.price-row span{{display:block;color:#667085;margin-top:4px}} .delete{{background:#fff;color:#b42318;border:1px solid #fecdca;padding:9px 12px}}
.note{{background:#eef4ff;border-radius:12px;padding:14px;color:#344054;line-height:1.45}}
@media(max-width:560px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<div class="nav"><a href="/dashboard?business={business_id}">Dashboard</a><a href="/settings?business={business_id}">Settings</a><a href="/logout">Log out</a></div>
<div class="card">
<h1>Revenue Estimates</h1>
<div class="sub">{html.escape(business["name"])} · Teach LeadPilot what your typical jobs are worth. Use specific job types when possible.</div>
{f'<div class="flash">{html.escape(message)}</div>' if message else ''}
<div class="note"><strong>These are opportunity estimates — not customer quotes.</strong><br>
LeadPilot uses your own typical ranges. When a job is won, the actual sold value can be recorded so the dashboard separates estimated opportunity from real won revenue.</div>
<form method="POST" action="/revenue-estimates">
<label>Service / job type</label>
<input name="service" placeholder="Examples: Sink repair, Water heater replacement, Roof replacement" required>
<div class="grid">
<div><label>Typical low value</label><input name="low_value" type="number" min="0" step="1" placeholder="9000" required></div>
<div><label>Typical high value</label><input name="high_value" type="number" min="0" step="1" placeholder="18000" required></div>
</div>
<input type="hidden" name="business_id" value="{business_id}">
<button style="margin-top:16px">Save estimate range</button>
</form></div>
<div class="card"><h2>Configured job values</h2>
{rows or '<div class="hint">No ranges yet. Add the first service above.</div>'}
</div></div></body></html>"""

def lead_followup_status(row):
    """Timer-aware follow-up recommendation for the dashboard."""
    status = (row["status"] or "New").strip()
    score = int(row["lead_score"] or 0)
    qualification = (row["qualification"] or "Standard").strip()
    wait_minutes = lead_wait_minutes(row)

    if status in ("Won", "Lost", "Closed"):
        return ("done", f"{status} — no follow-up needed", wait_minutes, False)
    if status in ("Estimate", "Booked"):
        return ("booked", "Estimate stage — customer is being worked", wait_minutes, False)
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


def lead_score_for_sort(row):
    try:
        return int(row["lead_score"] or 0)
    except Exception:
        return 0



def historical_close_rate_for_lead(row, business_id):
    """
    Return a stabilized historical close-rate signal for this business/service.

    The displayed opportunity value stays unchanged. This signal is used only
    inside priority ranking. A small Bayesian-style prior prevents a tiny
    sample (for example 1 win or 1 loss) from swinging the queue too hard.
    """
    service = _normalize_service_name(row["service"] or "")
    if not service:
        return 0.50, 0

    con = db()
    try:
        history = execute(
            con,
            """SELECT service, status FROM leads
               WHERE business_id=? AND status IN ('Won','Lost','Closed')""",
            (business_id,)
        ).fetchall()
    finally:
        con.close()

    wins = 0
    losses = 0
    for h in history:
        if _normalize_service_name(h["service"] or "") != service:
            continue
        status = (h["status"] or "").strip()
        if status in ("Won", "Closed"):
            wins += 1
        elif status == "Lost":
            losses += 1

    outcomes = wins + losses

    # Neutral 50% prior with the weight of 5 completed jobs.
    # As real outcomes accumulate, the business's own close rate takes over.
    stabilized_rate = (wins + 2.5) / (outcomes + 5.0)
    return stabilized_rate, outcomes


def priority_rank(row, business_id):
    """
    Revenue-weighted priority score.

    Goal: rank the lead with the best combination of:
    1. Dollar opportunity
    2. Qualification / likelihood to close
    3. The business's historical close likelihood for that service
    4. Urgency
    5. Response-time pressure
    6. Pipeline stage

    Revenue is intentionally the strongest single factor, but a weak,
    low-quality large job will not automatically beat a strong, urgent lead.
    """
    low, high = lead_value_range(row, business_id)

    raw_status = (row["status"] or "New").strip()
    status = {"Booked":"Estimate", "Closed":"Won"}.get(raw_status, raw_status)

    if status not in ("New", "Contacted", "Estimate"):
        return -1

    try:
        lead_score = max(0, min(int(row["lead_score"] or 0), 100))
    except Exception:
        lead_score = 0

    _, _, wait_minutes, is_overdue = lead_followup_status(row)
    urgency = (row["urgency"] or "Normal").strip().lower()

    # -----------------------------
    # 1) Revenue score — max 100
    # -----------------------------
    # Use a conservative weighted value instead of the high estimate alone:
    # 60% low end + 40% high end.
    # This keeps the ranking grounded while still rewarding upside.
    expected_value = ((low or 0) * 0.60) + ((high or 0) * 0.40)

    # Revenue bands deliberately rise quickly for larger jobs.
    if expected_value >= 15000:
        revenue_score = 100
    elif expected_value >= 10000:
        revenue_score = 92
    elif expected_value >= 7500:
        revenue_score = 84
    elif expected_value >= 5000:
        revenue_score = 74
    elif expected_value >= 3000:
        revenue_score = 62
    elif expected_value >= 1500:
        revenue_score = 48
    elif expected_value >= 750:
        revenue_score = 34
    elif expected_value >= 300:
        revenue_score = 20
    elif expected_value > 0:
        revenue_score = 10
    else:
        revenue_score = 0

    # -----------------------------
    # 2) Qualification — max 100
    # -----------------------------
    qualification_score = lead_score

    # -----------------------------
    # 3) Historical close likelihood — max 100
    # -----------------------------
    # Invisible ranking signal only. We NEVER reduce the opportunity shown to
    # the owner. An $8,000 average job remains an ~$8,000 opportunity; this
    # simply helps LeadPilot decide which lead deserves attention first.
    historical_rate, historical_outcomes = historical_close_rate_for_lead(row, business_id)
    historical_score = historical_rate * 100.0

    # -----------------------------
    # 4) Urgency — max 100
    # -----------------------------
    if urgency == "emergency":
        urgency_score = 100
    elif urgency == "high":
        urgency_score = 75
    else:
        urgency_score = 25

    # -----------------------------
    # 5) Response pressure — max 100
    # -----------------------------
    hours_waiting = max(wait_minutes, 0) / 60.0
    if is_overdue and hours_waiting >= 24:
        response_score = 100
    elif is_overdue:
        response_score = 85
    elif hours_waiting >= 4:
        response_score = 65
    elif hours_waiting >= 1:
        response_score = 45
    elif hours_waiting >= 0.5:
        response_score = 30
    else:
        response_score = 15

    # -----------------------------
    # 6) Pipeline stage — max 100
    # -----------------------------
    stage_score = {
        "New": 100,
        "Contacted": 60,
        "Estimate": 45,
    }.get(status, 0)

    # Revenue is the strongest component.
    rank = (
        revenue_score * 0.45 +
        qualification_score * 0.20 +
        historical_score * 0.10 +
        urgency_score * 0.12 +
        response_score * 0.08 +
        stage_score * 0.05
    )

    # Small emergency work can still rise, but not simply overpower a
    # substantially larger qualified opportunity.
    if urgency == "emergency":
        rank += 6

    return rank


def priority_reason(row, business_id):
    low, high = lead_value_range(row, business_id)
    reasons = []

    try:
        score = int(row["lead_score"] or 0)
    except Exception:
        score = 0

    _, _, wait_minutes, is_overdue = lead_followup_status(row)
    urgency = (row["urgency"] or "Normal").strip().lower()

    expected_value = ((low or 0) * 0.60) + ((high or 0) * 0.40)

    if expected_value >= 5000:
        reasons.append("high-dollar opportunity")
    elif expected_value >= 750:
        reasons.append("strong revenue opportunity")
    elif expected_value > 0:
        reasons.append("revenue opportunity")

    if score >= 85:
        reasons.append("strong lead score")
    elif score >= 65:
        reasons.append("qualified lead")

    if urgency == "emergency":
        reasons.append("emergency")
    elif urgency == "high":
        reasons.append("high urgency")

    if is_overdue:
        reasons.append("overdue follow-up")
    elif wait_minutes >= 60:
        reasons.append("waiting customer")

    if not reasons:
        reasons.append("best current open lead")

    return " + ".join(reasons[:3])


def dashboard_html(business_id=BUSINESS_ID):
    business = get_business_settings(business_id)

    con = db()
    rows = execute(
        con,
        """SELECT * FROM leads
           WHERE business_id=?
           ORDER BY CASE WHEN status='New' THEN 0 ELSE 1 END, lead_score DESC, id DESC""",
        (business_id,)
    ).fetchall()
    routing_metrics = business_routing_metrics(con, business_id)
    con.close()

    counts = {"New":0, "Contacted":0, "Estimate":0, "Won":0, "Lost":0}
    quality_counts = {"Hot":0, "Strong":0, "Qualified":0, "Standard":0}

    open_opp_low = open_opp_high = 0.0
    overdue_opp_low = overdue_opp_high = 0.0
    won_revenue = 0.0
    overdue_count = 0
    open_count = 0
    completed_count = 0
    won_count = 0

    attention_rows = []

    for r in rows:
        raw_status = (r["status"] or "New").strip()
        status = {"Booked":"Estimate", "Closed":"Won"}.get(raw_status, raw_status)
        counts[status] = counts.get(status, 0) + 1

        quality = r["qualification"] or "Standard"
        quality_counts[quality] = quality_counts.get(quality, 0) + 1

        low, high = lead_value_range(r, business_id)

        if status in ("New", "Contacted", "Estimate"):
            open_count += 1
            open_opp_low += low
            open_opp_high += high

        if status == "Won":
            won_count += 1
            completed_count += 1
            won_revenue += float(r["final_job_value"] or 0)

        if status == "Lost":
            completed_count += 1

        followup_class, followup_text, wait_minutes, is_overdue = lead_followup_status(r)

        if is_overdue and status in ("New", "Contacted"):
            overdue_count += 1
            overdue_opp_low += low
            overdue_opp_high += high
            attention_rows.append((lead_score_for_sort(r), wait_minutes, r, low, high, followup_text))

    # Today's single best lead to work first.
    priority_candidates = []
    for r in rows:
        rank = priority_rank(r, business_id)
        if rank >= 0:
            priority_candidates.append((rank, r))

    priority_candidates.sort(key=lambda x: x[0], reverse=True)
    priority_row = priority_candidates[0][1] if priority_candidates else None
    priority_id = priority_row["id"] if priority_row else None

    # Needs Attention now uses the exact same revenue-weighted ranking system
    # as #1 Priority Today. The #1 lead is excluded so the owner gets a true
    # next-action queue instead of seeing the same customer twice.
    ranked_attention = []
    for r in rows:
        raw_status = (r["status"] or "New").strip()
        status = {"Booked":"Estimate", "Closed":"Won"}.get(raw_status, raw_status)
        followup_class, followup_text, wait_minutes, is_overdue = lead_followup_status(r)

        if (
            is_overdue
            and status in ("New", "Contacted", "Estimate")
            and r["id"] != priority_id
        ):
            low, high = lead_value_range(r, business_id)
            ranked_attention.append(
                (
                    priority_rank(r, business_id),
                    r,
                    low,
                    high,
                    followup_text,
                    wait_minutes,
                )
            )

    ranked_attention.sort(key=lambda x: x[0], reverse=True)

    conversion_rate = (won_count / completed_count * 100.0) if completed_count else 0.0
    average_won = (won_revenue / won_count) if won_count else 0.0

    # -------------------------------
    # Today's Priority
    # -------------------------------
    if priority_row:
        p_low, p_high = lead_value_range(priority_row, business_id)
        _, _, p_wait_minutes, p_overdue = lead_followup_status(priority_row)
        p_phone = (priority_row["phone"] or "").strip()
        p_value = (
            f"{money(p_low)}–{money(p_high)}"
            if (p_low > 0 or p_high > 0)
            else "Value not set"
        )
        p_score = int(priority_row["lead_score"] or 0)
        p_service = html.escape(priority_row["service"] or "General Repair")
        p_location = html.escape(priority_row["zip"] or "Location not provided")
        p_name = html.escape(priority_row["name"] or "Unnamed lead")
        p_reason = html.escape(priority_reason(priority_row, business_id))
        p_wait = format_wait_time(p_wait_minutes)
        p_raw_status = (priority_row["status"] or "New").strip()
        p_status = {"Booked":"Estimate", "Closed":"Won"}.get(p_raw_status, p_raw_status)
        p_email = (priority_row["email"] or "").strip()
        p_final_value = float(priority_row["final_job_value"] or 0)

        priority_status_buttons = ""
        for s in ["New","Contacted","Estimate","Won","Lost"]:
            active = "active" if p_status == s else ""
            priority_status_buttons += (
                f'<button class="priority-status-btn {active}" '
                f'onclick="updateStatus({priority_row["id"]}, \'{s}\')">{s}</button>'
            )

        priority_html = f"""
        <section class="priority-card">
          <div class="priority-kicker">🔥 #1 PRIORITY TODAY</div>
          <div class="priority-main">
            <div>
              <div class="priority-name">{p_name}</div>
              <div class="priority-service">{p_service} · {p_location}</div>
              <div class="priority-reason">Why: {p_reason}</div>
            </div>
            <div class="priority-value">
              <span>Opportunity</span>
              <strong>{p_value}</strong>
            </div>
          </div>

          <div class="priority-facts">
            <div><span>Lead score</span><strong>{p_score}/100</strong></div>
            <div><span>Waiting</span><strong>{p_wait}</strong></div>
            <div><span>Status</span><strong>{"🚨 OVERDUE" if p_overdue else "Open"}</strong></div>
          </div>

          <div class="priority-contact-actions">
            <a class="priority-call" href="tel:{html.escape(p_phone, quote=True)}">📞 Call</a>
            <a class="priority-contact" href="sms:{html.escape(p_phone, quote=True)}">💬 Text</a>
            <a class="priority-contact" href="mailto:{html.escape(p_email, quote=True)}">✉️ Email</a>
          </div>

          <div class="priority-pipeline">
            <div class="priority-pipeline-label">MOVE THIS LEAD</div>
            <div class="priority-status-actions">{priority_status_buttons}</div>

            <div id="wonbox-{priority_row['id']}" class="priority-won-box" style="display:{'block' if p_status=='Won' else 'none'}">
              <label>Final job value</label>
              <div class="won-input"><span>$</span><input id="value-{priority_row['id']}" type="number" min="0" step="1" value="{int(p_final_value) if p_final_value else ''}" placeholder="13400"><button onclick="saveValue({priority_row['id']})">Save</button></div>
              <small>Enter the actual sold amount. Saving moves revenue into Actual Won Revenue.</small>
            </div>

            <span id="saved-{priority_row['id']}" class="priority-saved"></span>
          </div>
        </section>
        """
    else:
        priority_html = """
        <section class="priority-card priority-empty">
          <div class="priority-kicker">🔥 TODAY'S PRIORITY</div>
          <div class="priority-name">No open leads right now</div>
          <div class="priority-reason">New opportunities will appear here automatically.</div>
        </section>
        """

    # -------------------------------
    # Needs Attention panel
    # -------------------------------
    attention_html = ""
    for queue_index, (_rank, r, low, high, followup_text, wait_minutes) in enumerate(ranked_attention[:5], start=2):
        phone = (r["phone"] or "").strip()
        value_text = (
            f"{money(low)}–{money(high)}"
            if (low > 0 or high > 0)
            else "Value not set"
        )
        queue_reason = priority_reason(r, business_id)

        attention_html += f"""
        <div class="attention-lead">
          <div>
            <div class="attn-name"><span class="queue-rank">#{queue_index}</span> {html.escape(r['name'] or 'Unnamed lead')}</div>
            <div class="attn-meta">{html.escape(r['service'] or 'General Repair')} · {html.escape(r['zip'] or 'Location not provided')}</div>
            <div class="attn-priority">Why: {html.escape(queue_reason)}</div>
            <div class="attn-reason">{html.escape(followup_text)}</div>
          </div>
          <div class="attn-value">
            <span>Opportunity</span>
            <strong>{value_text}</strong>
            <a href="tel:{html.escape(phone, quote=True)}">Call now</a>
          </div>
        </div>"""

    if not attention_html:
        attention_html = '<div class="attention-empty">No additional overdue leads right now. Work the #1 Priority lead first.</div>'

    # -------------------------------
    # Lead cards
    # -------------------------------
    cards = ""
    for r in rows:
        if priority_id is not None and r["id"] == priority_id:
            continue

        phone = (r["phone"] or "").strip()
        email = (r["email"] or "").strip()
        raw_status = (r["status"] or "New").strip()
        status = {"Booked":"Estimate", "Closed":"Won"}.get(raw_status, raw_status)
        urgency = r["urgency"] or "Normal"
        lead_score = int(r["lead_score"] or 0)
        qualification = r["qualification"] or "Standard"
        recommended_action = r["recommended_action"] or "Follow up and confirm the job details."
        followup_class, followup_text, wait_minutes, _ = lead_followup_status(r)
        low, high = lead_value_range(r, business_id)
        final_value = float(r["final_job_value"] or 0)

        if low > 0 or high > 0:
            opportunity = f"{money(low)}–{money(high)}"
            value_note = "Estimated opportunity"
        else:
            opportunity = "Not set"
            value_note = "Add a service range in Revenue Estimates"

        reason_chips = "".join(
            f'<span class="reason-chip">{html.escape(reason)}</span>'
            for reason in dashboard_score_reasons(r)
        )

        cards += f"""
        <section class="lead-card" data-stage="{html.escape(status)}">
          <div class="lead-top">
            <div>
              <div class="lead-name">{html.escape(r['name'] or 'Unnamed lead')}</div>
              <div class="lead-time">{html.escape(r['created_at'] or '')} · Waiting {format_wait_time(wait_minutes)}</div>
            </div>
            <div class="badges">
              <span class="badge score-badge">{lead_score}/100</span>
              <span class="badge qual-{qualification.lower()}">{html.escape(qualification)}</span>
              <span class="badge urgency-{urgency.lower()}">{html.escape(urgency)}</span>
            </div>
          </div>

          <div class="opportunity">
            <span>{value_note}</span>
            <strong>{opportunity}</strong>
            {"<small>Actual won value: "+money(final_value)+"</small>" if status=="Won" and final_value else ""}
          </div>

          <div class="details">
            <div><span>Service</span><strong>{html.escape(r['service'] or 'General Repair')}</strong></div>
            <div><span>Location</span><strong>{html.escape(r['zip'] or '—')}</strong></div>
            <div><span>Phone</span><strong>{html.escape(display_phone(phone) if phone else '—')}</strong></div>
            <div><span>Email</span><strong>{html.escape(email or '—')}</strong></div>
          </div>

          <div class="message">{html.escape(r['message'] or 'No message provided.')}</div>

          <div class="ai-box">
            <div class="ai-title">LeadPilot Qualification</div>
            <div><strong>{html.escape(qualification)} lead · {lead_score}/100</strong></div>
            <div class="reason-row">{reason_chips}</div>
            <div class="next-label">Recommended next step</div>
            <div class="ai-action">{html.escape(recommended_action)}</div>
          </div>

          <div class="followup-banner followup-{followup_class}"><strong>Follow-up:</strong> {html.escape(followup_text)}</div>

          <div class="actions">
            <a class="action primary" href="tel:{html.escape(phone, quote=True)}">📞 Call</a>
            <a class="action" href="sms:{html.escape(phone, quote=True)}">💬 Text</a>
            <a class="action" href="mailto:{html.escape(email, quote=True)}">✉️ Email</a>
          </div>

          <div class="status-row">
            <label>Lead pipeline</label>
            <div class="status-actions">
              {''.join(f'<button class="status-btn {"active" if status==s else ""}" onclick="updateStatus({r["id"]}, \'{s}\')">{s}</button>' for s in ["New","Contacted","Estimate","Won","Lost"])}
            </div>
            <div id="wonbox-{r['id']}" class="won-box" style="display:{'block' if status=='Won' else 'none'}">
              <label>Final job value</label>
              <div class="won-input"><span>$</span><input id="value-{r['id']}" type="number" min="0" step="1" value="{int(final_value) if final_value else ''}" placeholder="13400"><button onclick="saveValue({r['id']})">Save</button></div>
              <small>Use the actual sold amount. This is what counts toward Won Revenue.</small>
            </div>
            <span id="saved-{r['id']}" class="saved"></span>
          </div>
        </section>"""

    if not cards:
        cards = '<div class="empty">No leads yet. New customer requests routed to this business will appear here.</div>'

    return f"""<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot Business Lead Inbox</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}}
.wrap{{max-width:980px;margin:auto;padding:20px}}
header{{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:18px}}
h1{{font-size:30px;margin:0}}
.sub{{color:#667085;margin-top:5px}}
.toplinks a{{margin-left:12px;text-decoration:none;color:#3448c5;font-weight:700}}

.priority-card{{background:linear-gradient(135deg,#172033,#24304a);color:#fff;border-radius:20px;padding:20px;margin:18px 0;box-shadow:0 10px 30px rgba(23,32,51,.18)}}
.priority-empty{{background:#172033}}
.priority-kicker{{font-size:13px;font-weight:900;letter-spacing:.04em;color:#ffd66b;margin-bottom:12px}}
.priority-main{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}}
.priority-name{{font-size:26px;font-weight:900}}
.priority-service{{font-size:14px;color:#d0d5dd;margin-top:4px}}
.priority-reason{{font-size:13px;color:#e4e7ec;margin-top:10px;line-height:1.4}}
.priority-value{{text-align:right;min-width:155px}}
.priority-value span{{display:block;font-size:11px;text-transform:uppercase;color:#98a2b3}}
.priority-value strong{{display:block;font-size:25px;margin-top:5px}}
.priority-facts{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:16px 0}}
.priority-facts div{{background:rgba(255,255,255,.08);border-radius:10px;padding:10px}}
.priority-facts span{{display:block;font-size:10px;text-transform:uppercase;color:#b8c0cc}}
.priority-facts strong{{display:block;font-size:15px;margin-top:3px}}
.priority-contact-actions{{display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:8px;margin-top:16px}}
.priority-call,.priority-contact{{display:block;text-align:center;background:#fff;color:#172033;text-decoration:none;border-radius:11px;padding:14px 8px;font-size:15px;font-weight:900}}
.priority-contact{{background:rgba(255,255,255,.10);color:#fff;border:1px solid rgba(255,255,255,.18)}}
.priority-pipeline{{margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,.15)}}
.priority-pipeline-label{{font-size:10px;font-weight:900;letter-spacing:.06em;color:#b8c0cc;margin-bottom:8px}}
.priority-status-actions{{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}}
.priority-status-btn{{padding:10px 5px;border:1px solid rgba(255,255,255,.22);border-radius:9px;background:rgba(255,255,255,.08);color:#fff;font-weight:800;font-size:10px}}
.priority-status-btn.active{{background:#fff;color:#172033}}
.priority-won-box{{margin-top:10px;background:#effcf6;color:#172033;padding:12px;border-radius:10px}}
.priority-won-box label{{font-size:12px;font-weight:800}}
.priority-won-box small{{display:block;color:#667085;margin-top:6px}}
.priority-saved{{display:block;color:#8ef0bb;font-size:12px;min-height:14px;margin-top:7px}}
.money-grid{{display:grid;grid-template-columns:1.25fr 1fr 1fr 1fr;gap:10px;margin:18px 0}}
.money-card{{background:#172033;color:#fff;padding:18px;border-radius:16px}}
.money-card.light{{background:#fff;color:#172033;box-shadow:0 5px 18px rgba(0,0,0,.06)}}
.money-card.risk{{background:#fff4ed;color:#9a3412;border:1px solid #fed7aa}}
.money-card span{{display:block;font-size:12px;opacity:.72}}
.money-card strong{{display:block;font-size:27px;margin-top:6px}}
.money-card small{{display:block;margin-top:6px;opacity:.7;line-height:1.3}}

.stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:12px 0 18px}}
.stat{{background:#fff;padding:13px;border-radius:12px;box-shadow:0 4px 14px rgba(0,0,0,.05)}}
.stat b{{display:block;font-size:23px;margin-top:4px}}
.stat span{{font-size:11px;color:#667085}}

.attention{{background:#fff;border-radius:18px;padding:18px;box-shadow:0 7px 24px rgba(0,0,0,.07);margin:16px 0 20px}}
.attention-title{{display:flex;justify-content:space-between;gap:12px;align-items:end;margin-bottom:10px}}
.attention-title h2{{margin:0}}
.attention-title span{{font-size:12px;color:#667085}}
.attention-lead{{display:flex;justify-content:space-between;gap:14px;padding:13px 0;border-top:1px solid #eaecf0}}
.attn-name{{font-weight:800;font-size:16px}}
.attn-meta,.attn-reason{{font-size:12px;color:#667085;margin-top:4px}}
.attn-priority{{font-size:12px;color:#344054;margin-top:5px;font-weight:700}}
.queue-rank{{display:inline-block;background:#172033;color:#fff;border-radius:999px;padding:3px 7px;font-size:11px;vertical-align:2px}}
.attn-reason{{color:#b42318;font-weight:700}}
.attn-value{{text-align:right;min-width:130px}}
.attn-value span{{font-size:10px;text-transform:uppercase;color:#667085}}
.attn-value strong{{display:block;font-size:16px;margin:3px 0 7px}}
.attn-value a{{display:inline-block;background:#172033;color:#fff;text-decoration:none;padding:8px 10px;border-radius:8px;font-size:12px;font-weight:800}}
.attention-empty{{padding:16px;background:#f8fafc;border-radius:10px;color:#667085}}

.section-title{{display:flex;justify-content:space-between;gap:10px;align-items:end;margin:18px 0 10px}}
.section-title h2{{margin:0}}
.section-title span{{font-size:12px;color:#667085}}
.folder-bar{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:10px 0 16px}}
.folder{{border:1px solid #dfe3ea;background:#fff;color:#172033;border-radius:12px;padding:12px 8px;text-align:left;box-shadow:0 3px 10px rgba(0,0,0,.04)}}
.folder span{{display:block;font-size:11px;color:#667085}}
.folder b{{display:block;font-size:22px;margin-top:3px}}
.folder.active{{background:#172033;color:#fff;border-color:#172033}}
.folder.active span{{color:#cbd5e1}}
.folder-heading{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin:8px 0 10px}}
.folder-heading h2{{margin:0}}
.folder-heading span{{font-size:12px;color:#667085;text-align:right}}
.folder-empty{{background:#fff;padding:24px;border-radius:16px;color:#667085;text-align:center}}

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

.opportunity{{margin:14px 0;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:12px}}
.opportunity span,.opportunity small{{display:block;color:#667085;font-size:11px}}
.opportunity strong{{display:block;font-size:22px;color:#05603a;margin:3px 0}}

.details{{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:12px 0}}
.details div{{background:#f8fafc;padding:10px;border-radius:10px;overflow:hidden}}
.details span{{display:block;font-size:11px;color:#667085;margin-bottom:4px}}
.details strong{{font-size:14px;word-break:break-word}}
.message{{border-left:4px solid #172033;background:#f7f9fc;padding:12px;border-radius:8px;line-height:1.4}}

.ai-box{{margin-top:12px;padding:12px;border-radius:12px;background:#eef4ff;border:1px solid #d6e4ff}}
.ai-title{{font-size:12px;color:#475467;font-weight:800;text-transform:uppercase}}
.ai-action{{font-size:13px;color:#475467;margin-top:4px}}
.reason-row{{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}}
.reason-chip{{background:#fff;border:1px solid #dbe3ef;border-radius:999px;padding:5px 8px;font-size:11px;font-weight:700}}
.next-label{{margin-top:10px;font-size:10px;font-weight:900;text-transform:uppercase;color:#667085}}

.followup-banner{{margin:12px 0;padding:10px 12px;border-radius:10px;font-size:12px;font-weight:700}}
.followup-urgent,.followup-overdue{{background:#fee4e2;color:#b42318}}
.followup-soon{{background:#fff0c2;color:#93370d}}
.followup-today,.followup-contacted{{background:#eaf2ff;color:#175cd3}}
.followup-normal,.followup-done{{background:#f2f4f7;color:#344054}}
.followup-booked{{background:#dcfae6;color:#05603a}}

.actions{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}}
.action{{display:block;text-align:center;text-decoration:none;border:1px solid #d0d5dd;color:#172033;padding:11px 8px;border-radius:10px;font-weight:800}}
.action.primary{{background:#172033;color:#fff}}

.status-row{{border-top:1px solid #eaecf0;padding-top:14px}}
.status-row>label{{font-weight:800;font-size:13px}}
.status-actions{{display:grid;grid-template-columns:repeat(5,1fr);gap:5px;margin-top:8px}}
.status-btn{{padding:10px 4px;border:1px solid #d0d5dd;border-radius:9px;background:#fff;color:#344054;font-weight:800;font-size:10px}}
.status-btn.active{{background:#172033;color:#fff;border-color:#172033}}
.won-box{{margin-top:10px;background:#f0fdf4;padding:12px;border-radius:10px}}
.won-box label{{font-size:12px;font-weight:800}}
.won-input{{display:flex;align-items:center;gap:6px;margin-top:6px}}
.won-input input{{width:100%;padding:10px;border:1px solid #d0d5dd;border-radius:8px;font-size:16px}}
.won-input button{{border:0;background:#067647;color:#fff;border-radius:8px;padding:11px 13px;font-weight:800}}
.won-box small{{display:block;color:#667085;margin-top:6px}}
.saved{{display:block;color:#067647;font-size:12px;min-height:14px;margin-top:6px}}
.empty{{background:#fff;padding:25px;border-radius:16px}}

@media(max-width:820px){{
  .money-grid{{grid-template-columns:1fr 1fr}}
}}
@media(max-width:700px){{
  .wrap{{padding:14px}}
  header{{display:block}}
  .toplinks{{margin-top:10px}}
  .toplinks a{{margin:0 10px 0 0}}
  .priority-main{{display:block}}
  .priority-value{{text-align:left;margin-top:14px}}
  .priority-facts{{grid-template-columns:1fr 1fr 1fr}}
  .priority-contact-actions{{grid-template-columns:1fr 1fr 1fr}}
  .priority-status-actions{{grid-template-columns:repeat(3,1fr)}}
  .folder-bar{{grid-template-columns:repeat(3,1fr)}}
  .folder-heading{{display:block}}
  .folder-heading span{{display:block;text-align:left;margin-top:4px}}
  .money-grid{{grid-template-columns:1fr}}
  .stats{{grid-template-columns:repeat(3,1fr)}}
  .leads{{grid-template-columns:1fr}}
  .status-actions{{grid-template-columns:repeat(3,1fr)}}
  .attention-lead{{align-items:flex-start}}
}}
</style></head><body><div class="wrap">

<header>
  <div>
    <h1>Business Lead Inbox</h1>
    <div class="sub">LeadPilot AI · {html.escape(business["name"])}</div>
  </div>
  <div class="toplinks">
    <a href="/b/{business_id}">Customer page</a>
    <a href="/revenue-estimates?business={business_id}">Revenue Estimates</a>
    <a href="/settings?business={business_id}">Settings</a>
    <a href="/businesses">Businesses</a>
    <a href="/logout">Log out</a>
  </div>
</header>

{priority_html}

<div class="money-grid">
  <div class="money-card">
    <span>Open estimated opportunity</span>
    <strong>{money(open_opp_low)}–{money(open_opp_high)}</strong>
    <small>Estimated value of New, Contacted, and Estimate-stage leads.</small>
  </div>

  <div class="money-card risk">
    <span>Potential revenue at risk</span>
    <strong>{money(overdue_opp_low)}–{money(overdue_opp_high)}</strong>
    <small>{overdue_count} overdue lead(s) currently need attention.</small>
  </div>

  <div class="money-card light">
    <span>Actual won revenue</span>
    <strong>{money(won_revenue)}</strong>
    <small>{won_count} won job(s) · avg {money(average_won) if won_count else "$0"}</small>
  </div>

  <div class="money-card light">
    <span>Close rate</span>
    <strong>{conversion_rate:.0f}%</strong>
    <small>Won ÷ completed outcomes (Won + Lost).</small>
  </div>
</div>

<div class="stats">
  <div class="stat"><span>New</span><b>{counts["New"]}</b></div>
  <div class="stat"><span>Contacted</span><b>{counts["Contacted"]}</b></div>
  <div class="stat"><span>Estimate</span><b>{counts["Estimate"]}</b></div>
  <div class="stat"><span>Won</span><b>{counts["Won"]}</b></div>
  <div class="stat"><span>Lost</span><b>{counts["Lost"]}</b></div>
</div>

<div class="attention">
  <div class="attention-title">
    <h2>Needs Attention</h2>
    <span>Next-best opportunities after #1 Priority</span>
  </div>
  {attention_html}
</div>

<div class="section-title">
  <h2>Lead Folders</h2>
  <span>Priority lead stays above · Routing health {routing_metrics["health"]}/100</span>
</div>

<div class="folder-bar">
  <button class="folder active" data-folder="New" onclick="filterLeads('New', this)"><span>New</span><b>{counts["New"]}</b></button>
  <button class="folder" data-folder="Contacted" onclick="filterLeads('Contacted', this)"><span>Contacted</span><b>{counts["Contacted"]}</b></button>
  <button class="folder" data-folder="Estimate" onclick="filterLeads('Estimate', this)"><span>Estimates</span><b>{counts["Estimate"]}</b></button>
  <button class="folder" data-folder="Won" onclick="filterLeads('Won', this)"><span>Won</span><b>{counts["Won"]}</b></button>
  <button class="folder" data-folder="Lost" onclick="filterLeads('Lost', this)"><span>Lost</span><b>{counts["Lost"]}</b></button>
  <button class="folder" data-folder="Open" onclick="filterLeads('Open', this)"><span>All Open</span><b>{open_count}</b></button>
</div>

<div class="folder-heading">
  <h2 id="folder-title">New Leads</h2>
  <span id="folder-note">Untouched leads waiting for first contact</span>
</div>

<div class="leads" id="lead-list">{cards}</div>
<div class="folder-empty" id="folder-empty" style="display:none">No leads in this folder.</div>
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
   const wonbox=document.getElementById('wonbox-'+id);
   if(wonbox) wonbox.style.display=status==='Won'?'block':'none';
   s.textContent='✓ '+status;

   if(status==='Won'){{
     s.textContent='✓ Won — enter final job value below';
   }} else {{
     setTimeout(()=>location.reload(),550);
   }}
 }} else {{
   s.textContent='Could not save';
 }}
}}

function filterLeads(stage, btn){{
 const cards=[...document.querySelectorAll('.lead-card')];
 let shown=0;

 cards.forEach(card=>{{
   const s=card.dataset.stage;
   const match = stage==='Open'
     ? ['New','Contacted','Estimate'].includes(s)
     : s===stage;
   card.style.display=match?'block':'none';
   if(match) shown++;
 }});

 document.querySelectorAll('.folder').forEach(x=>x.classList.remove('active'));
 if(btn) btn.classList.add('active');

 const labels={{
   New:['New Leads','Untouched leads waiting for first contact'],
   Contacted:['Contacted','Customers your team has already reached'],
   Estimate:['Estimates','Jobs where an estimate or quote is in progress'],
   Won:['Won Jobs','Closed business and actual revenue'],
   Lost:['Lost Leads','Closed opportunities that did not convert'],
   Open:['All Open Leads','New + Contacted + Estimate, excluding #1 Priority']
 }};
 const label=labels[stage]||labels.New;
 document.getElementById('folder-title').textContent=label[0];
 document.getElementById('folder-note').textContent=label[1];
 document.getElementById('folder-empty').style.display=shown?'none':'block';
}}

window.addEventListener('DOMContentLoaded',()=>{{
 const first=document.querySelector('.folder[data-folder="New"]');
 filterLeads('New', first);
}});

async function saveValue(id){{
 const s=document.getElementById('saved-'+id);
 const value=document.getElementById('value-'+id).value;
 s.textContent='Saving job value...';

 const r=await fetch('/api/leads/'+id+'/value?business={business_id}',{{
   method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{final_job_value:value}})
 }});

 s.textContent=r.ok?'✓ Job value saved':'Could not save job value';
 if(r.ok) setTimeout(()=>location.reload(),700);
}}
</script>
</body></html>"""

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
            self.send_bytes(coverage_demand_html(message=query.get("message", [""])[0]).encode())

        elif p == "/sms-status":
            if not logged_in(self.headers):
                self.redirect("/login")
                return
            self.send_bytes(sms_status_html().encode())

        elif p == "/revenue-estimates":
            if not logged_in(self.headers):
                self.redirect("/login")
                return
            try:
                business_id = int(query.get("business", [BUSINESS_ID])[0])
            except Exception:
                business_id = BUSINESS_ID
            self.send_bytes(
                revenue_estimates_html(
                    business_id,
                    query.get("message", [""])[0]
                ).encode()
            )

        elif p == "/recruiting":
            if not logged_in(self.headers):
                self.redirect("/login")
                return
            self.send_bytes(
                recruiting_pipeline_html(
                    prefill_service=query.get("service", [""])[0],
                    prefill_city=query.get("city", [""])[0],
                    prefill_count=query.get("count", [""])[0],
                    prefill_county=query.get("county", [""])[0],
                    prefill_zip=query.get("zip", [""])[0],
                    message=query.get("message", [""])[0]
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

    def read_request_data(self):
        """Read either JSON API payloads or standard HTML form submissions."""
        content_type = (self.headers.get("Content-Type", "") or "").lower()
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b""

        if "application/json" in content_type:
            try:
                return json.loads(raw or b"{}")
            except Exception:
                return {}

        try:
            parsed = parse_qs(raw.decode())
            return {k: v[0] for k, v in parsed.items()}
        except Exception:
            return {}

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

            if p == "/coverage-demand/notify":
                if not logged_in(self.headers):
                    self.redirect("/login")
                    return
                form = self.read_form()
                try:
                    waitlist_id = int(form.get("waitlist_id", "0"))
                except Exception:
                    waitlist_id = 0
                ok, result = notify_waitlist_customer(waitlist_id)
                message = (
                    "Customer notification sent."
                    if ok else "Could not notify customer: " + str(result)
                )
                self.redirect("/coverage-demand?message=" + quote(message))
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
                requested_status = form.get("status", "Prospect")
                ok = update_provider_prospect_status(prospect_id, requested_status)
                if ok:
                    self.redirect("/recruiting?message=" + quote("Pipeline stage updated."))
                else:
                    self.redirect("/recruiting?message=" + quote("That stage is locked until required verification is complete."))
                return

            if p == "/recruiting/activate":
                if not logged_in(self.headers):
                    self.redirect("/login")
                    return
                form = self.read_form()
                try:
                    prospect_id = int(form.get("prospect_id", "0"))
                except Exception:
                    prospect_id = 0
                ok, result = activate_provider_prospect(prospect_id)
                if ok:
                    waiting_matches = int(result.get("waiting_matches", 0))
                    message = (
                        f"Provider activated and is now LIVE. "
                        f"{waiting_matches} waiting customer(s) are ready to notify."
                    )
                    self.redirect("/recruiting?message=" + quote(message))
                else:
                    self.redirect("/recruiting?message=" + quote(str(result)))
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

            data = self.read_request_data()

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

                # LEAD INTEGRITY GATE (V17)
                # Re-classify from the customer's actual problem text at the final
                # submission boundary. A confident server classification wins over
                # stale/mutated browser state. If the text is genuinely ambiguous,
                # a specific service already collected in chat may be preserved.
                message = (data.get("message") or "").strip()
                detected_service, detected_urgency = classify(message)

                supplied_service = (data.get("service") or "").strip()
                supplied_urgency = (data.get("urgency") or "").strip()

                valid_services = {"HVAC", "Plumbing", "Electrical", "Roofing", "General Repair"}
                valid_urgencies = {"Normal", "High", "Emergency"}

                if detected_service in valid_services and detected_service != "General Repair":
                    service = detected_service
                elif supplied_service in valid_services:
                    service = supplied_service
                else:
                    service = "General Repair"

                # Urgency is also normalized at the server boundary. Escalation
                # detected from the problem text takes precedence over a stale
                # lower client value. We never silently downgrade Emergency/High.
                urgency_rank = {"Normal": 0, "High": 1, "Emergency": 2}
                supplied_u = supplied_urgency if supplied_urgency in valid_urgencies else "Normal"
                detected_u = detected_urgency if detected_urgency in valid_urgencies else "Normal"
                urgency = detected_u if urgency_rank[detected_u] >= urgency_rank[supplied_u] else supplied_u

                # If this is a contractor-specific page and services are configured,
                # never accept a clearly different trade. This prevents a Roofing
                # request from being silently stored as a Plumbing lead (or vice versa).
                configured_services = [
                    s.strip().lower()
                    for s in str(selected_business.get("services") or "").split(",")
                    if s.strip()
                ]
                if configured_services and service != "General Repair":
                    normalized_service = service.lower()
                    service_allowed = any(
                        normalized_service == s
                        or normalized_service in s
                        or s in normalized_service
                        for s in configured_services
                    )
                    if not service_allowed:
                        self.send_bytes(
                            json.dumps({
                                "error": "service mismatch",
                                "message": f"This business is not configured to receive {service} requests.",
                                "service": service,
                                "urgency": urgency
                            }).encode(),
                            409,
                            "application/json"
                        )
                        return

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

                # Notify the matched business immediately for EVERY new lead.
                # Hot/Strong/Standard wording is handled inside the SMS helper.
                send_new_lead_sms(
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

            if p == "/revenue-estimates":
                if not logged_in(self.headers):
                    self.redirect("/login")
                    return
                try:
                    business_id = int(data.get("business_id", BUSINESS_ID))
                    low = max(0.0, float(data.get("low_value", 0) or 0))
                    high = max(0.0, float(data.get("high_value", 0) or 0))
                except Exception:
                    self.send_bytes(b"Bad pricing values", 400)
                    return
                service = (data.get("service") or "").strip()
                if not service or high < low:
                    self.send_bytes(b"Service required and high value must be >= low value", 400)
                    return
                con = db()
                try:
                    if USE_POSTGRES:
                        execute(con, """INSERT INTO service_pricing(business_id,service,low_value,high_value)
                                        VALUES(?,?,?,?)
                                        ON CONFLICT (business_id,service)
                                        DO UPDATE SET low_value=EXCLUDED.low_value, high_value=EXCLUDED.high_value""",
                                (business_id, service, low, high))
                    else:
                        execute(con, """INSERT OR REPLACE INTO service_pricing(business_id,service,low_value,high_value)
                                        VALUES(?,?,?,?)""", (business_id, service, low, high))
                    con.commit()
                finally:
                    con.close()
                self.redirect(f"/revenue-estimates?business={business_id}&message=Estimate%20range%20saved")
                return

            if p == "/revenue-estimates/delete":
                if not logged_in(self.headers):
                    self.redirect("/login")
                    return
                try:
                    business_id = int(data.get("business_id", BUSINESS_ID))
                except Exception:
                    business_id = BUSINESS_ID
                service = (data.get("service") or "").strip()
                con = db()
                execute(con, "DELETE FROM service_pricing WHERE business_id=? AND service=?", (business_id, service))
                con.commit(); con.close()
                self.redirect(f"/revenue-estimates?business={business_id}&message=Estimate%20range%20removed")
                return

            if p.startswith("/api/leads/") and p.endswith("/value"):
                if not logged_in(self.headers):
                    self.send_bytes(b'{"error":"unauthorized"}', 401, "application/json")
                    return
                parts = p.strip("/").split("/")
                lead_id = int(parts[2])
                try:
                    business_id = int(query.get("business", [BUSINESS_ID])[0])
                    final_value = max(0.0, float(data.get("final_job_value", 0) or 0))
                except Exception:
                    self.send_bytes(b'{"error":"bad value"}', 400, "application/json")
                    return
                con = db()
                cur = execute(con, "UPDATE leads SET final_job_value=? WHERE id=? AND business_id=?",
                              (final_value, lead_id, business_id))
                con.commit(); changed = cur.rowcount; con.close()
                if not changed:
                    self.send_bytes(b'{"error":"lead not found"}', 404, "application/json")
                    return
                self.send_bytes(json.dumps({"ok":True,"id":lead_id,"final_job_value":final_value}).encode(),
                                content_type="application/json")
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

                if status not in ["New", "Contacted", "Estimate", "Won", "Lost"]:
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
            print("ERROR:", repr(e), flush=True)

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
