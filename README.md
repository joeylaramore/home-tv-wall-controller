# Roku Wall

A local PWA for a 2×2 wall of Roku TVs. Individual and group On/Off controls, with positions tied to each Roku's device ID (or MAC address) so a changed IP does not move a TV to the wrong tile. Python 3.9+ with no Python dependencies.

## Set up your TVs

On each TV, enable **Settings → System → Advanced system settings → Control by mobile apps** and **Settings → System → Power → Fast TV Start**. Fast TV Start uses more standby power. The controller and TVs must be on the same local network. No Roku developer account or developer mode is needed.

## Find the four device IDs

On the computer that will run the controller, run `python server.py --discover`. Match the names/IPs to the physical screens and copy each `device-id` into `config.json` in top-left, top-right, bottom-left, bottom-right order. Start with `cp config.example.json config.json` (or copy it in File Explorer). You can use a `mac` instead of `device_id`, but Roku has separate Wi-Fi and Ethernet MAC addresses, so device ID is preferred. You may set an optional cached `ip`; it is verified against identity and refreshed automatically via SSDP after an address change. If your network blocks multicast between segments, put the controller on the TVs' network or reserve addresses in your router.

## Try it on the controller computer

Run `python server.py` and open `http://localhost:8765`. Test one TV's Off and On before using group controls. Roku explicitly documents `PowerOff`; confirm `PowerOn` works on your models. The app reports failures per TV.

## Install on a phone

A phone PWA needs trusted HTTPS. Generate a trusted local certificate with `mkcert` for the controller computer's LAN IP. Example (replace the IP):

```
mkcert -install
mkcert -cert-file roku-wall.pem -key-file roku-wall-key.pem 192.168.1.50 localhost
```

Trust the mkcert root CA on the phone using mkcert's device instructions; iPhone also needs full trust enabled for that root. Keep the key private. Set a password, then run the controller on the LAN:

```
export ROKU_WALL_PASSWORD='choose-a-long-unique-password'
python server.py --host 0.0.0.0 --cert roku-wall.pem --key roku-wall-key.pem
```

On Windows PowerShell, set `$env:ROKU_WALL_PASSWORD = 'choose-a-long-unique-password'` instead of `export`. Allow inbound TCP 8765 on the private network only. Open `https://192.168.1.50:8765` on the phone. In Safari choose Share → Add to Home Screen; in Android Chrome choose Install app. Your controller computer must remain on. Away from home, use a private VPN to the LAN.

## Linux server with Docker Compose

Copy `config.example.json` to `config.json` and `.env.example` to `.env`, then set actual IDs and a unique password. Generate a certificate for the server's LAN IP, put it at `certs/roku-wall.pem` and its key at `certs/roku-wall-key.pem`, and grant the container user read access to both. Run `docker compose up -d --build`. Linux host networking permits SSDP multicast; the server listens on TCP 8765. Keep that port limited to the trusted LAN or VPN. Do not port-forward it to the public internet.

`config.json`, `.env`, and certificate files are excluded from Git. The server requires HTTPS and a password when exposed on the LAN. The browser service worker caches only the interface; TV commands always go to the controller. A public release would need guided discovery/pairing and stronger device authentication before distribution.
