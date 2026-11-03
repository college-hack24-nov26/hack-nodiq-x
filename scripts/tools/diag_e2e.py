#!/usr/bin/env python3
"""In-container diagnostic: correlate API poll state with direct PG reads
during one analysis to pin down the empty-payload 'completed' anomaly."""
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "/app")
os.environ.setdefault("NODIQ_BACKEND", "supabase")
import nodiq.services.context as context_svc  # noqa: E402
import nodiq.services.db as store             # noqa: E402

BASE = "http://127.0.0.1:8001"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def req2(method, path, data=None, hdrs=None):
    r = urllib.request.Request(BASE + path, method=method, data=data,
                               headers=hdrs or ({"Content-Type": "application/json"}
                                                if data else {}))
    try:
        resp = op.open(r, timeout=120)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


s, b = req2("POST", "/api/auth/signup",
            json.dumps({"email": f"diag4-{uuid.uuid4().hex[:6]}@test.local",
                        "password": "password1", "name": "D4"}).encode())
print("signup:", s)

boundary = uuid.uuid4().hex
from nodiq.core.config import WEB_DIR
img = (WEB_DIR / "public" / "dataset" / "micrograph_0001.png").read_bytes()
parts = [
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
    f"filename=\"d.png\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode(),
    img,
    f"\r\n--{boundary}--\r\n".encode(),
]
s, b = req2("POST", "/api/analyze", b"".join(parts),
            hdrs={"Content-Type": f"multipart/form-data; boundary={boundary}"})
if s != 202:
    print("analyze:", s, b[:200]); sys.exit(1)
aid = json.loads(b)["analysis_id"]
print("analysis:", aid)

t0 = time.time()
prev = None
while time.time() - t0 < 150:
    s, b = req2("GET", f"/api/analyses/{aid}")
    d = json.loads(b)
    st = d.get("status") or d.get("record", {}).get("status")
    api_full = bool(d.get("analysis"))
    # direct read: ensure the pool connection is open, then read directly
    store.init_db()
    with store._LOCK:
        row = store._CONN.execute(
            "SELECT payload FROM full_payloads WHERE id = ?", (aid,)).fetchone()
    db_has = row is not None
    cur = (st, api_full, db_has)
    if cur != prev:
        print(f"t={round(time.time()-t0,1)}s api_status={st} "
              f"api_payload={api_full} db_payload={db_has}")
        prev = cur
    if st == "completed":
        if not api_full and db_has:
            print(">>> API served completed-empty WHILE direct PG read sees the row")
            # retry the exact cache path a few times: does it stay empty?
            for i in range(3):
                p = context_svc.load_full_analysis(aid)
                print(f"    load_full_analysis retry {i+1}: "
                      f"{'payload, iso=' + str(p.get('iso_nodularity_pct')) if p else 'None'}")
                time.sleep(1)
        elif not api_full and not db_has:
            print(">>> PG genuinely empty at that moment (write lag)")
        else:
            print("payload present — no anomaly this run")
        break
    time.sleep(0.4)
