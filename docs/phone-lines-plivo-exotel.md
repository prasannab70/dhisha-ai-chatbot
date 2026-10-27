# Indian phone number for Disha: Plivo or Exotel

```
Caller ──> Plivo or Exotel number ──(SIP trunk)──> Retell (speech) ──(WebSocket)──> Disha backend (answers, bookings)
```

Retell and the backend stay the same. Only the phone company in front of Retell changes.

- **Incoming calls:** import both numbers into Retell and attach the same agent. Calls to either number work.
- **Outgoing calls:** Disha calls from the number of the active line, set by `PHONE_PROVIDER` (`plivo` or `exotel`).

## 1. Plivo (about ₹200 a month for the number, ₹0.38 a minute, pay as you go)

1. Create a Plivo account, complete KYC, and rent an Indian number (Phone Numbers -> Buy).
2. Go to SIP Trunking -> Credentials and add a username (5-20 letters or digits) and a password (5-20 characters, including one special character such as `@`).
3. Go to SIP Trunking -> Outbound trunk, create a trunk with that credential, and copy its **Termination SIP Domain** (`<trunk_id>.zt.plivo.com`).
4. Go to SIP Trunking -> Origination URI and add `sip.retellai.com;transport=tcp`. Create an **Inbound trunk** with this URI and assign your number to it.
5. In Retell, go to Phone Numbers -> + -> Connect via SIP trunking:
   - **Number:** the Plivo number in +91 format.
   - **Termination URI:** `<trunk_id>.zt.plivo.com` (no `sip:` prefix).
   - **Transport:** TCP.
   - **Username/password:** from step 2.
   - **Test SIP Connection:** should return 2xx. Then Save.
6. Attach the Disha agent (the Custom LLM one) for **inbound and outbound**.

Guide: https://docs.plivo.com/docs/voice-agents/sip-trunking/integration-guides/retell

## 2. Exotel (plan from ₹9,999 for 5 months, includes 1 number)

1. Complete KYC and ask Exotel (hello@exotel.com) to enable SIP trunking for Retell.
2. Set up the trunk (by API, or ask Exotel support to do it):
   - Create the trunk: `/trunks`.
   - Map your number: `/trunks/<trunk_sid>/phone-numbers`.
   - Add the destination URI `sip:sip.retellai.com:5060;transport=tcp`.
   - Add the credentials (username/password).
3. In App Bazaar, create a flow with a **Connect** applet. Set **Dial whom** to `sip:<trunk_sid>`, and attach the flow to the number.
4. In Retell, import the number the same way as Plivo step 5, using the termination address Exotel gives you.
5. Attach the same Disha agent for inbound and outbound.

Guide: https://docs.exotel.com/dynamic-sip-trunking/connect-exotel-sip-trunking-to-retell-ai

## 3. Tell the backend (disha-api/.env)

```
PHONE_PROVIDER=plivo          # line Disha calls OUT from: plivo | exotel
PLIVO_NUMBER=+918071234567
EXOTEL_NUMBER=+918047112233
OUTBOUND_CALLS_PER_HOUR=30
```

Restart uvicorn. The `retell heard` lines in the log now also show which line a call came in on.

## 4. Switch lines and make Disha call someone

These requests use your `CONSOLE_TOKEN` (Windows `curl.exe`):

```
REM which line is active
curl.exe -H "Authorization: Bearer change-me-too" http://localhost:8000/phone/line

REM switch outgoing calls to Exotel (until restart; change PHONE_PROVIDER in .env to make it permanent)
curl.exe -X PUT -H "Authorization: Bearer change-me-too" -H "Content-Type: application/json" -d "{\"provider\":\"exotel\"}" http://localhost:8000/phone/line

REM Disha calls Kumar from the active line
curl.exe -X POST -H "Authorization: Bearer change-me-too" -H "Content-Type: application/json" -d "{\"to\":\"98765 43210\",\"name\":\"Kumar\",\"reason\":\"the callback you asked for\"}" http://localhost:8000/phone/call
```

On a call she places, Disha opens with: "Hello Kumar, this is Disha from DhishaAI Complete Analytics. I'm calling about the callback you asked for. Is this a good time to talk?"

## Notes

- The caller's number is cleaned up from either company's format (`09876543210`, `919876543210`, `+919876543210`) to `+91 98765 43210`. Callbacks and bookings therefore get the right number.
- **Rules for Indian numbers:** TRAI rules may require voice AI calls on Indian numbers to be handled by servers in India, and Retell is hosted outside India. Confirm with Retell and the phone company before going live.
- **Outgoing call limits:** call only people who asked to be called (callbacks, demo reminders). Keep to 9:00-20:00, and respect DND for promotional calls.
- **Cost:** Retell adds about ₹6 a minute on every call, whichever line you use.
