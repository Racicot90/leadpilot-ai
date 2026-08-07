import os
import json
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "5000"))
DB = "leadpilot.db"
BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "LeadPilot Demo Services")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS leads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT,
            phone TEXT,
            email TEXT,
            zip TEXT,
            service TEXT,
            urgency TEXT,
            message TEXT,
            status TEXT DEFAULT 'New'
        )
    """)
    con.commit()
    con.close()

def classify(text):
    t = text.lower()
    if any(x in t for x in ["ac ", "a/c", "air condition", "hvac", "heat", "furnace"]):
        service = "HVAC"
    elif any(x in t for x in ["pipe", "plumb", "toilet", "sink", "drain", "water leak"]):
        service = "Plumbing"
    elif any(x in t for x in ["electric", "outlet", "breaker", "power", "wire", "sparking"]):
        service = "Electrical"
    else:
        service = "General Repair"

    if any(x in t for x in ["gas leak", "smell gas", "sparking", "fire", "flooding", "burst pipe"]):
        urgency = "Emergency"
    elif any(x in t for x in ["today", "asap", "urgent", "right now", "no ac", "no heat"]):
        urgency = "High"
    else:
        urgency = "Normal"
    return service, urgency

def assistant_reply(message):
    service, urgency = classify(message)
    if urgency == "Emergency":
        return {
            "reply": "This may be an emergency. If there is fire, a suspected gas leak, dangerous electrical arcing, or immediate danger, leave the area and contact the appropriate emergency or utility service. I can still collect your information so the business can follow up.",
            "service": service,
            "urgency": urgency
        }
    return {
        "reply": f"That sounds like a {service} request. I can help get this over to the service team. Please fill in your contact information below and they can follow up with you.",
        "service": service,
        "urgency": urgency
    }

INDEX = r"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot AI</title>
<style>
body{font-family:Arial,sans-serif;margin:0;background:#f4f7fb;color:#172033}
.wrap{max-width:720px;margin:auto;padding:24px}
.card{background:white;border-radius:18px;padding:22px;box-shadow:0 8px 30px rgba(0,0,0,.08);margin-bottom:18px}
h1{margin:0 0 8px;font-size:30px}.muted{color:#667085}
.chat{min-height:180px;background:#f7f9fc;border-radius:14px;padding:14px;overflow:auto}
.msg{padding:10px 12px;border-radius:12px;margin:8px 0;max-width:85%}
.bot{background:#e9eefb}.user{background:#172033;color:white;margin-left:auto}
.row{display:flex;gap:8px;margin-top:12px}
input,textarea,button,select{font:inherit}
input,textarea,select{width:100%;box-sizing:border-box;padding:12px;border:1px solid #d0d5dd;border-radius:10px;margin:6px 0}
button{padding:12px 16px;border:0;border-radius:10px;background:#172033;color:white;font-weight:700}
button:hover{opacity:.9}.success{color:#067647;font-weight:bold}
a{color:#3448c5}
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
<div class="msg bot">Hi! Tell me what you need help with. For example: “My AC stopped working and I need someone tomorrow.”</div>
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
<strong>Business owner?</strong> <a href="/dashboard">Open lead dashboard</a>
</div>
</div>
<script>
function add(text,cls){
 const c=document.getElementById('chat');
 const d=document.createElement('div'); d.className='msg '+cls; d.textContent=text; c.appendChild(d);
 c.scrollTop=c.scrollHeight;
}
async function sendChat(){
 const el=document.getElementById('message'); const message=el.value.trim(); if(!message)return;
 add(message,'user'); document.getElementById('details').value=message; el.value='';
 const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})});
 const j=await r.json(); add(j.reply,'bot'); document.getElementById('service').value=j.service; document.getElementById('urgency').value=j.urgency;
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
 if(!data.name || !data.phone){ result.textContent='Please enter at least your name and phone number.'; return; }
 const r=await fetch('/api/leads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const j=await r.json(); result.className='success'; result.textContent='Request received! Lead #'+j.id+' has been created.';
}
</script>
</body>
</html>"""

def dashboard_html():
    con = db()
    rows = con.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    con.close()

    counts = {"New":0, "Contacted":0, "Booked":0, "Closed":0}
    for r in rows:
        counts[r["status"] or "New"] = counts.get(r["status"] or "New", 0) + 1

    cards = ""
    for r in rows:
        phone = (r["phone"] or "").strip()
        email = (r["email"] or "").strip()
        status = r["status"] or "New"
        urgency = r["urgency"] or "Normal"
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
            <span class="badge urgency-{urgency.lower()}">{urgency}</span>
          </div>

          <div class="details">
            <div><span>Service</span><strong>{r['service'] or 'General Repair'}</strong></div>
            <div><span>ZIP</span><strong>{r['zip'] or '—'}</strong></div>
            <div><span>Phone</span><strong>{phone or '—'}</strong></div>
            <div><span>Email</span><strong>{email or '—'}</strong></div>
          </div>

          <div class="message">{r['message'] or 'No message provided.'}</div>

          <div class="actions">
            <a class="action primary" href="tel:{phone}">📞 Call</a>
            <a class="action" href="sms:{phone}">💬 Text</a>
            <a class="action" href="mailto:{email}">✉️ Email</a>
          </div>

          <div class="status-row">
            <label for="status-{r['id']}">Lead status</label>
            <select id="status-{r['id']}" onchange="updateStatus({r['id']}, this.value)">
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
h1{{font-size:28px;margin:0}} .sub{{color:#667085;margin-top:5px}}
.back{{text-decoration:none;color:#3448c5;font-weight:700}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}}
.stat{{background:#fff;padding:16px;border-radius:14px;box-shadow:0 5px 18px rgba(0,0,0,.06)}}
.stat b{{display:block;font-size:27px;margin-top:5px}}
.stat span{{font-size:13px;color:#667085}}
.leads{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.lead-card{{background:white;border-radius:18px;padding:18px;box-shadow:0 7px 24px rgba(0,0,0,.07)}}
.lead-top{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}
.lead-name{{font-size:21px;font-weight:800}} .lead-time{{font-size:12px;color:#667085;margin-top:5px}}
.badge{{padding:7px 10px;border-radius:999px;font-size:12px;font-weight:800;background:#eef2f6}}
.urgency-emergency{{background:#fee4e2;color:#b42318}} .urgency-high{{background:#fff0c2;color:#93370d}}
.details{{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:16px 0}}
.details div{{background:#f8fafc;padding:10px;border-radius:10px;overflow:hidden}}
.details span{{display:block;font-size:11px;color:#667085;margin-bottom:4px}}
.details strong{{font-size:14px;word-break:break-word}}
.message{{border-left:4px solid #172033;background:#f7f9fc;padding:12px;border-radius:8px;line-height:1.4}}
.actions{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}}
.action{{display:block;text-align:center;text-decoration:none;border:1px solid #d0d5dd;color:#172033;padding:11px 8px;border-radius:10px;font-weight:800}}
.action.primary{{background:#172033;color:#fff;border-color:#172033}}
.status-row{{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:9px;border-top:1px solid #eaecf0;padding-top:14px}}
.status-row label{{font-size:13px;font-weight:700}}
select{{width:100%;padding:10px;border:1px solid #d0d5dd;border-radius:9px;background:white}}
.saved{{grid-column:1/-1;color:#067647;font-size:12px;min-height:14px}}
.empty{{background:white;padding:25px;border-radius:16px}}
@media(max-width:700px){{
 .wrap{{padding:14px}} header{{display:block}} .back{{display:inline-block;margin-top:10px}}
 .stats{{grid-template-columns:1fr 1fr}} .leads{{grid-template-columns:1fr}}
 h1{{font-size:25px}}
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div><h1>LeadPilot AI — Lead Dashboard</h1><div class="sub">{BUSINESS_NAME}</div></div>
  <a class="back" href="/">← Customer page</a>
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
async function updateStatus(id, status) {{
  const saved = document.getElementById('saved-' + id);
  saved.textContent = 'Saving...';
  const r = await fetch('/api/leads/' + id + '/status', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{status}})
  }});
  if (r.ok) {{
    saved.textContent = '✓ Saved';
    setTimeout(() => location.reload(), 500);
  }} else {{
    saved.textContent = 'Could not save';
  }}
}}
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, data, status=200, content_type="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/":
            self.send_bytes(INDEX.encode())
        elif p == "/dashboard":
            self.send_bytes(dashboard_html().encode())
        elif p == "/health":
            self.send_bytes(b'{"ok":true}', content_type="application/json")
        else:
            self.send_bytes(b"Not found", 404, "text/plain")

    def read_json(self):
        n = int(self.headers.get("Content-Length","0"))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            data = self.read_json()

            if p == "/api/chat":
                out = assistant_reply(data.get("message",""))
                self.send_bytes(json.dumps(out).encode(), content_type="application/json")
                return

            if p == "/api/leads":
                con = db()
                cur = con.execute("""INSERT INTO leads(created_at,name,phone,email,zip,service,urgency,message,status)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (datetime.now().strftime("%Y-%m-%d %H:%M"),data.get("name"),data.get("phone"),
                     data.get("email"),data.get("zip"),data.get("service"),data.get("urgency"),
                     data.get("message"),"New"))
                con.commit()
                lead_id = cur.lastrowid
                con.close()
                self.send_bytes(json.dumps({"ok":True,"id":lead_id}).encode(), content_type="application/json")
                return

            if p.startswith("/api/leads/") and p.endswith("/status"):
                parts = p.strip("/").split("/")
                lead_id = int(parts[2])
                status = data.get("status","")
                if status not in ["New","Contacted","Booked","Closed"]:
                    self.send_bytes(b'{"error":"bad status"}',400,"application/json")
                    return

                con = db()
                cur = con.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
                con.commit()
                changed = cur.rowcount
                con.close()

                if not changed:
                    self.send_bytes(b'{"error":"lead not found"}',404,"application/json")
                    return

                self.send_bytes(json.dumps({"ok":True,"id":lead_id,"status":status}).encode(), content_type="application/json")
                return

            self.send_bytes(b'{"error":"not found"}',404,"application/json")

        except Exception as e:
            self.send_bytes(json.dumps({"error":str(e)}).encode(),500,"application/json")

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format%args))

if __name__ == "__main__":
    init_db()
    print(f"LeadPilot AI V1 dashboard upgrade running on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
