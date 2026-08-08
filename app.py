import os
import re
import json
import sqlite3
import hashlib
import hmac
import threading
import time
import html
from datetime import datetime
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
                alert_phone TEXT DEFAULT ''
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
                alert_phone TEXT DEFAULT ''
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
        execute(con, "INSERT OR IGNORE INTO businesses(id,name) VALUES(1,?)", (BUSINESS_NAME,))

    # Safe schema upgrades for existing databases.
    if USE_POSTGRES:
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS services TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS service_area TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS email TEXT DEFAULT ''")
        execute(con, "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS alert_phone TEXT DEFAULT ''")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_score INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS qualification TEXT DEFAULT 'Standard'")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS recommended_action TEXT")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS chase_10_sent INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS chase_30_sent INTEGER DEFAULT 0")
    else:
        for sql in [
            "ALTER TABLE businesses ADD COLUMN services TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN service_area TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN email TEXT DEFAULT ''",
            "ALTER TABLE businesses ADD COLUMN alert_phone TEXT DEFAULT ''",
            "ALTER TABLE leads ADD COLUMN lead_score INTEGER DEFAULT 0",
            "ALTER TABLE leads ADD COLUMN qualification TEXT DEFAULT 'Standard'",
            "ALTER TABLE leads ADD COLUMN recommended_action TEXT"
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
        "SELECT id,name,services,service_area,email,alert_phone FROM businesses WHERE id=?",
        (business_id,)
    ).fetchone()
    con.close()

    if not row:
        return {
            "id": business_id,
            "name": BUSINESS_NAME,
            "services": "",
            "service_area": "",
            "email": "",
            "alert_phone": NOTIFY_PHONE
        }

    return {
        "id": row["id"],
        "name": row["name"] or BUSINESS_NAME,
        "services": row["services"] or "",
        "service_area": row["service_area"] or "",
        "email": row["email"] or "",
        "alert_phone": row["alert_phone"] or NOTIFY_PHONE
    }

def save_business_settings(name, services, service_area, email, alert_phone, business_id=BUSINESS_ID):
    con = db()
    execute(
        con,
        "UPDATE businesses SET name=?, services=?, service_area=?, email=?, alert_phone=? WHERE id=?",
        (
            (name or BUSINESS_NAME).strip(),
            (services or "").strip(),
            (service_area or "").strip(),
            (email or "").strip(),
            (alert_phone or "").strip(),
            business_id
        )
    )
    con.commit()
    con.close()

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
input,textarea{{width:100%;padding:13px;border:1px solid #d0d5dd;border-radius:10px;font-size:16px;font-family:inherit}}
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
        "SELECT id,name,services,service_area,email,alert_phone FROM businesses ORDER BY id"
    ).fetchall()
    con.close()
    return rows


def create_business(name, services="", service_area="", email="", alert_phone=""):
    con = db()
    if USE_POSTGRES:
        new_id = execute(con, "SELECT COALESCE(MAX(id),0)+1 AS next_id FROM businesses").fetchone()["next_id"]
    else:
        new_id = execute(con, "SELECT COALESCE(MAX(id),0)+1 AS next_id FROM businesses").fetchone()["next_id"]

    execute(
        con,
        """INSERT INTO businesses(id,name,services,service_area,email,alert_phone)
           VALUES(?,?,?,?,?,?)""",
        (
            int(new_id),
            (name or f"Business {new_id}").strip(),
            (services or "").strip(),
            (service_area or "").strip(),
            (email or "").strip(),
            (alert_phone or "").strip()
        )
    )
    con.commit()
    con.close()
    return int(new_id)


def businesses_html(created_id=None):
    rows = list_businesses()
    items = ""
    for r in rows:
        bid = r["id"]
        items += f"""
        <div class="biz">
          <div><strong>{html.escape(r['name'] or 'Unnamed business')}</strong>
          <span>{html.escape(r['service_area'] or 'No service area yet')}</span></div>
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
<h1>LeadPilot Businesses</h1>
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


def match_business_for_lead(service, location):
    """Resolve Florida geography, then choose an eligible business fairly."""
    resolved = resolve_florida_location(location)
    if not resolved:
        return None, None

    con = db()
    businesses = execute(
        con,
        "SELECT id,name,services,service_area,email,alert_phone FROM businesses ORDER BY id"
    ).fetchall()

    matches = [
        b for b in businesses
        if business_supports_service(b, service)
        and business_serves_location(b, resolved)
    ]

    if not matches:
        con.close()
        return None, resolved

    # Beta fairness: send the next lead to the eligible business with the
    # fewest leads so far. Business ID breaks ties deterministically.
    ranked = []
    for b in matches:
        count_row = execute(
            con,
            "SELECT COUNT(*) AS c FROM leads WHERE business_id=?",
            (b["id"],)
        ).fetchone()
        ranked.append((int(count_row["c"] or 0), int(b["id"]), b))

    con.close()
    ranked.sort(key=lambda x: (x[0], x[1]))
    return ranked[0][2], resolved


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
    matched_business_id = int(context.get("matched_business_id") or 0)
    matched_business_name = (context.get("business_name") or "").strip()

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
            "business_name": ""
        }

    if step == "location":
        location = msg
        matched, resolved = match_business_for_lead(service, location)

        if not resolved:
            return {
                "reply": "I couldn't verify that as a Florida city or ZIP code. Please send a Florida city or 5-digit ZIP code.",
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "location",
                "matched_business_id": 0,
                "customer_zip": ""
            }

        if not matched:
            place = resolved.get("display") or location
            return {
                "reply": f"I recognize {place}, but I don't currently have a {service.lower()} provider covering that area. Try another nearby city or ZIP code, or check back as more businesses join LeadPilot.",
                "service": service,
                "urgency": urgency,
                "issue": issue,
                "intake_step": "location",
                "matched_business_id": 0,
                "customer_zip": resolved.get("postcode") or _extract_zip(location)
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
            "customer_zip": customer_zip
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
            step = "ready"
            reply = f"Perfect. Your {service.lower()} request is ready to send to {matched_business_name}. Tap Send Request below."
        else:
            parsed = _extract_email(msg)
            if not parsed:
                reply = "That doesn't look like an email address. Try again, or type SKIP."
            else:
                customer_email = parsed
                step = "ready"
                reply = f"Perfect. Your {service.lower()} request is ready to send to {matched_business_name}. Tap Send Request below."
    else:
        reply = f"Your request is ready to send to {matched_business_name}."

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
        "business_name": matched_business_name
    }


def classify(text):
    t = text.lower()

    if any(x in t for x in ["ac ", "ac.", "my ac", "a/c", "air condition", "hvac", "heat", "furnace"]):
        service = "HVAC"
    elif any(x in t for x in ["pipe", "plumb", "toilet", "sink", "drain", "water leak"]):
        service = "Plumbing"
    elif any(x in t for x in ["electric", "outlet", "breaker", "power", "wire", "sparking"]):
        service = "Electrical"
    elif any(x in t for x in ["roof", "shingle", "roof leak"]):
        service = "Roofing"
    else:
        service = "General Repair"

    if any(x in t for x in ["gas leak", "smell gas", "sparking", "fire", "flooding", "burst pipe"]):
        urgency = "Emergency"
    elif any(x in t for x in ["today", "asap", "urgent", "right now", "no ac", "no heat"]):
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
        score += 30
    elif urgency_v.lower() == "high":
        score += 20
    else:
        score += 5

    immediate = ("today","right now","asap","immediately","emergency","need someone","send someone","need it fixed","can you come","appointment","schedule","book","quote","estimate")
    research = ("thinking about","later this year","sometime","just curious","price range","researching","considering")
    severe = ("not working","stopped working","no ac","no heat","leaking","burst","flooding","sparking","smell gas","roof leaking","ceiling leaking","won\'t turn on","broken")
    projects = ("replace","replacement","install","installation","new system","new roof","repiping","panel upgrade","water heater","whole house")

    if any(x in t for x in immediate): score += 15
    if any(x in t for x in research): score -= 10
    if any(x in t for x in severe): score += 12
    if any(x in t for x in projects): score += 7
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
    business = get_business_settings(business_id)
    context = context or {}

    business_name = business.get("name") or BUSINESS_NAME
    services_raw = business.get("services") or ""
    service_area = business.get("service_area") or ""
    services = [s.strip() for s in services_raw.split(",") if s.strip()]
    services_lower = [s.lower() for s in services]

    msg = (message or "").strip()
    msg_lower = msg.lower()

    intake_step = (context.get("intake_step") or "").strip()
    customer_name = (context.get("customer_name") or "").strip()
    customer_phone = (context.get("customer_phone") or "").strip()
    customer_email = (context.get("customer_email") or "").strip()
    customer_zip = (context.get("customer_zip") or "").strip()

    if intake_step:
        service0 = context.get("service", "")
        urgency0 = context.get("urgency", "")
        issue0 = context.get("issue", "")

        if intake_step == "name":
            parsed = _extract_name(msg)
            if not parsed:
                reply = "I just need your name first. What name should I put on the request?"
            else:
                customer_name = parsed
                intake_step = "phone"
                reply = f"Thanks, {customer_name}. What's the best phone number for the business to reach you?"

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
                intake_step = "zip"
                reply = "No problem. What's the ZIP code for the job?"
            else:
                parsed = _extract_email(msg)
                if not parsed:
                    reply = "That doesn't look like an email address. Please try again, or type SKIP."
                else:
                    customer_email = parsed
                    intake_step = "zip"
                    reply = "Thanks. What's the ZIP code for the job?"

        elif intake_step == "zip":
            parsed = _extract_zip(msg)
            if not parsed:
                reply = "Please send the 5-digit ZIP code for the job."
            else:
                customer_zip = parsed
                intake_step = "ready"
                reply = (
                    f"Perfect. I have your {service0.lower() or 'service'} request ready for {customer_name}. "
                    "Your information has been filled into the request form below. Tap Submit Request to send it."
                )
        else:
            reply = "Your request is ready to submit."

        return {
            "reply": reply,
            "service": service0,
            "urgency": urgency0,
            "issue": issue0,
            "intake_step": intake_step,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "customer_email": customer_email,
            "customer_zip": customer_zip
        }

    detected_service, detected_urgency = classify(msg)
    prior_service = (context.get("service") or "").strip()
    prior_urgency = (context.get("urgency") or "").strip()
    prior_issue = (context.get("issue") or "").strip()

    # Common location-answer patterns.
    location_phrases = [
        "i'm in ", "im in ", "i am in ", "located in ", "my zip is ",
        "zip is ", "i live in ", "we're in ", "were in ",
        "i'm on ", "im on ", "i am on "
    ]

    looks_like_zip = msg.replace("-", "").isdigit() and 4 <= len(msg.replace("-", "")) <= 10
    looks_like_location_followup = (
        bool(prior_service)
        and (
            any(p in msg_lower for p in location_phrases)
            or looks_like_zip
            or (
                len(msg.split()) <= 5
                and detected_service == "General Repair"
                and detected_urgency == "Normal"
            )
        )
    )

    service = prior_service if looks_like_location_followup and prior_service else detected_service
    urgency = prior_urgency if looks_like_location_followup and prior_urgency else detected_urgency
    issue = prior_issue if looks_like_location_followup and prior_issue else msg

    service_supported = True
    if services and service != "General Repair":
        service_supported = any(
            service.lower() in s or s in service.lower()
            for s in services_lower
        )

    location_question = any(
        phrase in msg_lower
        for phrase in [
            "do you service", "do you serve", "service area", "come to",
            "travel to", "available in", "work in"
        ]
    )

    stated_location = msg
    for prefix in location_phrases:
        pos = msg_lower.find(prefix)
        if pos >= 0:
            stated_location = msg[pos + len(prefix):].strip(" .?!,")
            break

    # Normalize common Florida place-name variations.
    def normalize_place(s):
        s = (s or "").lower().strip()
        replacements = {
            "st. ": "saint ",
            "st ": "saint ",
            "county of ": "",
            "saint johns co": "saint johns county",
            "st johns co": "saint johns county",
        }
        for a, b in replacements.items():
            s = s.replace(a, b)
        s = " ".join(s.split())
        return s

    normalized_area = normalize_place(service_area)
    normalized_location = normalize_place(stated_location)

    # Known place aliases for the first specialty market.
    # This is intentionally explicit and editable rather than pretending
    # we have a full geocoder.
    area_aliases = {
        "saint johns county": [
            "saint augustine",
            "saint augustine beach",
            "elkton",
            "ponte vedra",
            "ponte vedra beach",
            "nocatee",
            "fruit cove",
            "switzerland",
            "hastings",
            "vilano beach",
            "butler beach",
            "crescent beach"
        ],
        "jacksonville": [
            "jacksonville",
            "jacksonville beach",
            "atlantic beach",
            "neptune beach"
        ]
    }

    def location_matches_area(location, area_text):
        if not location or not area_text:
            return False

        if location in area_text:
            return True

        # Match any comma-separated configured area entry.
        configured_parts = [normalize_place(p) for p in area_text.split(",") if p.strip()]
        for part in configured_parts:
            if location == part or location in part or part in location:
                return True

        # Match known towns/cities inside a configured county/metro label.
        for configured_name, aliases in area_aliases.items():
            if configured_name in area_text:
                for alias in aliases:
                    if location == alias or location.startswith(alias + " "):
                        return True

        return False

    if looks_like_location_followup and service_area:
        in_listed_area = location_matches_area(normalized_location, normalized_area)

        if in_listed_area:
            reply = (
                f"Yes — {stated_location} appears to be inside {business_name}'s listed "
                f"service area ({service_area}). Your {service.lower()} request can be "
                "submitted below so the business can follow up."
            )
        else:
            reply = (
                f"{stated_location} does not appear to be inside {business_name}'s listed "
                f"service area ({service_area}). I can still submit your {service.lower()} "
                "request so the business can confirm whether they can travel to you."
            )

    elif location_question and service_area:
        reply = (
            f"{business_name} currently lists its service area as {service_area}. "
            "Tell me your city or ZIP code and I can compare it with the listed area."
        )

    elif not service_supported:
        offered = ", ".join(services)
        reply = (
            f"{business_name} currently lists these services: {offered}. "
            f"Your request sounds like {service}. I can still send the details "
            "to the business so they can confirm whether they can help."
        )

    elif urgency == "Emergency":
        reply = (
            f"This may be an emergency {service.lower()} issue for {business_name}. "
            "If there is fire, a suspected gas leak, dangerous electrical arcing, "
            "or immediate danger, leave the area and contact the appropriate emergency "
            "or utility service. I can still collect your information for urgent follow-up."
        )

    elif urgency == "High":
        reply = (
            f"That sounds like a high-priority {service} request for {business_name}. "
            "Please fill in your contact information below so the business can follow up "
            "as soon as possible."
        )

    else:
        area_note = f" Their listed service area is {service_area}." if service_area else ""
        reply = (
            f"That sounds like a {service} request for {business_name}.{area_note} "
            "I can collect your contact information right here. What's your name?"
        )

    return {
        "reply": reply,
        "service": service,
        "urgency": urgency,
        "issue": issue,
        "business_name": business_name,
        "service_area": service_area,
        "services": services,
        "intake_step": (
            "name"
            if service != "General Repair"
            and not looks_like_location_followup
            and not location_question
            else ""
        ),
        "customer_name": "",
        "customer_phone": "",
        "customer_email": "",
        "customer_zip": ""
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
        for business in list_businesses():
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
<h2>Request service</h2>
<input id="name" placeholder="Name">
<input id="phone" placeholder="Phone">
<input id="email" placeholder="Email">
<input id="zip" placeholder="ZIP code">
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
  marketplace_mode: __MARKETPLACE_MODE__
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
 document.getElementById('details').value=message;
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
 if(zipEl && chatContext.customer_zip) zipEl.value=chatContext.customer_zip;
}

async function submitLead(){
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
   result.textContent='Please enter at least your name and phone number.';
   return;
 }

 const r=await fetch('/api/leads',{
   method:'POST',
   headers:{'Content-Type':'application/json'},
   body:JSON.stringify(data)
 });

 const j=await r.json();

 if(r.ok){
   const businessName = chatContext.business_name || '__BUSINESS_NAME__';
   const firstName = (data.name || '').trim().split(/\s+/)[0] || 'there';
   result.className='success';
   result.textContent =
     `Thanks, ${firstName}. Your ${data.service.toLowerCase()} request has been sent to ${businessName}. ` +
     `They'll contact you as soon as possible.`;

   add(
     `Thanks, ${firstName}. Your request has been sent to ${businessName}. ` +
     `They'll contact you as soon as possible.`,
     'bot'
   );

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
            <div><span>ZIP</span><strong>{r['zip'] or '—'}</strong></div>
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
<a href="/settings?business={business_id}">Settings</a> <a href="/businesses">Businesses</a>
<a href="/logout">Log out</a>
</div>
</header>

<div class="stats">
<div class="stat"><span>New Leads</span><b>{counts.get('New',0)}</b></div>
<div class="stat"><span>Contacted</span><b>{counts.get('Contacted',0)}</b></div>
<div class="stat"><span>Booked</span><b>{counts.get('Booked',0)}</b></div>
<div class="stat"><span>Closed</span><b>{counts.get('Closed',0)}</b></div>
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
                    form.get("name", ""),
                    form.get("services", ""),
                    form.get("service_area", ""),
                    form.get("email", ""),
                    form.get("alert_phone", ""),
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

                con = db()
                now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

                # Always classify on the server from the customer's actual message.
                # This prevents blank/default form fields from turning an HVAC,
                # plumbing, electrical, or roofing lead into "General Repair".
                message = data.get("message") or ""
                detected_service, detected_urgency = classify(message)

                service = detected_service
                urgency = detected_urgency

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
