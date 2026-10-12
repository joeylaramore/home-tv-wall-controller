#!/usr/bin/env python3
"""Local-only Roku TV wall controller. Python standard library only."""
import concurrent.futures
import base64
import http.server
import ipaddress
import json
import hmac
import os
import pathlib
import re
import socket
import ssl
import sys
import threading
import tempfile
import uuid
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent
WEB = ROOT / "web"
CONFIG_PATH = pathlib.Path(os.environ.get("ROKU_CONFIG_PATH", str(ROOT / "config.json")))
CONFIG_LOCK = threading.RLock()
MAX_CONFIG_BYTES = 256 * 1024
LOCAL_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                       ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
TVS = []


def local_address(value):
    address = ipaddress.ip_address(value)
    return address.is_loopback or any(address in network for network in LOCAL_NETWORKS)


def validate_config(payload):
    """Validate the existing config format; list order is the wall layout."""
    if not isinstance(payload, dict) or set(payload) != {"tvs"}:
        raise ValueError('Configuration must contain only a "tvs" list')
    devices = payload["tvs"]
    if not isinstance(devices, list) or len(devices) > 100:
        raise ValueError("Provide a list of no more than 100 TVs")
    configured, seen_ids, seen_macs = [], set(), set()
    for index, item in enumerate(devices):
        if not isinstance(item, dict) or set(item) - {"name", "device_id", "mac", "ip"}:
            raise ValueError(f"TV {index + 1} has invalid fields")
        tv = {}
        for key in ("name", "device_id", "mac", "ip"):
            value = item.get(key, "")
            if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 for c in value):
                raise ValueError(f"TV {index + 1}: invalid {key}")
            tv[key] = value.strip()
        if not tv["name"] or not (tv["device_id"] or tv["mac"]):
            raise ValueError(f"TV {index + 1} needs a name and device ID or MAC")
        if tv["mac"]:
            if not re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", tv["mac"]):
                raise ValueError(f"TV {index + 1}: invalid MAC address")
            tv["mac"] = tv["mac"].lower()
        for key, seen in (("device_id", seen_ids), ("mac", seen_macs)):
            if tv[key] and tv[key] in seen:
                raise ValueError(f"Each TV needs a unique {key}")
            if tv[key]:
                seen.add(tv[key])
        if tv["ip"] and not local_address(tv["ip"]):
            raise ValueError("Cached TV addresses must be private LAN addresses")
        configured.append(tv)
    return {"tvs": configured}


def atomic_write(path, data):
    """Replace a file only after its full contents have reached disk."""
    fd, temporary = tempfile.mkstemp(prefix=".roku-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_config(payload):
    config = validate_config(payload)
    data = (json.dumps(config, indent=2) + "\n").encode("utf-8")
    with CONFIG_LOCK:
        # A failed backup aborts the save. Keep every previous version.
        backup_dir = CONFIG_PATH.parent / "config-backups"
        backup_dir.mkdir(mode=0o700, exist_ok=True)
        previous = CONFIG_PATH.read_bytes()
        backup = backup_dir / f"config-{uuid.uuid4().hex}.json"
        atomic_write(backup, previous)
        atomic_write(CONFIG_PATH, data)
        TVS[:] = config["tvs"]
    return backup.name


def device_info(ip):
    ipaddress.ip_address(ip)
    host = f"[{ip}]" if ":" in ip else ip
    with urllib.request.urlopen(f"http://{host}:8060/query/device-info", timeout=2) as response:
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
    # Multicast does not cross a routed VPN. Explicit networks let a controller
    # scan a private LAN reached through a tunnel while keeping device IDs as
    # the persisted identity.
    configured = os.environ.get("ROKU_SCAN_CIDRS", "").strip()
    if configured:
        networks = []
        for value in configured.split(","):
            network = ipaddress.ip_network(value.strip(), strict=False)
            if not isinstance(network, ipaddress.IPv4Network) or not network.is_private or network.prefixlen < 24:
                raise ValueError("ROKU_SCAN_CIDRS requires private IPv4 /24 or smaller networks")
            networks.append(network)
        if sum(network.num_addresses for network in networks) > 1024:
            raise ValueError("ROKU_SCAN_CIDRS exceeds 1024 addresses")
        addresses = sorted({str(address) for network in networks for address in network.hosts()})
    else:
        # Some access points block SSDP multicast between wired and wireless
        # clients. Fall back to a bounded private /24 scan of Roku's ECP port.
        if found:
            return found
        addresses = local_scan_addresses()

    if not addresses:
        return found

    def probe(address):
        try:
            info = device_info(address)
            if info["device-id"]:
                return info["device-id"], {"ip": address, **info}
        except Exception:
            return None
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        for result in pool.map(probe, addresses):
            if result:
                device_id, info = result
                found[device_id] = info
    return found


def local_scan_addresses():
    """Return a bounded scan range for the server's default private route."""
    local_ip = None
    for probe in ("192.0.2.1", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_sock:
                route_sock.connect((probe, 1))
                candidate = route_sock.getsockname()[0]
                if ipaddress.ip_address(candidate).is_private:
                    local_ip = candidate
                    break
        except OSError:
            continue
    if not local_ip:
        return []

    prefix = ".".join(local_ip.split(".")[:3])
    return [f"{prefix}.{host}" for host in range(1, 255)]


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


def send_keypress(tv, action, ip):
    try:
        host = f"[{ip}]" if ":" in ip else ip
        request = urllib.request.Request(
            f"http://{host}:8060/keypress/{action}", data=b"", method="POST"
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            return {"name": tv["name"], "ok": response.status == 200}
    except Exception as exc:
        return {"name": tv["name"], "ok": False, "error": str(exc)}


def command(tv, action):
    """Resolve and send one command."""
    try:
        return send_keypress(tv, action, resolve(tv))
    except Exception as exc:
        return {"name": tv["name"], "ok": False, "error": str(exc)}


def command_many(tvs, action):
    """Resolve every TV first, then send the keypresses in one synchronized wave."""
    def resolve_one(tv):
        try:
            return tv, resolve(tv), None
        except Exception as exc:
            return tv, None, exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, max(1, len(tvs)))) as pool:
        resolved = list(pool.map(resolve_one, tvs))

    ready = threading.Event()

    def send_one(item):
        tv, ip, error = item
        if error:
            return {"name": tv["name"], "ok": False, "error": str(error)}
        ready.wait()
        return send_keypress(tv, action, ip)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, max(1, len(resolved)))) as pool:
        futures = [pool.submit(send_one, item) for item in resolved]
        # All requests are queued before releasing the workers, so DNS/identity
        # discovery cannot make one TV start much later than another.
        ready.set()
        return [future.result() for future in futures]


class Handler(http.server.SimpleHTTPRequestHandler):
    timeout = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if not self.allowed_client():
            return
        if self.path == "/healthz":
            return self.reply(200, {"ok": True})
        if not self.authorized():
            return
        if self.path == "/api/backup":
            try:
                with CONFIG_LOCK:
                    config = validate_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
                return self.reply(200, config, attachment="roku-wall-config.json")
            except (OSError, ValueError) as exc:
                return self.reply(500, {"error": str(exc)})
        if self.path == "/api/discover":
            try:
                return self.reply(200, list(discover().values()))
            except Exception as exc:
                return self.reply(500, {"error": str(exc)})
        if self.path == "/api/tvs":
            with CONFIG_LOCK:
                devices = [dict(tv, paired=bool(tv.get("device_id") or tv.get("mac"))) for tv in TVS]
            return self.reply(200, devices)
        return super().do_GET()

    def do_HEAD(self):
        if self.allowed_client() and self.authorized():
            super().do_HEAD()

    def do_POST(self):
        if not self.allowed_client() or not self.authorized():
            return
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if (origin and origin not in (f"http://{host}", f"https://{host}")) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.reply(403, {"error": "Origin rejected"})
        parts = self.path.split("/")
        if self.path in ("/api/configure", "/api/restore"):
            if self.headers.get_content_type() != "application/json":
                return self.reply(415, {"error": "Use application/json"})
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Transfer-Encoding is unsupported")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_CONFIG_BYTES:
                    raise ValueError("Configuration must be between 1 and 262144 bytes")
                payload = json.loads(self.rfile.read(length))
                backup = save_config(payload)
            except (ValueError, UnicodeError, RecursionError) as exc:
                return self.reply(400, {"error": str(exc)})
            except OSError:
                return self.reply(500, {"error": "Could not save configuration; previous settings remain active"})
            return self.reply(200, {"ok": True, "count": len(TVS), "previous_backup": backup})
        if (len(parts) != 4 or parts[1] != "api" or
                (parts[2] != "all" and not re.fullmatch(r"[0-9]{1,3}", parts[2])) or
                parts[3] not in ("on", "off")):
            return self.reply(404, {"error": "Unknown command"})
        with CONFIG_LOCK:
            if parts[2] != "all" and int(parts[2]) >= len(TVS):
                return self.reply(404, {"error": "Unknown TV"})
            targets = list(TVS) if parts[2] == "all" else [TVS[int(parts[2])]]
        action = "PowerOn" if parts[3] == "on" else "PowerOff"
        result = command_many(targets, action) if parts[2] == "all" else [command(targets[0], action)]
        return self.reply(200, result)

    def reply(self, status, data, attachment=None):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def allowed_client(self):
        address = ipaddress.ip_address(self.client_address[0])
        if address.is_loopback or any(address in network for network in self.server.allowed_networks):
            return True
        self.reply(403, {"error": "Access is limited to the LAN and private VPN"})
        return False

    def authorized(self):
        password = os.environ.get("ROKU_WALL_PASSWORD")
        if not password:
            if ipaddress.ip_address(self.client_address[0]).is_loopback:
                return True
            self.reply(403, {"error": "Network access requires ROKU_WALL_PASSWORD"})
            return False
        expected = "Basic " + base64.b64encode(("roku:" + password).encode()).decode()
        if hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode()):
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
    try:
        TVS = validate_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))["tvs"]
        allowed_networks = LOCAL_NETWORKS + tuple(ipaddress.ip_network(value.strip()) for value in
            os.environ.get("ROKU_ALLOWED_CIDRS", "").split(",") if value.strip())
    except ValueError as exc:
        sys.exit(str(exc))
    if (args.host not in ("127.0.0.1", "localhost", "::1") and
            not os.environ.get("ROKU_WALL_PASSWORD") and
            os.environ.get("ROKU_ALLOW_UNAUTHENTICATED_NETWORK") != "1"):
        sys.exit("Network access requires ROKU_WALL_PASSWORD")
    if args.host not in ("127.0.0.1", "localhost", "::1") and not (args.cert and args.key):
        sys.exit("LAN access requires --cert and --key. See README.md")
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    server.allowed_networks = allowed_networks
    if args.cert and args.key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    scheme = "https" if args.cert else "http"
    print(f"Roku wall: {scheme}://{args.host}:{args.port}")
    server.serve_forever()
