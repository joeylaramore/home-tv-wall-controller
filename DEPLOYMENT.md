# Deployment

The repository includes `.github/workflows/deploy.yml`. Add these repository secrets before enabling deployment:

- `SERVER_HOST`: server hostname or IP reachable by the GitHub runner
- `SERVER_SSH_KEY`: private key for the deployment user
- Optional: `SERVER_USER`, `SERVER_PORT`, and `SERVER_PATH`

Defaults are user `joey`, port `22`, and path `/home/joey/roku-app`. On the server, create `config.json`, `.env`, and `certs/` once. Deployment deliberately preserves those files.

The server must have Docker Compose, SSH access, and network reachability to the Roku TVs. A GitHub-hosted runner cannot discover TVs on a private home LAN. If the server is only reachable at a private address, use a self-hosted runner or a private VPN path for Actions.

Do not expose the controller port publicly. Keep it on the trusted LAN or VPN.