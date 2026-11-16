"""A loopback RomM that speaks the parts of its API the extras module uses.

Shaped after RomM's own handlers (chunked upload with a target folder, per-category delete), written by
hand: nothing here is saved from a live server.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "SECRET-bearer-extras-77c2"
PASSWORD = "hunter2-extras-password"
DOC_EXT = {".pdf", ".md", ".txt"}


class FakeRomm2:
    """`files` maps rom id -> {file_id: {"file_name", "category", "data"}}."""

    def __init__(self):
        self.rom = {"id": 42, "platform_id": 7, "fs_name": "Chrono Trigger", "has_multiple_files": True,
                    "has_manual": False, "path_manual": None}
        self.files: dict[int, dict[int, dict]] = {42: {}}
        self.requests: list[tuple[str, str, dict, bytes]] = []
        self.next_id = 500
        self.sessions: dict[str, dict] = {}
        self.refuse_names: set[str] = set()      # `start` answers 409
        self.deny_delete = False                 # DELETE answers 403
        self.fail_chunk_once = False
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, body=b"{}", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                hdr = {k.lower(): v for k, v in self.headers.items()}
                outer.requests.append((method, self.path, hdr, body))
                if self.path == "/api/token":
                    return self._reply(200, json.dumps({"access_token": TOKEN}).encode())
                if hdr.get("authorization") != "Bearer " + TOKEN:
                    return self._reply(401, b'{"detail":"bad token"}')
                m = re.fullmatch(r"/api/roms/(\d+)", self.path)
                if m and method == "GET":
                    rid = int(m.group(1))
                    rom = dict(outer.rom, id=rid, files=[
                        {"id": fid, "file_name": f["file_name"], "category": f["category"],
                         "file_size_bytes": len(f["data"])} for fid, f in outer.files.get(rid, {}).items()])
                    return self._reply(200, json.dumps(rom).encode())
                if self.path == "/api/roms/upload/start" and method == "POST":
                    t = json.loads(body or b"{}")
                    name, folder = t.get("filename", ""), t.get("folder", "")
                    if name in outer.refuse_names:
                        return self._reply(409, b'{"detail":"exists"}')
                    if folder == "manual" and os.path.splitext(name)[1].lower() not in DOC_EXT:
                        return self._reply(400, b'{"detail":"Unsupported manual file type"}')
                    if any(f["file_name"] == name and f["category"] == folder
                           for f in outer.files.get(t["rom_id"], {}).values()):
                        return self._reply(409, b'{"detail":"already exists"}')
                    uid = f"up{len(outer.sessions) + 1}"
                    outer.sessions[uid] = {"rom_id": t["rom_id"], "folder": folder, "name": name,
                                           "size": int(hdr["x-upload-total-size"]), "chunks": int(hdr["x-upload-total-chunks"]),
                                           "platform": int(hdr["x-upload-platform"]), "got": {}, "state": "open"}
                    return self._reply(200, json.dumps({"upload_id": uid}).encode())
                m = re.fullmatch(r"/api/roms/upload/(\w+)", self.path)
                if m and method == "PUT":
                    s = outer.sessions[m.group(1)]
                    if outer.fail_chunk_once:
                        outer.fail_chunk_once = False
                        return self._reply(500, b"boom")
                    idx = int(hdr["x-chunk-index"])
                    size = math.ceil(s["size"] / s["chunks"])
                    expect = size if idx < s["chunks"] - 1 else s["size"] - size * (s["chunks"] - 1)
                    if len(body) != expect:
                        return self._reply(400, b'{"detail":"wrong chunk size"}')
                    s["got"][idx] = body
                    return self._reply(200, json.dumps({"received": len(s["got"]), "total": s["chunks"]}).encode())
                m = re.fullmatch(r"/api/roms/upload/(\w+)/complete", self.path)
                if m and method == "POST":
                    s = outer.sessions[m.group(1)]
                    if len(s["got"]) != s["chunks"]:
                        return self._reply(400, b'{"detail":"Missing chunks"}')
                    data = b"".join(s["got"][i] for i in range(s["chunks"]))
                    outer.next_id += 1
                    outer.files.setdefault(s["rom_id"], {})[outer.next_id] = {
                        "file_name": s["name"], "category": s["folder"], "data": data}
                    s["state"] = "complete"
                    return self._reply(201)
                m = re.fullmatch(r"/api/roms/upload/(\w+)/cancel", self.path)
                if m and method == "POST":
                    outer.sessions[m.group(1)]["state"] = "cancelled"
                    return self._reply(204)
                m = re.fullmatch(r"/api/roms/(\d+)/(?:manuals/)?files/(\d+)", self.path)
                if m and method == "DELETE":
                    rid, fid = int(m.group(1)), int(m.group(2))
                    if outer.deny_delete:
                        return self._reply(403, b'{"detail":"nope"}')
                    if fid not in outer.files.get(rid, {}):
                        return self._reply(404)
                    del outer.files[rid][fid]
                    return self._reply(200)
                self._reply(404)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

            def do_DELETE(self):
                self._handle("DELETE")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def seed(self, rom_id: int, name: str, category: str, data: bytes = b"x") -> int:
        self.next_id += 1
        self.files.setdefault(rom_id, {})[self.next_id] = {"file_name": name, "category": category, "data": data}
        return self.next_id

    def held(self, rom_id: int, category: str) -> dict[str, bytes]:
        return {f["file_name"]: f["data"] for f in self.files.get(rom_id, {}).values() if f["category"] == category}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
