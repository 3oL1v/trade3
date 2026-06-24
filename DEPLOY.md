# Deploying trade3 to an always-on cloud VM

The point of going cloud is the **automatic forward test**: it only accumulates
data if the collector runs 24/7. Your laptop doesn't have to stay on — this
runs the always-on part (API + collectors + SQLite journals) plus the web UI on
a free Oracle Cloud ARM VM. The Ollama AI analyst stays **off** in the cloud (it
needs a GPU and is only useful on demand); the UI degrades gracefully without it.

## Architecture

```
Browser ──▶ Caddy (:80)  ──┬─▶ /v1/*, /health ─▶ api (uvicorn :8000) ─▶ Bybit public API
                           └─▶ everything else ─▶ static SPA (built frontend)
                                                   api also runs the 24/7 collectors
                                                   journals persist in ./data (SQLite)
```

Single origin, so the frontend keeps using relative `/v1` URLs — no CORS, no
build-time API host.

## 1. Create the VM (Oracle Cloud, Always Free)

1. Sign up at cloud.oracle.com. **Pick a home region in the EU or Asia, not the
   US** — Bybit geo-blocks many US datacenters (you'd get HTTP 403).
2. Create a Compute instance:
   - Shape: **Ampere A1 (arm64)**, e.g. 1–2 OCPU / 6–12 GB RAM (within the
     always-free 4 OCPU / 24 GB).
   - Image: **Ubuntu 22.04**.
   - Add your SSH public key.
3. Networking — allow inbound HTTP:
   - In the subnet's **Security List** (or the instance NSG), add an ingress
     rule: source `0.0.0.0/0`, TCP, destination port **80** (and **443** later
     if you attach a domain). Keep 22 for SSH.

## 2. Open the firewall on the VM

Oracle's Ubuntu images ship a restrictive iptables that blocks port 80 even
after the Security List allows it. SSH in and run:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
newgrp docker   # or log out/in
```

## 4. Get the code and configure

```bash
git clone https://github.com/3oL1v/trade3.git
cd trade3
```

Create `.env` (gitignored) with the cloud settings:

```bash
cat > .env <<'EOF'
# AI analyst needs a GPU and is on-demand, so keep it off in the cloud.
TRADE3_OLLAMA_ENABLED=false
# The reason to run 24/7: the automatic directional forward test.
TRADE3_AUTO_SIGNAL_ENABLED=true
# Live Bybit WebSocket feed. Leave on; turn off only to save bandwidth.
TRADE3_LIVE_MARKET_DATA_ENABLED=true
# If Bybit returns HTTP 403 from this region, route through an HTTP proxy:
# TRADE3_BYBIT_HTTP_PROXY=http://user:pass@host:port
EOF
```

## 5. Build and run

The images build natively on the ARM VM (no cross-compile needed):

```bash
docker compose up -d --build
```

## 6. Verify

```bash
curl -s http://localhost/health                 # {"status":"ok",...}
curl -s http://localhost/v1/markets/top | head  # real Bybit symbols
```

Then open `http://<VM_PUBLIC_IP>/` in a browser. The **АВТОТЕСТ** button in the
header shows the forward test filling up over the next hours. The AI panel will
read `OLLAMA OFFLINE` by design (it's disabled in the cloud).

If `/v1/markets/top` returns a 403/502, Bybit is geo-blocking the VM region —
move the VM to another region or set `TRADE3_BYBIT_HTTP_PROXY` in `.env` and
`docker compose up -d` again.

## Operations

- **Logs:** `docker compose logs -f api`
- **Update:** `git pull && docker compose up -d --build`
- **Data lives in `./data/`** (SQLite journals). Back it up:
  `tar czf trade3-data-$(date +%F).tgz data/`
- **Stop:** `docker compose down` (data is preserved on the host).

## Optional: a domain + HTTPS

Point a domain's A record at the VM IP, open port 443 in the Security List and
iptables, then change `:80` to your domain in `apps/web/Caddyfile` and rebuild —
Caddy provisions a Let's Encrypt certificate automatically.

## Using the AI analyst later

It stays a local feature: run the backend locally with `TRADE3_OLLAMA_ENABLED=true`
and Ollama up when you want AI reviews. Or, to make it cloud-native, swap the
local Ollama call for a hosted small-model API (separate change). The cloud
forward test does not depend on it.
