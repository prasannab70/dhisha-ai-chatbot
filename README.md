# Disha — AI Receptionist for DhishaAI Complete Analytics

Disha is the AI receptionist for **DhishaAI Complete Analytics**. She answers the website chat, WhatsApp and
phone calls, books demo classes and counselling, and stores every conversation and lead in MySQL for the admin
side. One backend serves every channel. Company facts come from dhishaai.com itself and refresh automatically.

```
dhishaai.com (WordPress, chat front end in PHP) ──> POST /web/chat     ┐
WhatsApp (Meta Cloud API)                       ──> /webhooks/whatsapp ├─> Disha API (FastAPI) ──> MySQL
Phone (Plivo / Exotel number -> Retell AI)      ──> wss://…/llm-websocket │                        (tables, CSV per table)
"Talk to Disha AI" page (/disha/)              ──> Retell web call      ┘        └──> DhishaAI Admin Portal (enquiries)
```

---

## Table of contents

1. [Features](#features)
2. [Tech stack](#tech-stack)
3. [Project structure](#project-structure)
4. [Prerequisites](#prerequisites)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [Running the project](#running-the-project)
8. [Checking it works](#checking-it-works)
9. [Connecting the channels](#connecting-the-channels)
10. [API for the front end and the admin side](#api-for-the-front-end-and-the-admin-side)
11. [Deployment](#deployment)
12. [Troubleshooting](#troubleshooting)

---

## Features

**Answers, from DhishaAI's own information only**
- Courses: what is offered, duration, fee, mode, next batch, who it suits, what you learn.
- The company: founders and leadership, vision and values, services, products, industries, clients,
  testimonials, careers and job openings, contact details and directions to the office.
- Career guidance that helps a caller choose a course.
- Anything unrelated to DhishaAI (maths, general knowledge, coding, other companies) is politely refused.

**Does things**
- Books a free **demo class** or a **counselling session**: free slots, details read back, booked only on a clear
  "yes", confirmation on WhatsApp, reminder before the slot.
- Sends the course **brochure** on WhatsApp.
- Takes **callback requests** (name, number, reason, preferred time).
- **Connects to a counsellor** who is online (chat: the counsellor replies inside the same chat; phone: the call
  is transferred) and hands the chat back to Disha afterwards.
- Remembers the person's **name and number** within a conversation.

**Keeps records**
- Every conversation, message, lead, booking, callback and WhatsApp send is stored in MySQL; the admin side reads
  them as JSON or downloads any table as **CSV**.
- Every lead, booking, brochure request and callback is also created as an **enquiry in the DhishaAI Admin Portal**.

**On the phone**
- Understands numbers said in words and reads them back digit by digit; understands the company name however it
  is misheard; says "one moment, let me check" on slow lookups; ends the call politely on "no, that's all".
- Can **call people** (callbacks, demo reminders) from the company's Plivo or Exotel number.

**Always**
- Company knowledge refreshes itself from dhishaai.com every few hours (new pages picked up via the sitemap).
- Temperature 0 on every model: the same question gets the same answer for everyone.
- Rate limits per visitor and per IP on the website chat; secrets never leave the server.

---

## Tech stack

| Layer | Used |
| --- | --- |
| Language | Python 3.11+ |
| Backend | FastAPI, Uvicorn, Pydantic (settings and request models), APScheduler (reminders, website refresh, portal sync) |
| Database | MySQL 8 via SQLAlchemy 2 + PyMySQL (`disha-api/sql/schema.sql`) |
| AI models | Groq (`llama-3.3-70b-versatile`), OpenAI (`gpt-4o-mini`), Anthropic Claude (`claude-haiku-5-5`) or local Ollama (`llama3.1:8b`); single or hybrid mode |
| Voice | Retell AI (speech in / speech out) over a WebSocket; `retell-client-js-sdk` for the browser page; Plivo or Exotel for the Indian phone number |
| WhatsApp | Meta WhatsApp Cloud API |
| Website front end | PHP (WordPress plugin: `wordpress/`) or any PHP page calling the API; plain HTML/CSS/JS, no framework |
| Admin side | DhishaAI Admin Portal (Node.js, separate repository) fed through its API; CSV/JSON endpoints for any other admin page |
| HTTP client / parsing | httpx, Python's `html.parser` (website knowledge) |
| Deployment | Ubuntu, Caddy (automatic HTTPS), systemd |

---

## Project structure

```
aichatbot/
├── README.md                      this file
├── disha-api/                     the backend
│   ├── app/
│   │   ├── main.py                FastAPI app, /web/chat, /agent/*, /admin/*, startup (tables, seed, refresh)
│   │   ├── agent.py               the tool-calling loop over Groq / OpenAI / Claude / Ollama (hybrid routing)
│   │   ├── prompt.py              Disha's instructions and tool definitions
│   │   ├── tools.py               courses, slots, bookings, brochures, callbacks, handoff
│   │   ├── knowledge.py           website programmes and topic routing for company questions
│   │   ├── site_refresh.py        reads dhishaai.com (sitemap + pages) into data/website_kb.json
│   │   ├── db.py                  SQLAlchemy models (MySQL)
│   │   ├── lms.py                 pushes leads / bookings / callbacks into the Admin Portal
│   │   ├── speech.py              spoken numbers, misheard company name, text → speakable
│   │   ├── phone_line.py          Plivo / Exotel line selection
│   │   ├── whatsapp.py            Meta Cloud API send + webhook parsing
│   │   ├── scheduler.py           timed jobs
│   │   └── routers/               console (data + CSV), retell_llm (voice WebSocket), voice, phone, whatsapp, retell, tools
│   ├── static/disha-voice/        "Talk to Disha AI" page
│   ├── static/test-chat/          test pages (visitor chat, counsellor side) — not deployed, git-ignored
│   ├── sql/schema.sql             MySQL database, user and tables
│   ├── deploy/                    Caddyfile, systemd units, server guide
│   ├── docs/api-for-frontend-and-admin.md
│   ├── requirements.txt
│   ├── .env.example               every setting, with comments
│   └── README.md                  backend details
├── wordpress/                     PHP chat front end as a WordPress plugin (+ zip and README)
└── docs/                          Retell agent setup; Plivo / Exotel phone-line setup
```

---

## Prerequisites

| Need | Version | Notes |
| --- | --- | --- |
| Python | 3.11 or newer | python.org (tick "Add to PATH" on Windows) |
| MySQL | 8.x | the company's MySQL server, or MySQL Community Server locally |
| Git | any | to clone the repository |
| A model key | one of | Groq (free tier at console.groq.com), OpenAI, Anthropic — or Ollama installed locally |
| Optional | | Retell AI account (calls, voice page), Meta WhatsApp Cloud API, Plivo/Exotel number, Node.js 22+ for the Admin Portal, ngrok for testing webhooks from a laptop |

---

## Installation

```bash
# 1. Clone
git clone https://github.com/<your-org>/<this-repo>.git
cd <this-repo>/disha-api

# 2. Virtual environment
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # Linux / macOS

# 3. Dependencies
pip install -r requirements.txt

# 4. Settings
copy .env.example .env           # Windows
# cp .env.example .env           # Linux / macOS
```

### Database

Open `sql/schema.sql`, replace `CHANGE-THIS-PASSWORD` with a password of your choice, then run it as the MySQL
root user:

```bash
mysql -u root -p < sql/schema.sql
# Windows, full path: "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -p < sql\schema.sql
```

This creates the `disha` database, the `disha` user and all tables. If you are using an existing MySQL server
instead, just create an empty database and a user with full rights on it: the API creates the tables itself on
first start.

---

## Configuration

Edit `disha-api/.env`. The minimum:

```ini
DATABASE_URL=mysql+pymysql://disha:YOUR-PASSWORD@localhost:3306/disha?charset=utf8mb4
LLM_PROVIDER=groq                 # groq | openai | anthropic | ollama
GROQ_API_KEY=gsk_...              # or OPENAI_API_KEY / ANTHROPIC_API_KEY
CONSOLE_TOKEN=<long random secret>    # the admin side's token for /console/* (tables, CSV)
SITE_KEY=<long random secret>         # the website front end's key for /web/chat
```

Everything else is optional and documented in `.env.example`:

| Group | Keys | For |
| --- | --- | --- |
| Voice / phone | `RETELL_API_KEY`, `RETELL_AGENT_ID`, `RETELL_SECRET`, `PHONE_PROVIDER`, `PLIVO_NUMBER`, `EXOTEL_NUMBER` | calls and the voice page |
| WhatsApp | `WA_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_VERIFY_TOKEN` | WhatsApp channel |
| Admin Portal | `LMS_URL`, `LMS_EMAIL`, `LMS_PASSWORD` | enquiries pushed to the portal |
| Website knowledge | `WEBSITE_URL`, `WEBSITE_REFRESH_HOURS`, `WEBSITE_PAGES` | which site to read and how often |
| Hybrid model | `LLM_MODE=hybrid`, `HYBRID_BASIC_PROVIDER`, `HYBRID_COMPLEX_PROVIDER` | cheap local model for simple questions |
| Office | `OFFICE_ADDRESS`, `OFFICE_HOURS`, `OFFICE_PHONE`, `OFFICE_EMAIL` | directions and contact answers |

Make secrets with `openssl rand -hex 24` (or any long random string).

---

## Running the project

```bash
cd disha-api
venv\Scripts\activate                       # if not already active
uvicorn app.main:app --reload --port 8000
```

Wait for `Application startup complete`. On the first start the API creates any missing tables, seeds the starter
courses, counsellors and demo slots, and reads dhishaai.com in the background.

| Address | What |
| --- | --- |
| http://localhost:8000/docs | every endpoint, with "try it" buttons |
| http://localhost:8000/disha/ | the "Talk to Disha AI" voice page (needs `RETELL_*`) |
| http://localhost:8000/test-chat/ | test chat (needs `SITE_KEY`) |
| http://localhost:8000/health | `{"ok": true}` |

For webhooks and Retell from a laptop, run ngrok in a second terminal: `ngrok http 8000`.

Optional, the Admin Portal (separate repository, Node.js 22+): `npm start` in its folder → http://localhost:4000.
Add a `counsellor` user for Disha there and put its login in `.env` (`LMS_*`).

---

## Checking it works

1. Open http://localhost:8000/test-chat/ and paste `SITE_KEY`. The bar at the top shows backend, model, website
   knowledge and Retell status.
2. Ask: "What courses do you offer?", "Who are the founders?", "Any job openings?", "What is 2+2?" (refused).
3. "Book a free demo class" and follow Disha through to a booking. Then download the table:
   `GET /console/tables/appointments/csv` with header `Authorization: Bearer <CONSOLE_TOKEN>`.
4. "I want to talk to a counsellor", then open http://localhost:8000/test-chat/counsellor.html (paste
   `CONSOLE_TOKEN`), reply from there and press "Give back to Disha".

---

## Connecting the channels

| Channel | Where to set it up | Guide |
| --- | --- | --- |
| Website chat | install `wordpress/disha-receptionist.zip` on the WordPress site and point it at the API, or build the PHP front end against `POST /web/chat` | `wordpress/README-wordpress.md` |
| WhatsApp | Meta → WhatsApp → Configuration → Webhook: `https://<host>/webhooks/whatsapp`, verify token = `WA_VERIFY_TOKEN` | `disha-api/README.md` |
| Phone / voice | Retell agent (Custom LLM) → `wss://<host>/llm-websocket`; Indian number from Plivo or Exotel via SIP trunk | `docs/retell-agent-setup.md`, `docs/phone-lines-plivo-exotel.md` |
| Admin Portal | `LMS_URL`, `LMS_EMAIL`, `LMS_PASSWORD` | `disha-api/README.md` |

---

## API for the front end and the admin side

`disha-api/docs/api-for-frontend-and-admin.md` is the contract. In short:

| Call | Auth | Purpose |
| --- | --- | --- |
| `POST /web/chat` | `X-Site-Key` | visitor message in, Disha's reply out |
| `GET /web/messages?visitor_id=&after=` | `X-Site-Key` | counsellor replies after a handoff |
| `GET /console/tables` · `/console/tables/{t}` · `/console/tables/{t}/csv` | Bearer `CONSOLE_TOKEN` | every table as JSON pages or a CSV download |
| `GET /console/appointments` · `/leads` · `/handoffs` · `/conversations` | Bearer | ready-made views |
| `POST /console/conversations/{id}/reply` · `POST /console/handoffs/{id}/release` | Bearer | counsellor replies, hand back to Disha |
| `GET /voice/config` · `POST /voice/web-call` | none / rate-limited | browser voice call |
| `POST /phone/call` · `PUT /phone/line` | Bearer | outgoing calls, Plivo/Exotel switch |

---

## Deployment

`disha-api/deploy/README.md` covers a single Ubuntu server: MySQL, the API as a systemd service, the Admin Portal
beside it, and Caddy giving HTTPS to `disha.dhishaai.com` (the API) and `admin.dhishaai.com` (the portal).
After that, point the WordPress plugin, the Retell agent and the Meta webhook at `disha.dhishaai.com`.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `DATABASE_URL must be a MySQL address` | `.env` still has a non-MySQL address |
| `Can't connect to MySQL server` | MySQL not running, or host/port wrong; remote server must allow your IP |
| `Access denied for user 'disha'` | password in `.env` differs from the one in `schema.sql` |
| Test chat says `HTTP 401: bad site key` | `SITE_KEY` in `.env` and the key you pasted differ; restart uvicorn after editing `.env` |
| Counsellor page says token rejected | same, for `CONSOLE_TOKEN` |
| `Agent failed (AuthenticationError)` | the model key is wrong or for the wrong provider |
| Company answers say "not on our website" | the website has not been read yet: `POST /admin/refresh-website` (Bearer) and check `GET /admin/website-status` |
| Calls connect but Disha is silent | the Retell agent's WebSocket address must be `wss://<host>/llm-websocket` and reachable |

---

Built for DhishaAI Complete Analytics · dhishaai.com
