# Deployment

The repository includes `.github/workflows/deploy.yml`. Add these repository secrets before enabling deployment:

- `SERVER_HOST`: server hostname or IP reachable by the GitHub runner
- `SERVER_SSH_KEY`: private key for the deployment user
- Optional: `SERVER_USER`, `SERVER_PORT`, and `SERVER_PATH`

Defaults are user `joey`, port `22`, and path `/home/joey/roku-app`. On the server, create `data/config.json`, `.env`, and `certs/` once. Deployment deliberately preserves those files and configuration backups. For older installations, the workflow copies the existing root `config.json` into `data/config.json` only when the latter does not exist. Set a nonempty `ROKU_WALL_PASSWORD` before deploying, or explicitly set `ROKU_ALLOW_UNAUTHENTICATED_NETWORK=1` when a trusted reverse proxy/firewall allowlist is in place.

The server must have Docker Compose, SSH access, and network reachability to the Roku TVs. A GitHub-hosted runner cannot discover TVs on a private home LAN. If the server is only reachable at a private address, use a self-hosted runner or a private VPN path for Actions.

Do not expose the controller port publicly. Keep it on the trusted LAN or VPN. The sample Nginx configuration allows LAN/WireGuard clients and redirects denied public requests to GitHub.

The workflow rebuilds the Docker image when application code changes. A direct Python installation can update these files and restart the server without a build. Neither path requires reinstalling the application or resetting TV configuration. Router firewall, reverse proxy, and tunnel changes are separate from code deployment; inspect the running GL-MT2500 setup before changing public access, as described in README.md.
