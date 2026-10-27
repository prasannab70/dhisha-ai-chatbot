# Deploying Disha and the Admin Portal

One small Ubuntu server (2 GB RAM is enough) runs everything: MySQL, the Disha API, the DhishaAI Admin Portal
(the Node app) and Caddy for HTTPS. The WordPress site at dhishaai.com stays where it is; only its Disha plugin
setting changes.

```
Visitors ──> dhishaai.com (WordPress + Disha plugin) ──> https://disha.dhishaai.com ──> Disha API ──> MySQL  
WhatsApp (Meta) ──> https://disha.dhishaai.com/webhooks/whatsapp                          │
Retell (calls, voice page) ──> wss://disha.dhishaai.com/llm-websocket                    │ every lead, booking,
                                                                                          │ callback -> enquiry
Counsellors / admin ──> https://admin.dhishaai.com  (Admin Portal: enquiries, students, fees) <┘
Admin side / PHP pages ──> https://disha.dhishaai.com/console/*  (tables as JSON or CSV, Bearer CONSOLE_TOKEN)
```

## 1. DNS

At your domain registrar, add two **A records**: `admin` and `disha` → the server's public IP. Wait until
`ping admin.dhishaai.com` answers from your laptop.

## 2. Packages

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip mysql-server git
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs   # for the Admin Portal
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
sudo mysql_secure_installation          # set a root password, answer Y to the rest
```

## 3. Database

Edit `sql/schema.sql` first and replace `CHANGE-THIS-PASSWORD` with a real password, then:

```bash
sudo mysql -u root -p < sql/schema.sql
```

This creates the `disha` database, the `disha` user and all tables. (The API also creates any missing table
on start, so a later version never needs this file again.)

## 4. The API

```bash
sudo adduser --system --group --home /opt/disha disha
sudo mkdir -p /opt/disha && sudo chown disha:disha /opt/disha
sudo -u disha bash -c '
  cd /opt/disha && git clone <your repo> . || true          # or copy the disha-api folder here with scp
  cd /opt/disha/disha-api
  python3 -m venv venv && venv/bin/pip install -r requirements.txt
  cp .env.example .env
'
sudo -u disha nano /opt/disha/disha-api/.env
```

Fill in `.env`:

| Key | Value |
| --- | --- |
| `DATABASE_URL` | `mysql+pymysql://disha:<the password from schema.sql>@localhost:3306/disha?charset=utf8mb4` |
| `LLM_PROVIDER` + its key | `groq` / `anthropic` / `openai` and the API key |
| `CONSOLE_TOKEN` | a long random secret: the token for the data endpoints (`/console/*`) |
| `SITE_KEY` | a long random secret: the WordPress plugin's key |
| `ALLOWED_ORIGINS` | `https://dhishaai.com,https://www.dhishaai.com` |
| `WEBSITE_URL` | `https://dhishaai.com` |
| `RETELL_API_KEY`, `RETELL_AGENT_ID`, `RETELL_SECRET` | from the Retell dashboard |
| `WA_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_VERIFY_TOKEN` | from Meta |
| `PHONE_PROVIDER`, `PLIVO_NUMBER` / `EXOTEL_NUMBER` | once the number exists |
| `LMS_URL`, `LMS_EMAIL`, `LMS_PASSWORD` | `http://127.0.0.1:4000` and the portal account made for Disha (step 5) |

Make random secrets with `openssl rand -hex 24`.

Then the service:

```bash
sudo cp /opt/disha/disha-api/deploy/disha-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now disha-api
sudo journalctl -u disha-api -n 50          # should end with "Application startup complete"
curl http://127.0.0.1:8000/health             # {"ok":true}
```

## 5. The Admin Portal (Node app)

```bash
sudo -u disha git clone https://github.com/chandanstsmg-eng/dhishaai-admin /opt/disha/dhishaai-admin
echo "DHISHAAI_SECRET=$(openssl rand -hex 32)" | sudo -u disha tee /opt/disha/dhishaai-admin/.env
sudo cp /opt/disha/disha-api/deploy/dhishaai-admin.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now dhishaai-admin
sudo journalctl -u dhishaai-admin -n 20        # prints the owner login on the very first start
```

Then in the portal (https://admin.dhishaai.com after step 6): change the owner password, and under
**Settings → Users** add a user for Disha, for example `disha@dhishaai.com` with role **counsellor**. Put that
email and password in the API's `.env` as `LMS_EMAIL` / `LMS_PASSWORD`, with `LMS_URL=http://127.0.0.1:4000`, and
`sudo systemctl restart disha-api`. From then on every lead, booking, brochure request and callback Disha captures
appears under **Enquiries** in the portal (with a follow-up entry when the same number comes back). The Disha
`GET /admin/lms-status` shows the sync status; `POST /admin/lms-check` tests the portal sign-in.

The portal keeps its data in `/opt/disha/dhishaai-admin/data/dhishaai.db` (its own SQLite file; `npm run backup`
there, or Settings → Data in the portal).

## 6. HTTPS with Caddy

```bash
sudo cp /opt/disha/disha-api/deploy/Caddyfile /etc/caddy/Caddyfile
sudo mkdir -p /var/log/caddy && sudo chown caddy:caddy /var/log/caddy
sudo systemctl reload caddy
```

Caddy fetches the certificates on its own (ports 80 and 443 must be open in the server firewall:
`sudo ufw allow 80,443/tcp`). Open https://disha.dhishaai.com/health (`{"ok":true}`), https://disha.dhishaai.com/disha/ and
https://admin.dhishaai.com (the portal).

## 7. Point the other systems at the server

| System | Setting |
| --- | --- |
| WordPress → Settings → Disha Receptionist | Disha API address `https://disha.dhishaai.com`, site key = `SITE_KEY`, voice page `https://disha.dhishaai.com/disha/` |
| Retell agent (Custom LLM) | `wss://disha.dhishaai.com/llm-websocket` |
| Meta → WhatsApp → Configuration → Webhook | `https://disha.dhishaai.com/webhooks/whatsapp`, verify token = `WA_VERIFY_TOKEN` |

ngrok is no longer needed.

## 8. Updating later

```bash
cd /opt/disha/disha-api && sudo -u disha git pull        # or copy the changed files
sudo -u disha venv/bin/pip install -r requirements.txt
sudo systemctl restart disha-api
```

## Backups

Nightly dump of the database (keeps 14 days):

```bash
sudo tee /etc/cron.daily/disha-backup >/dev/null <<'EOF'
#!/bin/sh
mkdir -p /var/backups/disha
mysqldump --single-transaction disha | gzip > /var/backups/disha/disha-$(date +%F).sql.gz
find /var/backups/disha -name 'disha-*.sql.gz' -mtime +14 -delete
EOF
sudo chmod +x /etc/cron.daily/disha-backup
```

(Put the `disha` user's password in `/root/.my.cnf` so mysqldump runs without a prompt.)

## If something is wrong

| Symptom | Check |
| --- | --- |
| /health does not answer | `sudo systemctl status disha-api caddy`; `sudo journalctl -u disha-api -n 100` |
| Leads do not appear in the portal | `GET /admin/lms-status` shows the last error; `POST /admin/lms-check`; `sudo systemctl status dhishaai-admin` |
| "Can't connect to MySQL" in the log | `DATABASE_URL` password; `sudo systemctl status mysql` |
| Website chat says Disha is not reachable | WordPress plugin → Test connection; `ALLOWED_ORIGINS`; `SITE_KEY` matches |
| Calls connect but Disha is silent | the Retell agent's WebSocket address must be `wss://disha.dhishaai.com/llm-websocket` |
| Company answers are empty | `POST /admin/refresh-website`; `GET /admin/website-status`; the server must reach dhishaai.com |
