import os
import json
import sqlite3
import hashlib
import hmac
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode
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
                name TEXT NOT NULL
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
            ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name
        """, (BUSINESS_NAME,))
    else:
        execute(con, """
            CREATE TABLE IF NOT EXISTS businesses(
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
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
        execute(con, "INSERT OR REPLACE INTO businesses(id,name) VALUES(1,?)", (BUSINESS_NAME,))

    # Safe schema upgrades for existing databases.
    if USE_POSTGRES:
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_score INTEGER DEFAULT 0")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS qualification TEXT DEFAULT 'Standard'")
        execute(con, "ALTER TABLE leads ADD COLUMN IF NOT EXISTS recommended_action TEXT")
    else:
        for sql in [
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
    """LeadPilot Qualification V1: fast, explainable scoring from 0-100."""
    score = 35
    reasons = []
    t = (message or "").lower()

    if urgency == "Emergency":
        score += 35
        reasons.append("emergency language")
    elif urgency == "High":
        score += 22
        reasons.append("same-day / urgent need")
    else:
        score += 8

    if phone:
        score += 10
        reasons.append("phone provided")
    if email:
        score += 5
    if zip_code:
        score += 5

    if service in ["HVAC", "Plumbing", "Electrical", "Roofing"]:
        score += 8
        reasons.append("clear service category")

    high_intent_terms = [
        "today", "tomorrow", "asap", "need someone", "need it fixed",
        "stopped working", "not working", "leaking", "no ac", "no heat",
        "burst", "flood", "sparking", "estimate", "quote", "appointment"
    ]
    matches = sum(1 for term in high_intent_terms if term in t)
    score += min(matches * 4, 16)

    if len((message or "").strip()) >= 25:
        score += 4

    score = max(0, min(score, 100))

    if score >= 85:
        qualification = "Hot"
        action = "Call immediately. This lead shows strong urgency and buying intent."
    elif score >= 70:
        qualification = "Strong"
        action = "Contact within 5-10 minutes and try to book the job."
    elif score >= 50:
        qualification = "Qualified"
        action = "Contact soon, confirm job details, and offer the next available appointment."
    else:
        qualification = "Standard"
        action = "Follow up, confirm the scope of work, and qualify timing and budget."

    return {
        "lead_score": score,
        "qualification": qualification,
        "recommended_action": action,
        "score_reasons": reasons
    }

def assistant_reply(message):
    service, urgency = classify(message)

    if urgency == "Emergency":
        reply = (
            "This may be an emergency. If there is fire, a suspected gas leak, "
            "dangerous electrical arcing, or immediate danger, leave the area and "
            "contact the appropriate emergency or utility service. I can still "
            "collect your information so the business can follow up."
        )
    else:
        reply = (
            f"That sounds like a {service} request. I can help get this over to "
            "the service team. Please fill in your contact information below and "
            "they can follow up with you."
        )

    return {"reply": reply, "service": service, "urgency": urgency}


def send_hot_lead_sms(lead_id, name, phone, service, urgency, message, qualification):
    """Send a concise SMS alert for Hot leads. Failures never block lead creation."""
    if qualification.get("qualification") != "Hot":
        return False

    if not all([
        NOTIFY_PHONE,
        TWILIO_PHONE_NUMBER,
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN
    ]):
        print("SMS skipped: Twilio environment variables are incomplete.", flush=True)
        return False

    preview = " ".join((message or "").split())
    if len(preview) > 120:
        preview = preview[:117] + "..."

    body = (
        f"🔥 HOT LEAD #{lead_id} — {service} — "
        f"{qualification.get('lead_score', 0)}/100 — {urgency}. "
        f"{name or 'Unnamed'} | {phone or 'No phone'}. "
        f"{preview}"
    )

    endpoint = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Messages.json"
    )

    payload = urlencode({
        "To": NOTIFY_PHONE,
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
            ok = 200 <= getattr(resp, "status", 0) < 300
            print("Twilio SMS:", "sent" if ok else f"status {getattr(resp, 'status', '?')}", flush=True)
            return ok
    except Exception as e:
        detail = ""
        try:
            if hasattr(e, "read"):
                detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
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
   body:JSON.stringify({message})
 });

 const j=await r.json();

 add(j.reply,'bot');
 document.getElementById('service').value=j.service;
 document.getElementById('urgency').value=j.urgency;
}

async function submitLead(){
 const data={
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
   result.className='success';
   result.textContent='Request received! Lead #'+j.id+' has been created.';
 } else {
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

def dashboard_html():
    con = db()

    rows = execute(
        con,
        "SELECT * FROM leads WHERE business_id=? ORDER BY id DESC",
        (BUSINESS_ID,)
    ).fetchall()

    con.close()

    counts = {"New":0, "Contacted":0, "Booked":0, "Closed":0}

    for r in rows:
        status = r["status"] or "New"
        counts[status] = counts.get(status, 0) + 1

    cards = ""

    for r in rows:
        phone = (r["phone"] or "").strip()
        email = (r["email"] or "").strip()
        status = r["status"] or "New"
        urgency = r["urgency"] or "Normal"
        lead_score = r["lead_score"] or 0
        qualification = r["qualification"] or "Standard"
        recommended_action = r["recommended_action"] or "Follow up and confirm the job details."

        options = "".join(
            f'<option value="{s}" {"selected" if s == status else ""}>{s}</option>'
            for s in ["New","Contacted","Booked","Closed"]
        )

        cards += f"""
        <section class="lead-card">
          <div class="lead-top">
            <div>
              <div class="lead-name">{r['name'] or 'Unnamed lead'}</div>
              <div class="lead-time">{r['created_at']}</div>
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
            <div class="ai-action">{recommended_action}</div>
          </div>

          <div class="actions">
            <a class="action primary" href="tel:{phone}">📞 Call</a>
            <a class="action" href="sms:{phone}">💬 Text</a>
            <a class="action" href="mailto:{email}">✉️ Email</a>
          </div>

          <div class="status-row">
            <label>Lead status</label>
            <select onchange="updateStatus({r['id']}, this.value)">
              {options}
            </select>
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
.actions{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}}
.action{{display:block;text-align:center;text-decoration:none;border:1px solid #d0d5dd;color:#172033;padding:11px 8px;border-radius:10px;font-weight:800}}
.action.primary{{background:#172033;color:#fff;border-color:#172033}}
.status-row{{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:9px;border-top:1px solid #eaecf0;padding-top:14px}}
select{{width:100%;padding:10px;border:1px solid #d0d5dd;border-radius:9px;background:#fff}}
.saved{{grid-column:1/-1;color:#067647;font-size:12px;min-height:14px}}
.empty{{background:#fff;padding:25px;border-radius:16px}}

@media(max-width:700px){{
 .wrap{{padding:14px}}
 header{{display:block}}
 .toplinks{{margin-top:10px}}
 .toplinks a{{margin:0 12px 0 0}}
 .stats{{grid-template-columns:1fr 1fr}}
 .leads{{grid-template-columns:1fr}}
 h1{{font-size:25px}}
}}
</style>
</head>
<body>

<div class="wrap">

<header>
<div>
<h1>LeadPilot AI — Lead Dashboard</h1>
<div class="sub">{BUSINESS_NAME}</div>
</div>

<div class="toplinks">
<a href="/">Customer page</a>
<a href="/logout">Log out</a>
</div>
</header>

<div class="stats">
<div class="stat"><span>New Leads</span><b>{counts.get('New',0)}</b></div>
<div class="stat"><span>Contacted</span><b>{counts.get('Contacted',0)}</b></div>
<div class="stat"><span>Booked</span><b>{counts.get('Booked',0)}</b></div>
<div class="stat"><span>Closed</span><b>{counts.get('Closed',0)}</b></div>
</div>

<div class="leads">{cards}</div>

</div>

<script>
async function updateStatus(id,status){{
 const s=document.getElementById('saved-'+id);
 s.textContent='Saving...';

 const r=await fetch('/api/leads/'+id+'/status',{{
   method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{status}})
 }});

 if(r.ok){{
   s.textContent='✓ Saved';
   setTimeout(()=>location.reload(),400);
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
        p = urlparse(self.path).path

        if p == "/":
            self.send_bytes(INDEX.encode())

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

            self.send_bytes(dashboard_html().encode())

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
        p = urlparse(self.path).path

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

            data = self.read_json()

            if p == "/api/chat":
                out = assistant_reply(data.get("message", ""))

                self.send_bytes(
                    json.dumps(out).encode(),
                    content_type="application/json"
                )

                return

            if p == "/api/leads":
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
                            BUSINESS_ID,
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
                            BUSINESS_ID,
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
                    qualification
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
                    (status, lead_id, BUSINESS_ID)
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

    print(
        "LeadPilot AI running on "
        f"http://{HOST}:{PORT} using "
        f"{'Postgres' if USE_POSTGRES else 'SQLite'}"
    )

    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
