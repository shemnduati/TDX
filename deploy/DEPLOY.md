# TDX server deployment (isolated install)

Use a **dedicated directory** so other projects on the same server are untouched.
Example: `/opt/tdx` owned by user `tdx` (adjust names to match your server).

## 1. Clone (one-time)

```bash
sudo mkdir -p /opt/tdx
sudo chown "$USER:$USER" /opt/tdx
git clone https://github.com/shemnduati/TDX.git /opt/tdx
cd /opt/tdx
```

## 2. Python API

```bash
cd /opt/tdx
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
curl -s http://127.0.0.1:5001/health   # after starting gunicorn (step 4)
```

Optional env in `/opt/tdx/.env` (see `.env.example` at repo root):

```bash
# Exchange keys (if needed)
API_KEY=...
SECRET=...

# Required when the dashboard is on the public internet
DASHBOARD_AUTH_USERNAME=admin
DASHBOARD_AUTH_PASSWORD=your-long-random-password
DASHBOARD_SECRET_KEY=another-long-random-string-min-16-chars
DASHBOARD_COOKIE_SECURE=1
```

Uncomment `EnvironmentFile=/opt/tdx/.env` in `tdx-api.service`.

## 3. Frontend build

```bash
cd /opt/tdx/frontend
npm ci
npm run build
# static files → frontend/dist/
```

## 4. systemd (API only on localhost)

Copy and edit paths/user:

```bash
sudo cp /opt/tdx/deploy/tdx-api.service /etc/systemd/system/tdx-api.service
sudo nano /etc/systemd/system/tdx-api.service   # fix User= and paths if needed
sudo systemctl daemon-reload
sudo systemctl enable --now tdx-api
sudo systemctl status tdx-api
curl http://127.0.0.1:5001/health
```

Use **one gunicorn worker** (`-w 1`) so sweep/walk-forward background jobs stay in one process.

## 5. Nginx (new site — does not modify other vhosts)

```bash
sudo cp /opt/tdx/deploy/nginx-tdx.conf.example /etc/nginx/sites-available/tdx
sudo nano /etc/nginx/sites-available/tdx   # set server_name and root path
sudo ln -sf /etc/nginx/sites-available/tdx /etc/nginx/sites-enabled/tdx
sudo nginx -t && sudo systemctl reload nginx
```

Enable HTTPS when ready:

```bash
sudo certbot --nginx -d tdx.yourdomain.com
```

## 6. Updates

**Automatic (recommended):** push to `main` — GitHub Actions runs tests and deploys. See [CICD.md](CICD.md) for secrets setup.

**Manual:**

```bash
cd /opt/tdx
git fetch origin main && git reset --hard origin/main
bash deploy/deploy.sh
```

## Security

With `DASHBOARD_AUTH_PASSWORD` set, the React app shows a **sign-in** screen and the
API requires a session cookie on all routes except `/health` and `/auth/*`.

Without that variable (typical local dev), auth is **off** — do not deploy publicly
without setting password + secret key.

Also use HTTPS (Let's Encrypt) so `DASHBOARD_COOKIE_SECURE=1` protects the session cookie.

## Optional: live paper bot

Separate systemd unit (see `tdx-bot.service.example`). Only enable if you want the Live tab fed from `data.json`.
