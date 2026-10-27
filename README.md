# Disha — AI receptionist for DhishaAI Complete Analytics

Disha answers the website chat, WhatsApp and phone calls for DhishaAI, books demo classes and counselling,
and stores everything in the company's MySQL so the admin side can see and download it. One backend serves
every channel; company facts come from dhishaai.com itself and are refreshed automatically.

```
dhishaai.com  (WordPress; chat front end in PHP)  ──>  POST /web/chat     ┐
WhatsApp  (Meta Cloud API)                        ──>  /webhooks/whatsapp ├─>  Disha API (FastAPI)  ──>  MySQL
Phone  (Plivo / Exotel number -> Retell AI)       ──>  wss://…/llm-websocket │       │                    (tables; CSV per table)
"Talk to Disha AI" page  (/disha/, Retell web call)                      ┘       └──>  DhishaAI Admin Portal (enquiries)
```

## Folders

| Folder | What it is |
| --- | --- |
| `disha-api/` | the backend (Python / FastAPI). Start here: `disha-api/README.md`. |
| `disha-api/docs/api-for-frontend-and-admin.md` | every API call the PHP front end and the admin side use |
| `disha-api/deploy/` | Caddyfile, systemd units and the server setup guide (`disha.dhishaai.com` + `admin.dhishaai.com`) |
| `disha-api/sql/schema.sql` | MySQL: database, user and all tables |
| `disha-api/static/disha-voice/` | the "Talk to Disha AI" page (Disha's face reacts to the call) |
| `disha-api/static/test-chat/` | test pages only: visitor chat and counsellor side (not deployed, git-ignored) |
| `wordpress/` | a working PHP chat front end as a WordPress plugin (bubble + chat panel). Use it, restyle it, or build your own against the API. |
| `docs/` | Retell agent setup; Plivo / Exotel phone-line setup |

## What Disha does

- **Answers** questions about courses, fees, batches, the company, founders, services, products, careers and
  testimonials. Course facts come from the `courses` table; company facts from a copy of dhishaai.com that the
  backend re-reads every few hours (new pages are found through the site's sitemap, no code change).
- **Books** demo classes and counselling (reads the details back and books only on a clear "yes"), sends the
  brochure, takes callback requests, connects to an online counsellor, and hands a chat to a human.
- **Stays on topic**: anything that is not about DhishaAI is politely refused.
- **Same answer for everyone**: every model is called at temperature 0.
- **Stores** every conversation, message, lead, booking and callback in MySQL. The admin side reads them as JSON or
  downloads any table as CSV (`/console/tables/{table}/csv`), and every lead, booking and callback is also created
  as an enquiry in the DhishaAI Admin Portal.

## Channels

| Channel | How it connects |
| --- | --- |
| Website chat | the PHP front end calls `POST /web/chat` with the site key; counsellor replies come through `GET /web/messages` |
| WhatsApp | Meta Cloud API webhook → `/webhooks/whatsapp`; replies and booking confirmations go back on WhatsApp |
| Phone | an Indian number from Plivo or Exotel rings the Retell agent; Retell talks to `wss://…/llm-websocket` (speech in, text out). Disha reads numbers digit by digit, says "one moment, let me check" on slow lookups, and ends the call on "no thanks". Outgoing calls: `POST /phone/call`. |
| Voice page | `/disha/`: a browser call to the same Retell agent, with Disha's expressions following the call |

## Model

Groq, OpenAI, Claude or a local Ollama model, chosen in `.env` (`LLM_PROVIDER`), or hybrid mode: a local model for
simple questions and a cloud model for complex ones. Switch at runtime with `PUT /agent/provider`.

## Running and deploying

- Laptop: `disha-api/README.md` → "Run it locally". Test with `http://localhost:8000/test-chat/`.
- Server: `disha-api/deploy/README.md` (Ubuntu, MySQL, Caddy for HTTPS, systemd; the Admin Portal beside it).
- Website: `wordpress/README-wordpress.md` (install the plugin, point it at the API), or build the PHP front end
  from `disha-api/docs/api-for-frontend-and-admin.md`.

## Data

Tables in MySQL (`sql/schema.sql`): `conversations`, `messages`, `appointments`, `leads`, `handoffs`, `message_log`,
`courses`, `staff`, `working_hours`, `demo_slots`, `lms_sync`. The website copy lives in
`disha-api/data/website_kb.json` (generated, not in git).

## Secrets

All in `disha-api/.env` (never in git): `DATABASE_URL`, the model key, `CONSOLE_TOKEN` (data endpoints),
`SITE_KEY` (website front end), `RETELL_*`, `WA_*`, `LMS_*`. `disha-api/.env.example` lists them with comments.
