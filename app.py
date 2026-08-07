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
 const data={name:document.getElementById('name').value,phone:document.getElementById('phone').value,email:document.getElementById('email').value,zip:document.getElementById('zip').value,service:document.getElementById('service').value||'General Repair',urgency:document.getElementById('urgency').value||'Normal',message:document.getElementById('details').value};
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
    body = ""
    for r in rows:
        body += f"""<tr>
<td>{r['id']}</td><td>{r['created_at']}</td><td>{r['name'] or ''}</td>
<td>{r['phone'] or ''}</td><td>{r['service'] or ''}</td><td>{r['urgency'] or ''}</td>
<td>{r['status'] or ''}</td><td>{r['message'] or ''}</td></tr>"""
    if not body:
        body = "<tr><td colspan='8'>No leads yet. Submit a test lead from the customer page.</td></tr>"
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadPilot Dashboard</title><style>
body{{font-family:Arial;margin:0;background:#f4f7fb;color:#172033}}.wrap{{padding:20px;overflow:auto}}
table{{border-collapse:collapse;width:100%;background:white}}th,td{{padding:10px;border:1px solid #ddd;text-align:left;white-space:nowrap}}
a{{color:#3448c5}}</style></head><body><div class="wrap">
<h1>{BUSINESS_NAME} — Lead Dashboard</h1><p><a href="/">← Customer page</a></p>
<table><tr><th>ID</th><th>Created</th><th>Name</th><th>Phone</th><th>Service</th><th>Urgency</th><th>Status</th><th>Message</th></tr>
{body}</table></div></body></html>"""

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
                con.commit(); lead_id = cur.lastrowid; con.close()
                self.send_bytes(json.dumps({"ok":True,"id":lead_id}).encode(), content_type="application/json")
                return
            self.send_bytes(b'{"error":"not found"}',404,"application/json")
        except Exception as e:
            self.send_bytes(json.dumps({"error":str(e)}).encode(),500,"application/json")

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format%args))

if __name__ == "__main__":
    init_db()
    print(f"LeadPilot AI V1 single-file running on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
