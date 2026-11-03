#!/usr/bin/env python3
"""
scripts/tools/hardening_smoke.py — controlled Phase-26 smoke test against the live
2-worker deployment. Prints statuses only; never prints token bodies.
Probe accounts are deleted again by scripts/tools/hardening_cleanup.py.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = "http://127.0.0.1:8001"
RESULTS = []


_LAST_SC = ""

def req(method, path, token=None, body=None, headers=None):
    global _LAST_SC
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            _LAST_SC = resp.headers.get("Set-Cookie", "") or ""
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")


SUF = uuid.uuid4().hex[:6]
A = f"hard-a-{SUF}@probe.local"
B = f"hard-b-{SUF}@probe.local"
PW = "Probe-Passw0rd!"


def login(email, pw=PW):
    s, b = req("POST", "/api/auth/login",
               body={"email": email, "password": pw})
    try:
        # Session token lives ONLY in the HttpOnly cookie — read Set-Cookie.
        tok = _LAST_SC.split("nodiq_session=", 1)[1].split(";", 1)[0]
        return s, tok
    except Exception:
        return s, None


sa, _ = req("POST", "/api/auth/signup",
            body={"email": A, "password": PW, "name": "Probe"})
sb, _ = req("POST", "/api/auth/signup",
            body={"email": B, "password": PW, "name": "Probe"})
check("signup A + B", sa in (200, 201) and sb in (200, 201), f"({sa},{sb})")

# 1 anonymous protected endpoint
s1, _ = req("GET", "/api/analyses")
check("1 anonymous /api/analyses -> 401", s1 == 401, str(s1))

# 2 wrong password -> generic 401
s2, b2 = req("POST", "/api/auth/login",
             body={"email": A, "password": "definitely-wrong"})
msg = b2.decode("utf-8", "ignore").lower()
check("2 wrong password -> 401 generic", s2 == 401 and
      "exist" not in msg and ("invalid email or password" in msg
                              or "incorrect" in msg), f"{s2}")

_, tokA = login(A)
_, tokB = login(B)
check("tokens issued", bool(tokA) and bool(tokB))

# 4 logout revocation
s_me, _ = req("GET", "/api/auth/me", token=tokA)
check("4a me before logout -> 200", s_me == 200, str(s_me))
s_lo, _ = req("POST", "/api/auth/logout", token=tokA)
s_after, _ = req("GET", "/api/auth/me", token=tokA)
check("4b logout then me -> 401", s_lo == 200 and s_after == 401,
      f"({s_lo},{s_after})")

# 5 reset flow: response never contains a token
s5, b5 = req("POST", "/api/auth/forgot-password", body={"email": B})
try:
    j5 = json.loads(b5)
except Exception:
    j5 = {}
check("5 forgot response has NO token", s5 == 200 and
      "token" not in json.dumps(j5).lower().replace("emailed", ""), f"{s5}")

# 7/8/9: B creates an analysis; A must not read/modify/delete/replace/report it
s_an, b_an = req("POST", "/api/analyze", token=tokB,
                 body={"dataset_image": "micrograph_0001.png"})
aid = ""
try:
    j_an = json.loads(b_an)
    aid = j_an.get("analysis_id") or j_an.get("id") or \
          j_an.get("analysis", {}).get("id") or ""
except Exception:
    pass
check("7a B analysis created (owner=B)", s_an == 200 and bool(aid),
      f"{s_an} id={'yes' if aid else 'no'}")

# re-login A (A's token died in step 4)
_, tokA = login(A)

if aid:
    s_rd, _ = req("GET", f"/api/analyses/{aid}", token=tokA)
    check("7b A read B's analysis -> 404", s_rd == 404, str(s_rd))
    s_mod, _ = req("POST", f"/api/analyses/{aid}/lot",
                   token=tokA, body={"lot_id": "X"})
    check("8 A modify B's analysis -> 404", s_mod == 404, str(s_mod))
    s_del, _ = req("DELETE", f"/api/analyses/{aid}", token=tokA)
    check("9 A delete B's analysis -> 404", s_del == 404, str(s_del))
    s_rep, _ = req("POST", "/api/analyses", token=tokA,
                   body={"id": aid, "filename": "hijack.png"})
    check("9b A POST-replace B's id -> 409", s_rep == 409, str(s_rep))
    s_rg, b_rg = req("POST", "/api/reports/generate", token=tokA,
                     body={"analysis_id": aid})
    # 400 'no analyses to report on' IS isolation: A's request must resolve
    # zero of B's records; 404 = record-level scope, 400 = empty scope
    check("9c A generate report from B -> 400/404 (no B rows)",
          s_rg in (400, 404), f"{s_rg}")

# 10b copilot memory isolation (same session id for both users)
sid = f"shared-{SUF}"
s_ca, _ = req("POST", "/api/copilot", token=tokA,
              body={"message": "hello", "session_id": sid})
s_cb, _ = req("POST", "/api/copilot", token=tokB,
              body={"message": "hello", "session_id": sid})
print(f"INFO  copilot turns for A,B: ({s_ca},{s_cb}) "
      f"(file-level isolation proven in-container separately)")

# 11 path traversal on the dataset file route (regex-gated)
for evil in ("../../server_data/nodiq.db", "..%2f..%2f.env",
             "micrograph_0001.png%00.png", "micrograph_0001.png/../../x",
             "....//server_data/nodiq.db", "%2e%2e%2f%2e%2e%2fnodiq.db"):
    s_t, _ = req("GET",
                 f"/api/dataset/file/{urllib.parse.quote(evil, safe='')}",
                 token=tokB)
    check(f"11 traversal rejected: {evil[:28]}", s_t in (400, 403, 404),
          str(s_t))
# positive control: legitimate names still serve (no over-blocking)
s_ok, _ = req("GET", "/api/dataset/file/micrograph_0001.png", token=tokB)
check("11b legit dataset image still -> 200", s_ok == 200, str(s_ok))

# 3 rate limit LAST (it exhausts this IP's login bucket)
codes = []
for i in range(14):
    s, _ = req("POST", "/api/auth/login",
               body={"email": f"rl-{i}@probe.local", "password": "x"})
    codes.append(s)
check("3 rate limit -> 429 (2 workers, shared budget)", 429 in codes,
      f"tail={codes[-3:]}")

# 15 CORS
s_c, _, h_c = None, None, {}
r = urllib.request.Request(BASE + "/api/health",
                           headers={"Origin": "http://evil.example"})
try:
    with urllib.request.urlopen(r, timeout=15) as resp:
        h_c = dict(resp.headers)
except urllib.error.HTTPError as e:
    h_c = dict(e.headers)
acao = h_c.get("Access-Control-Allow-Origin", "")
check("15 CORS: evil origin not reflected", acao != "*" and
      "evil" not in acao, repr(acao))

# 16 security headers
check("16 security headers present",
      all(k in h_c for k in ("X-Content-Type-Options", "X-Frame-Options",
                             "Referrer-Policy",
                             "Content-Security-Policy")))

print("\nSummary:", sum(1 for _, ok, _ in RESULTS if ok), "/",
      len(RESULTS), "checks passed")
bad = [n for n, ok, _ in RESULTS if not ok]
print("FAILED:" if bad else "ALL GREEN", *bad)
