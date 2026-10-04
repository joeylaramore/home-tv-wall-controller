#!/usr/bin/env python3
"""Local-only Roku TV wall controller. Python standard library only."""
import concurrent.futures
import base64
import http.server
import ipaddress
import json
import os
import pathlib
import socket
import ssl
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent
WEB = ROOT / "web"
CONFIG_PATH = ROOT / "config.json"
TVS = []


def device_info(ip):
    ipaddress.ip_address(ip)
    with urllib.request.urlopen(f"http://{ip}:8060/query/device-info", timeout=2) as response:
        root = ET.fromstring(response.read(65536))
    return {key: root.findtext(key, "") for key in
            ("device-id", "serial-number", "wifi-mac", "ethernet-mac", "user-device-name", "power-mode")}


def discover(timeout=3):
    """Find Roku ECP devices by SSDP; verify identity using device-info."""
    request = (b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
               b'MAN: "ssdp:discover"\r\nMX: 2\r\nST: roku:ecp\r\n\r\n')
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(timeout)
        sock.sendto(request, ("239.255.255.250", 1900))
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                packet, address = sock.recvfrom(4096)
            except socket.timeout:
                break
            headers = {}
            for line in packet.decode("latin1", "replace").splitlines()[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.lower().strip()] = value.strip()
            location = urllib.parse.urlparse(headers.get("location", ""))
            if location.scheme != "http" or location.port != 8060 or location.hostname != address[0]:
                continue
            try:
                info = device_info(address[0])
                if info["device-id"]:
                    found[info["device-id"]] = {"ip": address[0], **info}
            except Exception:
                continue
    return found


def matches(tv, info):
    if tv.get("device_id"):
        return tv["device_id"] == info["device-id"]
    mac = tv.get("mac", "").lower()
    return bool(mac and mac in (info["wifi-mac"].lower(), info["ethernet-mac"].lower()))


def resolve(tv):
    ip = tv.get("ip")
    if ip:
        try:
            if matches(tv, device_info(ip)):
                return ip
        except Exception:
            pass
    for candidate in discover().values():
        if matches(tv, candidate):
            tv["ip"] = candidate["ip"]  # Runtime cache; identity remains in config.
            return candidate["ip"]
    raise ConnectionError("TV not found by its device ID or MAC on this network")


def command(tv, action):
    try:
        ip = resolve(tv)
        request = urllib.request.Request(
            f"http://{ip}:8060/keypress/{action}", data=b"", method="POST"
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            return {"name": tv["name"], "ok": response.status == 200}
    except Exception as exc:
        return {"name": tv["name"], "ok": False, "error": str(exc)}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/api/discover":
            try:
                return self.reply(200, list(discover().values()))
            except Exception as exc:
                return self.reply(500, {"error": str(exc)})
        if self.path == "/api/tvs":
            return self.reply(200, [{"name": tv["name"], "paired": bool(tv.get("device_id") or tv.get("mac"))} for tv in TVS])
        return super().do_GET()

    def do_POST(self):
        if not self.authorized():
            return
        parts = self.path.split("/")
        if self.path == "/api/configure":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            devices = payload.get("tvs", [])
            if not isinstance(devices, list) or not devices or len(devices) > 100:
                return self.reply(400, {"error": "Provide between 1 and 100 TVs"})
            seen = set()
            configured = []
            for index, item in enumerate(devices):
                device_id = str(item.get("device_id", "")).strip()
                if not device_id or device_id in seen:
                    return self.reply(400, {"error": "Each TV needs a unique discovered device ID"})
                seen.add(device_id)
                configured.append({"name": str(item.get("name") or f"TV {index + 1}").strip(), "device_id": device_id, "mac": "", "ip": str(item.get("ip", "")).strip()})
            CONFIG_PATH.write_text(json.dumps({"tvs": configured}, indent=2) + "\n")
            TVS[:] = configured
            return self.reply(200, {"ok": True, "count": len(TVS)})
        if len(parts) != 4 or parts[1] != "api" or parts[2] not in ("all",) and not parts[2].isdigit() or parts[3] not in ("on", "off"):
            return self.reply(404, {"error": "Unknown command"})
        if parts[2] != "all" and (not parts[2].isdigit() or int(parts[2]) >= len(TVS)):
            return self.reply(404, {"error": "Unknown TV"})
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if origin and origin not in (f"http://{host}", f"https://{host}"):
            return self.reply(403, {"error": "Origin rejected"})
        targets = TVS if parts[2] == "all" else [TVS[int(parts[2])]]
        action = "PowerOn" if parts[3] == "on" else "PowerOff"
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(lambda tv: command(tv, action), targets))
        return self.reply(200, result)

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        password = os.environ.get("ROKU_WALL_PASSWORD")
        if not password:
            return True
        import hmac
        expected = "Basic " + base64.b64encode(("roku:" + password).encode()).decode()
        if hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Roku Wall"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cert", help="Trusted local HTTPS certificate")
    parser.add_argument("--key", help="Private key for certificate")
    parser.add_argument("--discover", action="store_true", help="List nearby Roku devices and their IDs/MACs")
    args = parser.parse_args()
    if args.discover:
        print(json.dumps(list(discover().values()), indent=2))
        sys.exit(0)
    if not CONFIG_PATH.exists():
        sys.exit("Copy config.example.json to config.json and set four TV identities")
    TVS = json.loads(CONFIG_PATH.read_text())["tvs"]
    if len(TVS) > 100:
        sys.exit("Configure no more than 100 TVs in config.json")
    for tv in TVS:
        if tv.get("ip") and not ipaddress.ip_address(tv["ip"]).is_private:
            sys.exit("Optional cached IP must be a private LAN address")
    if args.host not in ("127.0.0.1", "localhost", "::1") and not (args.cert and args.key):
        sys.exit("LAN access requires --cert and --key. See README.md")
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    if args.cert and args.key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    scheme = "https" if args.cert else "http"
    print(f"Roku wall: {scheme}://{args.host}:{args.port}")
    server.serve_forever()
