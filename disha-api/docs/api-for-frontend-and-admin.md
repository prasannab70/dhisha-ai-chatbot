# Disha API: what the PHP front end and the admin side call

Base address: `http://localhost:8000` on a laptop, `https://disha.dhishaai.com` on the server.
Every request and reply is JSON unless noted. Interactive reference with "try it" buttons: `/docs`.

## 1. Website chat (the PHP chat widget)

Header on every call: `X-Site-Key: <SITE_KEY from .env>`. Keep the key on the server side (PHP), never in the
browser; the browser talks to your PHP page, and PHP calls Disha.

| Call | Body / query | Reply |
| --- | --- | --- |
| `POST /web/chat` | `{"visitor_id": "<random id you keep per visitor>", "text": "What courses do you offer?"}` optional `"name"`, `"phone"` | `{"reply": "...", "muted": false, "conversation_id": "web:<visitor_id>", "last_id": 12}` |
| `GET /web/messages?visitor_id=<id>&after=<last_id>` | poll every few seconds while `muted` is true | `{"messages": [{"id": 13, "from": "counsellor", "text": "..."}], "muted": true, "last_id": 13}` |

- `visitor_id`: letters, digits, `-`, `_`; up to 40 characters. Use the same id across pages so the conversation
  continues (a cookie or localStorage value).
- `muted: true` means a counsellor has taken over that chat; Disha stops answering and the counsellor's replies
  arrive through `/web/messages`.
- `reply` may contain simple Markdown (`**bold**`, bullet lines, links).
- Errors: `401` wrong site key, `422` empty text, `429` too many messages (20 per minute per visitor and per IP),
  `502` the model failed.

PHP example:

```php
$r = curl_init('https://disha.dhishaai.com/web/chat');
curl_setopt_array($r, [
  CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 90,
  CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-Site-Key: ' . SITE_KEY],
  CURLOPT_POSTFIELDS => json_encode(['visitor_id' => $visitorId, 'text' => $text]),
]);
$reply = json_decode(curl_exec($r), true);   // $reply['reply']
```

A complete working PHP front end is in `wordpress/disha-receptionist/` (a WordPress plugin: bubble, chat panel,
polling for counsellor replies). Copy from it or install it as it is.

## 2. Voice ("Talk to Disha AI")

The page `/disha/` is ready to use or to embed in an iframe. If you build your own page:

| Call | Reply |
| --- | --- |
| `GET /voice/config` | `{"ready": true, "agent_id": "agent_..."}` |
| `POST /voice/web-call` | `{"access_token": "...", "call_id": "..."}` → start the call with Retell's browser SDK (`retell-client-js-sdk`, bundled at `/disha/retell-sdk.js`): `new RetellWebClient().startCall({accessToken})` |

Phone calls need no front end: the number (Plivo/Exotel) rings the Retell agent, which talks to this API over
`wss://<host>/llm-websocket`.

## 3. Data for the admin side

Header on every call: `Authorization: Bearer <CONSOLE_TOKEN from .env>`.

### Every table, as JSON or CSV

| Call | Reply |
| --- | --- |
| `GET /console/tables` | `[{"table": "appointments", "rows": 42, "columns": [...]}, ...]` |
| `GET /console/tables/{table}?limit=200&offset=0` | `{"columns": [...], "rows": [[...], ...]}` newest first |
| `GET /console/tables/{table}/csv` | the whole table as a CSV file (`Content-Disposition: attachment`), opens in Excel |

Tables and what the user gave:

| Table | Holds |
| --- | --- |
| `appointments` | every booking: type (demo / counselling), date, time, student name, phone, course, who it is for, counsellor, source (bot_chat / bot_call), status |
| `leads` | every person who gave a number: name, phone, course of interest, source, note (enquiry / booked / brochure / callback: reason) |
| `handoffs` | callbacks requested and counsellor handoffs: conversation, channel, summary, preferred time, done |
| `conversations` | one per visitor / WhatsApp number / call: phone, name, channel, whether a counsellor owns it |
| `messages` | every message of every conversation (user, Disha, counsellor, tool calls) |
| `message_log` | WhatsApp sends (confirmations, reminders) and their status |
| `courses`, `staff`, `working_hours`, `demo_slots` | the catalogue, counsellors and timings Disha books against |
| `lms_sync` | what was sent to the admin portal (status, error, portal enquiry id) |

### Ready-made views

| Call | Reply |
| --- | --- |
| `GET /console/summary` | bookings today, bookings made by Disha, handoffs waiting, leads |
| `GET /console/appointments?from_date=YYYY-MM-DD` | upcoming bookings with counsellor and course names |
| `GET /console/leads` | latest 100 leads |
| `GET /console/handoffs` | callbacks and handoffs, newest first |
| `GET /console/conversations?limit=100` | latest conversations |
| `GET /console/conversations/{id}/messages?tools=false` | one conversation's transcript |
| `GET /console/staff` · `PUT /console/staff/{id}/status {"status": "online|busy|out"}` | counsellor presence (Disha only connects callers to online counsellors) |
| `POST /console/conversations/{id}/reply {"text", "staff_name"}` | a counsellor answers inside a chat (WhatsApp threads get the message on WhatsApp) |
| `POST /console/handoffs/{id}/release` | give the chat back to Disha / mark a callback done |

### Admin portal (the Node app)

With `LMS_URL`, `LMS_EMAIL`, `LMS_PASSWORD` set, every lead, booking, brochure request and callback is also created
as an **Enquiry** in the portal (or a follow-up on the open enquiry for that number), so the admin sees them there
without calling this API. `GET /admin/lms-status`, `POST /admin/lms-check`, `POST /admin/lms-retry`.

### Website knowledge

`GET /admin/website-status` (what was read from dhishaai.com and when); `POST /admin/refresh-website` (re-read now).
Bearer token on both.

## 4. Webhooks (set once, no front end)

| System | Address |
| --- | --- |
| Meta WhatsApp | `https://<host>/webhooks/whatsapp` (verify token = `WA_VERIFY_TOKEN`) |
| Retell agent (Custom LLM) | `wss://<host>/llm-websocket` |
