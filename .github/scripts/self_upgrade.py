"""CI: TailorbirdCV upgrades itself (Applications banner → Upgrade), scripted against the API.

Expects TailorbirdCV <old> installed by name with the one-line installer from a local package folder (UV_FIND_LINKS)
that also holds <new>. Serves a PyPI-like answer announcing <new> (TAILORBIRDCV_UPDATE_URL points here), starts
`tailorbirdcv serve`, asks it to upgrade, and waits until <new> answers on the same port and reports a successful upgrade.
Usage: self_upgrade.py <tailorbirdcv executable> <data folder> <old> <new>
"""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8011
exe, data, old, new = sys.argv[1], Path(sys.argv[2]).resolve(), sys.argv[3], sys.argv[4]


def call(method: str, path: str) -> dict:
    key = (data / ".access-key").read_text(encoding="utf-8").strip()
    cookie = "tailorbirdcv_key_" + hashlib.sha256(str(data).encode()).hexdigest()[:10]
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api{path}", method=method, data=b"" if method == "POST" else None,
                                 headers={"Cookie": f"{cookie}={key}", "X-TailorbirdCV": "1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wait_for(check, what: str, seconds: float):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (urllib.error.URLError, ConnectionError, OSError, ValueError):
            pass  # restarting
        time.sleep(1)
    stop()
    sys.exit(f"timed out waiting for {what}\n--- tailorbirdcv serve output ---\n{LOG.read_text(errors='replace')[-4000:]}")


def stop():
    """Stop TailorbirdCV: on POSIX it's still our child (the upgrade re-execs in place); on Windows the upgraded copy
    runs in the helper's new console, so stop it by name."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/IM", "tailorbirdcv.exe"], capture_output=True)
    server.terminate()


class Feed(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"info": {"version": new}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


feed = ThreadingHTTPServer(("127.0.0.1", 0), Feed)
threading.Thread(target=feed.serve_forever, daemon=True).start()
os.environ["TAILORBIRDCV_UPDATE_URL"] = f"http://127.0.0.1:{feed.server_port}/pypi/tailorbirdcv/json"
LOG = data / "serve.log"
with open(LOG, "w") as log:  # never our stdout: the server outlives this script's pipe otherwise
    server = subprocess.Popen([exe, "serve", "--port", str(PORT), "--no-browser"], stdin=subprocess.DEVNULL,
                              stdout=log, stderr=subprocess.STDOUT)
status = wait_for(lambda: call("GET", "/update"), "TailorbirdCV to start", 60)
print("before:", status)
assert status["current"] == old and status["latest"] == new and status["newer"], status
assert status["kind"] == "uv-tool", status
print("upgrade:", call("POST", "/update/upgrade"))
after = wait_for(lambda: (s := call("GET", "/update"))["current"] == new and s, f"TailorbirdCV {new} to answer", 300)
print("after:", after)
assert after["last_upgrade"] and after["last_upgrade"]["ok"] and after["last_upgrade"]["target"] == new, after
assert not after["newer"], after
print(f"TailorbirdCV upgraded itself from {old} to {new} and answers on port {PORT} again.")
print("--- tailorbirdcv serve output ---", LOG.read_text(errors="replace")[-3000:], sep="\n")
stop()
