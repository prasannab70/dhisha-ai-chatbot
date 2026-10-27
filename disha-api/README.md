# Disha API

The backend of Disha, DhishaAI's AI receptionist: one FastAPI service that answers the website chat, WhatsApp,
phone calls (Retell) and the "Talk to Disha AI" voice page, books demos and counselling, and stores everything in
MySQL. Company facts come from dhishaai.com itself (read automatically); every lead and booking is also pushed into
the DhishaAI Admin Portal as an enquiry.

```
Website chat (PHP front end -> POST /web/chat)  ─┐
WhatsApp (Meta Cloud API)                         ├─>  Disha API  ─>  MySQL tables (CSV download per table)
Phone (Plivo/Exotel number -> Retell)             │        │
"Talk to Disha AI" page (/disha/)                ─┘        └─>  Admin Portal (enquiries, follow-ups)
```

**For the PHP front end and the admin side:** `docs/api-for-frontend-and-admin.md` lists every call.

## What Disha does

**Answers, from DhishaAI's own information only**
- Courses: what is offered, duration, fee, mode and timings, next batch, who a course suits, what you learn
  (from the `courses` table; the four programmes on dhishaai.com are added automatically).
- The company: founders and leadership, vision and values, services, products (TimeLens, LMS), industries, clients,
  testimonials, careers and job openings, contact details, directions to the office (from the live website copy).
- Career guidance that helps a caller choose a course ("is data analytics good for a commerce graduate?").
- Anything else (maths, general knowledge, coding, jokes, other companies) is politely refused.

**Does things**
- Books a **free demo class** or a **counselling session**: shows free slots, reads the details back, books only
  on a clear "yes", sends the confirmation on WhatsApp, reminds the person before the slot.
- Sends the **course brochure** on WhatsApp.
- Takes a **callback request** with the person's name, number, reason and preferred time.
- **Connects to a counsellor** who is online (chat: the counsellor replies inside the same chat; phone: the call is
  transferred), and hands the chat back to Disha afterwards.
- Captures the person's **name and phone number** once and reuses them (no asking twice).

**Keeps records**
- Every conversation and message, every lead, booking, callback and WhatsApp send goes to MySQL; the admin side reads
  them as JSON or downloads any table as CSV.
- Every lead, booking, brochure request and callback is also created as an **enquiry in the DhishaAI Admin Portal**.

**On the phone, in addition**
- Understands numbers said in words ("nine eight seven six…", "double five") and reads them back digit by digit.
- Understands the company name however it is misheard ("this AI", "Dishay", "Nishai").
- Says "one moment, let me check that" when an answer takes long, so the caller is never left in silence.
- Ends the call politely on "thanks, that's all" / "no, nothing else".
- Can **call people** (callbacks, demo reminders) from the Plivo or Exotel number, introducing herself and the reason.

**Always**
- Company facts refresh themselves from dhishaai.com every few hours (new pages included via the sitemap).
- Temperature 0: the same question gets the same answer for everyone.
- Rate limits per visitor and per IP on the website chat; secrets stay on the server.

## Run it locally (Windows)

1. `.env`: `copy .env.example .env` and fill in at least

       DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/DATABASE?charset=utf8mb4    # the company's MySQL
       LLM_PROVIDER=groq            # and its key (GROQ_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY)
       CONSOLE_TOKEN=...            # token for the data endpoints
       SITE_KEY=...                 # key the PHP chat front end sends

   Optional: `RETELL_*` for calls and the voice page, `WA_*` for WhatsApp, `LMS_*` for the Admin Portal.
   To try things without MySQL for a moment: `DATABASE_URL=sqlite:///./local-test.db` plus `ALLOW_LOCAL_TEST_DB=true`.

2. Create the database once with `sql/schema.sql` (`mysql -u root -p < sql\schema.sql`, after setting the password
   in it), or just create an empty database and user: the API creates the tables itself on first start.

3. Python 3.11+:

       python -m venv venv && venv\Scripts\activate           # Linux/macOS: . venv/bin/activate
       pip install -r requirements.txt
       uvicorn app.main:app --reload --port 8000

   First start: tables created, starter courses / counsellors / demo slots seeded, dhishaai.com read in the
   background.

4. Check it works (test pages, not part of the product):

   | Page | What it checks |
   | --- | --- |
   | http://localhost:8000/test-chat/ | the visitor side: chat with Disha through the same calls the PHP front end makes (`POST /web/chat`, `GET /web/messages`); needs `SITE_KEY`. The bar at the top shows backend, model, website knowledge and Retell status. |
   | http://localhost:8000/test-chat/counsellor.html | the counsellor side: chats waiting for a counsellor, reply inside them, give them back to Disha; needs `CONSOLE_TOKEN`. (This is what the admin/PHP screen will do with `/console/*`.) |
   | http://localhost:8000/disha/ | the voice page (needs `RETELL_*`) |
   | http://localhost:8000/docs | every endpoint with "try it" |

   Full test run: ask about courses and founders, "What is 2+2?" (refused), book a demo, then "I want to talk to a
   counsellor" and answer from the counsellor page. Download `/console/tables/appointments/csv` to see the booking.

5. For the website chat and Retell from a laptop: `ngrok http 8000` in a second terminal.

## Deploy on the server

`deploy/README.md`: Ubuntu + MySQL + Caddy (HTTPS by itself) + systemd, with the Admin Portal beside it.

## Website knowledge (automatic)

`app/site_refresh.py` reads `WEBSITE_URL` on start and every `WEBSITE_REFRESH_HOURS` (default 6): every page in the
site's sitemap plus `WEBSITE_PAGES`, saved to `data/website_kb.json`. Disha answers company questions (founders,
services, products, careers, testimonials, offers...) only from that copy, so a new page or a changed paragraph on
dhishaai.com reaches her at the next refresh, or at once with `POST /admin/refresh-website`. Nothing about the
company is written in the code. Course durations and batch dates found on the site update the course table too.

## Admin Portal (LMS) sync

Every lead, booking, brochure request and callback is sent to the DhishaAI Admin Portal
(github.com/chandanstsmg-eng/dhishaai-admin) as an **Enquiry**, or as a follow-up on the open enquiry for that
phone number; demo bookings set the demo date and priority High. `app/lms.py`; `LMS_URL`, `LMS_EMAIL`,
`LMS_PASSWORD` in `.env` (a portal user with the counsellor role). The `lms_sync` table keeps anything the portal
could not take yet and retries every minute.

## Choosing the model (LLM_PROVIDER in .env)

| Provider | Cost | Setup |
| --- | --- | --- |
| `groq` | free tier | key from console.groq.com → API Keys. Default model `llama-3.3-70b-versatile` (good tool calling). Free-tier rate limits apply (~30 req/min); fine for a pilot. |
| `ollama` | free, local | install Ollama, `ollama pull llama3.1:8b`, keep `ollama serve` running. No key. Slower on a laptop CPU; quality lower than Groq's 70B. |
| `anthropic` | paid credits | key from console.anthropic.com. Best quality. |
| `openai` | paid | key from platform.openai.com. |

Change `LLM_PROVIDER`, restart uvicorn, then `curl localhost:8000/agent/check` reports the provider, model and a test reply.
You can also switch at runtime with `PUT /agent/provider {"provider":"groq","model":"..."}`; that lasts until
restart, `.env` makes it permanent.
Every provider is called with temperature 0, so the same question gets the same answer for everyone.

## Connect WhatsApp (Meta Cloud API)
1. Meta Business → WhatsApp → get `WA_TOKEN` and `WA_PHONE_NUMBER_ID`; put them in `.env`.
2. The API must be on HTTPS: `https://disha.dhishaai.com` (Caddy), or `ngrok http 8000` while testing.
3. In Meta's webhook settings: callback `https://<host>/webhooks/whatsapp`, verify token = `WA_VERIFY_TOKEN`,
   subscribe to `messages`.
4. Create and submit templates `booking_confirmed` (5 body params: name, what, course, when, address)
   and `appointment_reminder` (4 params: name, what, time, address). Approval takes 1–2 days.
Without a token the API logs sends as dry-run so everything else can be tested.

## Connect the phone (Retell AI)
1. Create a Retell agent with the prompt from `app/prompt.py` (phone-call variant).
2. Add one custom function per tool, URL `https://<host>/webhooks/retell/<tool_name>`,
   header `X-Retell-Secret: <RETELL_SECRET>`, parameters = the `input_schema` in `app/prompt.py`.
3. For `handoff`, the response includes `transfer_to` (the counsellor's number); use Retell's transfer call
   with that value. Buy or port a number via Retell, or connect Exotel by SIP.

## Talk to Disha AI (voice page in the browser)
`static/disha-voice/` is served at **http://localhost:8000/disha/**: Disha's face in a glowing orb with a
"Talk to Disha AI" button. It starts a Retell web call to your agent (the same Custom LLM agent the phone uses),
and Disha's expression follows the call: listening while you speak, thinking, talking/explaining while she
answers, curious after a question, goodbye when the call ends, excited on hover, sleepy when idle.
1. In `.env`: `RETELL_API_KEY=` (Retell dashboard -> API Keys) and `RETELL_AGENT_ID=` (agent id or its link).
2. Restart uvicorn and open http://localhost:8000/disha/ (allow the microphone).
3. For other devices use your https ngrok address + `/disha/` (browsers only allow the mic on https or localhost).

## Phone line: Plivo or Exotel (in front of Retell)
Import the Plivo and/or Exotel number into Retell (SIP trunking) and attach the same agent; incoming calls work on both.
`PHONE_PROVIDER` (plivo | exotel) picks the number Disha calls out from; `PLIVO_NUMBER` / `EXOTEL_NUMBER` in `.env`.
`GET/PUT /phone/line` shows or switches the line; `POST /phone/call {"to","name","reason"}` makes Disha call someone.
Step-by-step: `docs/phone-lines-plivo-exotel.md`.

## Layout
    app/main.py            FastAPI app: /web/chat, /web/messages, /agent/*, /admin/*, startup (tables, seed, refresh)
    app/agent.py           the tool-calling loop (Groq / Ollama / Claude / OpenAI, hybrid routing), temperature 0
    app/prompt.py          Disha's instructions + tool definitions
    app/tools.py           the tools (courses, slots, bookings, brochures, handoff, callbacks)
    app/knowledge.py       website programmes (COURSES) and the topic routing for company questions
    app/site_refresh.py    reads dhishaai.com (sitemap + pages) into data/website_kb.json; search over it
    app/db.py              SQLAlchemy models (MySQL);  sql/schema.sql has the same tables as DDL
    app/lms.py             sends leads, bookings and callbacks to the Admin Portal (enquiries + follow-ups)
    app/speech.py          spoken numbers -> digits, misheard company name, text -> speakable
    app/phone_line.py      Plivo / Exotel line selection and caller-number clean-up
    app/whatsapp.py        Meta Cloud API send + webhook parsing
    app/scheduler.py       reminders, lead follow-ups, website refresh, portal sync, WordPress course sync
    app/routers/           console (data + CSV), retell_llm (voice WebSocket), voice (web calls), phone (line switch,
                           outgoing calls), whatsapp, retell, tools
    static/disha-voice/    the "Talk to Disha AI" page
    static/test-chat/      test pages: visitor chat (index.html) and counsellor side (counsellor.html)
    sql/schema.sql         CREATE DATABASE / USER / TABLE statements for MySQL
    deploy/                Caddyfile, systemd units, server setup guide
    docs/                  api-for-frontend-and-admin.md (the integration contract), Retell and phone-line setup

## Guardrails built in
- No booking or brochure without a contact number the caller gave.
- `book_slot` re-checks the slot at write time; idempotency key prevents double booking on retries.
- Handoff mutes the bot on that conversation until the console releases it.
- Tool errors go back to the model as text; unexpected exceptions are logged and the caller is offered a counsellor.
