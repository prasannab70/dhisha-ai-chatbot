# Disha — Retell AI phone agent setup

Everything to paste into Retell to build Disha's phone agent as a **Conversation Flow** that calls the Disha backend for every fact and action.

Replace before pasting:
- `https://YOUR-HOST` → your backend address (ngrok URL while testing, `https://api.dhishaai.com` in production)
- `YOUR_RETELL_SECRET` → the value of `RETELL_SECRET` in `disha-api/.env`
- `+91XXXXXXXXXX` → the front-desk fallback number

---

## 1. Short description (for Retell's "describe your agent" / AI flow builder)

```
Disha is the AI phone receptionist for DhishaAI Complete Analytics, an analytics and AI training institute in Whitefield, Bengaluru. She answers inbound calls in friendly Indian English, short sentences, at most two sentences per turn.

She helps callers with five things:
1. Course information: lists courses grouped by track (Analytics & BI, Programming & Data Science, Data Engineering & Cloud, AI & GenAI) with fee, duration, mode and next batch, and recommends one course after asking at most three questions (background, goal, weekday or weekend).
2. Booking: a free counselling session with a named counsellor, or a free demo class. She asks which of the two they want, who it is for, the course, the date and time, offers at most three free slots, reads back a summary, and books only after the caller clearly says yes.
3. Brochure: sends the course brochure PDF on WhatsApp to the number the caller confirms.
4. Office location and directions: gives the address and landmark, sends the location pin on WhatsApp, and gives directions by bike, bus/metro or car with a leave-by time.
5. Talk to a person: checks which counsellors are online and transfers the call with a short summary; if nobody is online, creates a callback request.

Rules: every fee, date, slot and counsellor name comes from a function call, never from memory. Never book or send anything without a phone number the caller confirmed. Confirm names and numbers back digit by digit. She does not take payments, enrolments, refunds or discounts; those go to a counsellor. If she fails to understand the caller twice, or the caller asks for a human, she transfers or creates a callback.
```

---

## 2. Global prompt (Conversation Flow → Global Prompt)

```
## Identity
You are Disha, the receptionist of DhishaAI Complete Analytics, an analytics, AI and data training institute at Arya Hub Mall, Prasanth Extension, Whitefield, Bengaluru. You are on a phone call.

## Style
- Warm, polite Indian English. Short: at most 2 sentences per turn, then let the caller speak.
- Never read out lists longer than 3 items; offer "shall I tell you more?".
- Say times as "eleven a.m.", dates as "Saturday, the twenty-fifth", fees as "eighteen thousand rupees".
- Read phone numbers back in groups: "nine eight seven six five, four three two one zero — is that right?"
- Current date and time: {{current_time_Asia/Kolkata}}. Caller's number (may be empty): {{user_number}}.

## Facts come only from functions
- Courses, fees, batches: get_courses. Counsellors and who is in: get_available_staff. Free times: get_slots. Address: get_office_address. Directions: get_directions.
- If a function returns "error", tell the caller simply and offer another option or a callback. Never invent fees, dates, names or slots.

## Phone numbers
- Ask: "Shall I send the details on WhatsApp to the number you're calling from?" If yes, use {{user_number}}. If no, or it is empty, ask for the number and read it back.
- Call save_caller as soon as the caller tells you their name or a number.

## Booking
- First settle WHICH: "a free counselling session with a counsellor, or a free demo class?" Once chosen, never switch it unless the caller asks.
- Collect: who it is for (self, child, someone else), student name, course, counsellor (counselling only), date. Call get_slots and offer at most 3 times.
- Read back: type, course, counsellor, day, date, time, student name, WhatsApp number. Call book_slot ONLY after an explicit "yes".
- If book_slot says the slot is taken, apologise and offer the next free slots.

## Hand over
- Caller asks for a person, or you fail to understand twice, or the topic is payment, enrolment, refund, discount or a complaint: call get_available_staff, then handoff to an online counsellor with a one-line summary. If nobody is online, create_callback with their preferred time.

## Scope
You inform, book counselling and demo classes, send brochures, give directions, and hand over. Nothing else. Politely decline unrelated requests.
```

**Begin message:**
```
Hello, thank you for calling DhishaAI Complete Analytics. This is Disha. How can I help you today?
```

---

## 3. Flow (nodes)

| # | Node | Type | What it does | Exits |
| --- | --- | --- | --- | --- |
| 1 | Greeting | Conversation | Begin message; listen for the intent | Courses → 2 · Book → 4 · Brochure → 7 · Address/directions → 8 · Person → 10 · Unclear twice → 10 |
| 2 | Courses | Conversation (+ function `get_courses`) | Lists tracks, then courses on request; fee/duration/next batch | Wants a recommendation → 3 · Wants to book → 4 · Brochure → 7 · Done → 12 |
| 3 | Recommend | Conversation | Max 3 questions (background, goal, weekday/weekend), one course with a reason | Book → 4 · Brochure → 7 · Done → 12 |
| 4 | Booking type | Conversation | "Counselling or demo class?", who it's for, name, course, counsellor, date; `save_caller` | Details complete → 5 |
| 5 | Slots | Function `get_slots` → Conversation | Offers at most 3 times | Time chosen → 6 · No suitable time → 11 |
| 6 | Confirm and book | Conversation → Function `book_slot` | Reads the summary, waits for "yes", books | Booked → 12 · Slot taken → 5 |
| 7 | Brochure | Conversation → Function `send_brochure` | Confirms the WhatsApp number, sends the PDF | → 12 |
| 8 | Address | Function `get_office_address` → Conversation | Address, landmark, metro; pin sent on WhatsApp; "coming by bike, bus or car?" | Mode given → 9 · Done → 12 |
| 9 | Directions | Function `get_directions` → Conversation | Time, route, leave-by time | → 12 |
| 10 | Hand over | Function `get_available_staff` → Function `handoff` → Transfer Call | Transfers to `{{transfer_to}}`; whisper: `{{summary}}` | Nobody online / transfer fails → 11 |
| 11 | Callback | Conversation → Function `create_callback` | Preferred time; confirms a counsellor will call | → 12 |
| 12 | Anything else / goodbye | Conversation → End Call | "Is there anything else?" → back to 1, or a polite goodbye | End |

Transfer node: if your Retell version supports response variables on custom functions, map `transfer_to` and `summary` from the `handoff` response into dynamic variables and set the Transfer Call number to `{{transfer_to}}`. Otherwise transfer to the fixed front-desk number `+91XXXXXXXXXX`. Ring timeout 25 seconds; on no answer go to node 11.

---

## 4. Custom functions

For every function:
- **Method:** POST
- **URL:** `https://YOUR-HOST/webhooks/retell/<function name>`
- **Header:** `X-Retell-Secret: YOUR_RETELL_SECRET`
- **Payload:** the default (args nested under `args`; do **not** tick "args only / payload at root")
- **Speak during execution:** on for slow ones (`get_slots`, `book_slot`, `handoff`), e.g. "One moment, let me check."
- **Timeout:** 10 seconds

| Name | Description (paste into Retell) | Parameters (JSON schema) |
| --- | --- | --- |
| `save_caller` | Records the caller's name and/or WhatsApp number. Call only when the caller just said a name or number. | `{"type":"object","properties":{"name":{"type":"string"},"phone":{"type":"string"}}}` |
| `get_courses` | Course list with id, track, fee, duration, mode, next batch, who it suits. Pass a word to filter, or nothing for all. | `{"type":"object","properties":{"query":{"type":"string"}}}` |
| `get_company_info` | Facts from the official website dhishaai.com: about us, vision, values, founders, services, products, industries, clients, reviews, careers, internships, upcoming batch, contact and social media. Pass the caller's question as topic. | `{"type":"object","properties":{"topic":{"type":"string"}},"required":["topic"]}` |
| `get_available_staff` | Counsellors and their live status (online, busy, out). Use before offering a transfer. | `{"type":"object","properties":{}}` |
| `get_slots` | Free slots. type counselling needs person (counsellor name); type demo is the demo class. date is YYYY-MM-DD. The first type is locked; set caller_changed_mind=true only if the caller explicitly switched. | `{"type":"object","properties":{"type":{"type":"string","enum":["counselling","demo"]},"person":{"type":"string"},"date":{"type":"string"},"caller_changed_mind":{"type":"boolean"}},"required":["type","date"]}` |
| `book_slot` | Two steps. confirmed=false: checks the details and returns a summary to read back (nothing booked). confirmed=true: books, only after the caller said yes to that summary, with the same details. | `{"type":"object","properties":{"type":{"type":"string","enum":["counselling","demo"]},"person":{"type":"string"},"date":{"type":"string"},"time":{"type":"string","description":"HH:MM 24-hour"},"student_name":{"type":"string"},"phone":{"type":"string"},"course":{"type":"string"},"for_whom":{"type":"string"},"confirm_to":{"type":"string"},"confirmed":{"type":"boolean"}},"required":["type","date","time","student_name","course"]}` |
| `send_brochure` | Sends the course brochure PDF on WhatsApp to the number the caller confirmed. | `{"type":"object","properties":{"course_id":{"type":"string"},"phone":{"type":"string"}},"required":["course_id","phone"]}` |
| `get_office_address` | Office address, landmark, nearest metro, hours and map link; also sends the location pin on WhatsApp. | `{"type":"object","properties":{}}` |
| `get_directions` | Directions from the caller's area by bus, bike or car: minutes, route, leave-by time. | `{"type":"object","properties":{"origin":{"type":"string"},"mode":{"type":"string","enum":["bus","bike","car"]},"arrive_by":{"type":"string"}},"required":["origin","mode"]}` |
| `handoff` | Transfers the call to a named online counsellor with a 1–2 line summary. Returns transfer_to. Fails if they are not online. | `{"type":"object","properties":{"staff_name":{"type":"string"},"summary":{"type":"string"}},"required":["staff_name","summary"]}` |
| `create_callback` | Creates a callback request when nobody suitable is online. | `{"type":"object","properties":{"phone":{"type":"string"},"name":{"type":"string"},"reason":{"type":"string"},"preferred_time":{"type":"string"}},"required":["reason"]}` |

The backend reads the caller's number from Retell's `from_number` automatically, so bookings are linked to the number that called even if the model leaves `phone` empty.

---

## 5. Agent settings

| Setting | Value |
| --- | --- |
| Voice | An Indian-English female voice; test 2–3 and pick the clearest |
| Language | English (India) |
| Response eagerness / interruption | Medium; allow interruptions |
| Reminder when silent | After 8 seconds: "Are you still there?"; end after 2 reminders |
| Max call duration | 8 minutes (cost cap, README F22) |
| Backchannel | On ("mm-hmm", "okay") |
| Post-call analysis | Summary, intent (courses / booking / brochure / directions / human), booked yes/no |
| Webhook (call events, optional) | `https://YOUR-HOST/webhooks/retell/call_event` (not built yet; skip for now) |

---

## 6. Test before connecting a phone number

1. Backend running on Groq, reachable through ngrok; `RETELL_SECRET` set in `.env`.
2. In Retell, use **Test Agent → web call** from the browser.
3. Try: "What courses do you have?", "Book a demo class for Power BI on Saturday", "Send me the brochure", "Where is your office? I'm coming by bus from Marathahalli", "Can I talk to someone?".
4. Watch the uvicorn terminal for `POST /webhooks/retell/<tool>` lines and the Front Desk console for the booking with the "via bot · call" badge.
5. Only then connect the Exotel number (SIP trunk) for real calls.

---

## 7. Alternative: Custom LLM (Disha's own brain on calls)

Instead of Retell's built-in model plus 10 custom functions, Retell can ask the Disha backend for every reply over a WebSocket. Then phone calls use exactly the same prompt, tools and model (Groq / Ollama / Anthropic) as the website and WhatsApp.

1. In Retell: create an agent with **Response Engine = Custom LLM**.
2. WebSocket URL: `wss://YOUR-HOST/llm-websocket` (Retell adds `/{call_id}` itself).
3. No custom functions and no prompt are needed in Retell; the begin message is sent by the backend.
4. Use Groq (or Anthropic), not Ollama on a CPU laptop: each spoken turn must come back in about 1–2 seconds.
5. Transfers: when Disha hands off, the backend returns the counsellor's number as `transfer_number` and Retell transfers the call.

Code: `app/routers/retell_llm.py`.


### What the backend does on calls (Custom LLM mode)

- Waits 0.6 s for the caller's sentence to settle and answers only the final version; one model call at a time per call.
- Spoken numbers become digits before the model sees them; a number said in two pieces is joined ("Mm-hmm, go on" in between); numbers are read back digit by digit.
- "Thank you" → "You're welcome! Anything else?"; "no thanks", "that's all", "bye", or "no" after "anything else?" → goodbye and the call ends. None of these use the model.
- "(unintelligible audio)" gets "Could you say it once more?" without the model.
- Off-topic questions (maths, general knowledge, etc.) are declined.
- Model choice follows `LLM_MODE` / `LLM_PROVIDER` (single) or the hybrid settings; see README section 2.2.
- Test without Retell: `python scripts\test_retell_ws.py` (local) or `python scripts\test_retell_ws.py wss://your-domain/` (through ngrok).


### Website knowledge (both modes)

Disha answers questions about DhishaAI only from the official website (`disha-api/app/knowledge.py`, read 22 Oct 2026). The website's four programmes (Agentic AI and AI Agents, Data Science, Data Analytics, Excel Pro+) are added to the existing courses. Company topics: founders, services, products, industries, clients, reviews, careers and contact. For the website programmes, fees, timings and class mode are not published, so Disha offers a counsellor for those. In Custom LLM mode this works automatically; in the function mode add the `get_company_info` function above.
