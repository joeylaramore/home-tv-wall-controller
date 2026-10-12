# Roku Wall

A self-hosted local network controller for a 2×2 wall of Roku TVs. Individual and group On/Off controls use each TV's device ID (or MAC address), so a changed IP does not move a TV to the wrong tile. This is an independent project and is not affiliated with Roku. Python 3.9+ with no Python dependencies.

## Set up your TVs

On each TV, enable **Settings → System → Advanced system settings → Control by mobile apps** and **Settings → System → Power → Fast TV Start**. Fast TV Start uses more standby power. The controller and TVs must be on the same local network. No Roku developer account or developer mode is needed.

## Find the four device IDs

On the computer that will run the controller, run `python server.py --discover`. Match the names/IPs to the physical screens and copy each `device-id` into `config.json` in top-left, top-right, bottom-left, bottom-right order. Start with `cp config.example.json config.json` (or copy it in File Explorer). You can use a `mac` instead of `device_id`, but Roku has separate Wi-Fi and Ethernet MAC addresses, so device ID is preferred. You may set an optional cached `ip`; it is verified against identity and refreshed automatically via SSDP after an address change. If your network blocks multicast between segments, put the controller on the TVs' network or reserve addresses in your router.

## Try it on the controller computer

Run `python server.py` and open `http://localhost:8765`. Test one TV's Off and On before using group controls. Roku explicitly documents `PowerOff`; confirm `PowerOn` works on your models. The app reports failures per TV.

Each TV tile can select HDMI 1-4 or launch an installed Roku app. Clicking a tile opens a compact remote with navigation, playback, volume, mute, and input controls. Add saved scenes to `config.json` with an action target of `all` or a TV index. A `target` of `0` addresses the first TV, `1` the second, and so on. Select the HDMI port connected to the video-wall processor; the ARC port is a TV-specific HDMI port and should be configured according to the TV model.

For example, this scene opens YouTube TV on every screen:

```json
{"name":"NFL Sunday Ticket","actions":[{"target":"all","command":"launch_name","value":"YouTube TV"}]}
```

A 2x2 Apple TV wall scene can switch every TV to the processor input:

```json
{"name":"2x2 Game Wall","actions":[{"target":"all","command":"keypress","value":"InputHDMI4"}]}
```

Separate TV actions can be combined in one scene, but selecting a different live game automatically on each YouTube TV screen requires deep-link support from the installed service.

## Install on a phone

1. Put the phone on the same home Wi-Fi as the controller.
2. Open the controller address in Safari or Chrome. Use the address shown by your installation; for the example deployment, it is `https://roku.jlaramore.com`.
3. Add it to the home screen:
   - **iPhone/iPad:** Share → **Add to Home Screen**.
   - **Android:** ⋮ → **Install app** or **Add to Home screen**.

To use it away from home, connect the phone to the controller's private WireGuard VPN first, then open the same address. The public GitHub address is for the project instructions; it is not the controller.

## Linux server with Docker Compose

Create `data/`, copy `config.example.json` to `data/config.json` and `.env.example` to `.env`, then set the TV identities and a strong password. For an existing installation, copy the current `config.json` to `data/config.json` before switching Compose versions; keep the original as a recovery copy. The directory mount allows safe atomic configuration updates and persists recovery backups. Generate a certificate for the server's LAN/VPN name, put it at `certs/roku-wall.pem` and its key at `certs/roku-wall-key.pem`, then run `docker compose up -d --build`. Linux host networking permits SSDP multicast; the server listens on TCP 8765. Keep that port private and place Nginx or another HTTPS reverse proxy in front of it. Do not port-forward the controller port to the public internet.

`config.json`, `.env`, and certificate files are excluded from Git. The browser service worker caches only the interface; TV commands always go to the controller. A public release would need guided discovery/pairing and stronger device authentication before distribution.

For a private LAN/VPN deployment behind the Nginx allowlist, set `ROKU_WALL_PASSWORD=` and `ROKU_ALLOW_UNAUTHENTICATED_NETWORK=1`. Keep port 8765 unreachable from the public internet and use the Nginx example to enforce the trusted source networks. If you do not have a network allowlist, keep the strong password from `.env.example` and leave the flag at `0`.

## Back up and restore

**Backup Configuration** downloads the saved `config.json`, including device IDs, MAC addresses, names, cached addresses, and the TV list order used for layout. Save layout edits before downloading. **Restore Configuration** selects a JSON backup and asks before replacing settings. The server validates the entire file before writing; malformed files, duplicate identities, public TV addresses, and files larger than 256 KB are rejected. Empty TV lists are supported for a fresh setup.

Every save or restore first preserves the exact previous file in `config-backups/` beside the active configuration. The active file is then replaced atomically; a backup or write failure leaves the current configuration active. Restored settings take effect immediately. Recovery files stay on the controller, outside the website, and are never removed automatically. To recover, select one of those JSON files using Restore Configuration, or stop the server and copy it over the active config file.

Direct Python installations still use the repository's `config.json`. Set `ROKU_CONFIG_PATH` to change its location. Docker uses `data/config.json` and stores recovery files in `data/config-backups/`. These files and directories are excluded from Git and Docker build contexts.

## LAN and WireGuard access

Direct Python invocation defaults to loopback on port 8765; the Docker Compose example uses host networking so Roku discovery can cross the local network. Network listeners require HTTPS. With a password configured, the app also enforces HTTP Basic authentication. A passwordless deployment is supported only when `ROKU_ALLOW_UNAUTHENTICATED_NETWORK=1` is set and a reverse proxy/firewall strictly limits access to trusted networks; the application still rejects direct non-loopback requests without a password. The application always allows private address ranges and `ROKU_ALLOWED_CIDRS` can add trusted ranges; it does not replace those built-in private ranges. A reverse proxy must enforce the original client address when the app is proxied. Forwarded headers are not trusted by the application.

Application filtering alone cannot block public traffic forwarded by a local reverse proxy or tunnel: the server sees the proxy's local address. Before changing the GL-MT2500, inspect the existing public entry point:

```sh
uci show firewall | grep -Ei 'redirect|8765|roku'
ps w | grep -E 'server.py|nginx|uhttpd|cloudflared' | grep -v grep
```

These are initial checks; a proxy or tunnel using a different name may require further inspection. Remove the controller's WAN forwarding rule or public proxy/tunnel route once identified. Allow TCP 8765 only from the LAN and the WireGuard client zone, keeping WireGuard's own WAN UDP listener and routing intact. Use the Nginx example in `deploy/roku.jlaramore.com.conf.example` to allow `192.168.1.0/24` and the WireGuard subnet while redirecting denied public requests to the GitHub project. Verify access from both the home LAN and WireGuard, then verify the old public URL and WAN port cannot reach the controller from outside the VPN. GitHub hosts source and installation instructions; it does not need a public controller endpoint.

For a home router running AdGuard Home, add a DNS rewrite for the controller hostname to its WireGuard address (for example, `roku.jlaramore.com → 10.77.43.1`). Devices must use the home DNS service; clients using public DNS will resolve the public address and be denied.
