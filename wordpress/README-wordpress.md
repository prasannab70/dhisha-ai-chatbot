# Disha on the WordPress website

```
Visitor's browser  ──>  dhishaai.com (WordPress + Disha Receptionist plugin)  ──>  Disha API (/web/chat)
                         adds the secret site key here                            same brain as WhatsApp and calls
```

WordPress cannot run Python, so the plugin does not contain Disha itself. It shows the chat and passes messages
to your Disha backend. The site key stays on the WordPress server; visitors never see it.

## What you get

- **Chat bubble** ("Chat with Disha", with Disha's face) at the bottom right of every page. It opens a chat panel
  with suggested questions.
- **`[disha_chat]` shortcode** that shows the chat inside any page, for example a "Talk to us" page.
- **Conversation follows the visitor:** the same chat continues as they move between pages.
- **Counsellor replies:** when a counsellor takes over in the Front Desk console, their replies appear in the
  visitor's chat in orange.
- **"Talk to Disha" button** (optional) that opens your voice page.
- **Settings page** with a **Test connection** button.

## Step 1: Prepare the backend (`disha-api\.env`)

```
SITE_KEY=<make up a long random secret, e.g. dk_7f3a9c2e81b44d0f>
```

Restart uvicorn after changing it.

The website must be able to reach the backend:
- **On the server:** `https://disha.dhishaai.com` (see `disha-api/deploy/README.md`).
- **While testing from a laptop:** keep ngrok running and use its https address instead.

## Step 2: Install the plugin

1. WordPress admin -> **Plugins -> Add New -> Upload Plugin**.
2. Choose `disha-receptionist.zip`, then click **Install Now** and **Activate**.

## Step 3: Settings (Settings -> Disha Receptionist)

| Field | Value |
| --- | --- |
| Disha API address | `https://disha.dhishaai.com` (no slash at the end) |
| Site key | the same `SITE_KEY` as in `.env` |
| Chat bubble | ticked |
| Bubble label / first message / suggested questions | change if you like |
| Voice page (optional) | `https://disha.dhishaai.com/disha/` |

Click **Save**, then **Test connection**:
- "Connected to Disha ... The chat is ready." means it works.
- "site key is wrong" means `SITE_KEY` in `.env` and the plugin don't match.
- "Could not reach" means the backend isn't running, or the address is wrong.

## Step 4: Try it

Open the website in a private window. Click **Chat with Disha** and ask "What courses do you offer?". The chat
also appears in the Front Desk console as `web:v...`.

To put the chat inside a page: **Pages -> Add New**, add a Shortcode block with `[disha_chat]`, and publish.

## If something doesn't work

| Problem | Fix |
| --- | --- |
| The bubble doesn't appear | Check that Chat bubble is ticked and the API address is filled in. Clear the cache in LiteSpeed Cache, WP Rocket or a similar plugin. |
| "Disha is not reachable right now" | The backend or ngrok is down, or the address is wrong. Use **Test connection**. |
| Replies never arrive, or the chat shows an old reply | A caching or security plugin is caching or blocking `/wp-json/disha/`. Exclude `/wp-json/disha/*` from caching. In Wordfence or a similar plugin, allow that REST route. |
| "Too many messages" | Rate limits: 30 messages a minute per visitor in WordPress, plus `WEB_RATE_LIMIT_PER_MINUTE` in the backend. |

## Files

```
disha-receptionist/
├── disha-receptionist.php   settings page, REST proxy (/wp-json/disha/v1/chat and /messages), shortcode, bubble
└── assets/
    ├── widget.js            chat bubble and panel
    ├── widget.css           DhishaAI colours (navy #083E5A, orange #EE7600)
    └── disha.png            Disha's face
```
