# AgentGrid: Integration setup guide

Step-by-step instructions to get the keys for each integration and connect them to AgentGrid. Every integration is **optional**: without any of them the demo still works (web chat, the channel simulator, built-in CRM and the email Outbox).

> Third-party dashboards change their menus from time to time. If a label below doesn't match exactly, look for the closest equivalent. The values you need to copy never change.

| # | Integration | Time | Cost | Where it plugs in |
|---|---|---|---|---|
| 0 | [Before you start: your backend URL](#0-before-you-start-your-backend-url) | 2 min | – | – |
| 1 | [LLM key (OpenRouter / OpenAI / Anthropic / Qwen)](#1-llm-key) | 5 min | ~$5–10 credit | Render env var **or** Console → AI models |
| 2 | [Telegram bot](#2-telegram-bot) | 3 min | Free | Console → Agents → *agent* → Channels |
| 3 | [WhatsApp Cloud API test number](#3-whatsapp-cloud-api-test-number) | 20–30 min | Free | Console → Agents → *agent* → Channels, plus Meta dashboard |
| 4 | [Slack alerts](#4-slack-alerts) | 5 min | Free | Console → Settings → Integrations |
| 5 | [Email over SMTP (Gmail or Brevo)](#5-email-over-smtp) | 10 min | Free | Render env vars (server-wide) |
| 6 | [HubSpot CRM](#6-hubspot-crm) | 10 min | Free CRM | Console → Settings → Integrations |
| 7 | [Outbound webhooks (any system)](#7-outbound-webhooks) | 5 min | – | Console → Settings → Integrations + a workflow step |
| 8 | [Local development tunnel (optional)](#8-local-development-tunnel-optional) | 5 min | Free | Only for testing webhooks on your laptop |
| 9 | [Troubleshooting](#9-troubleshooting) | | | |

---

## 0. Before you start: your backend URL

WhatsApp and Telegram deliver messages to a **public HTTPS URL**, so connect them **after** the backend is deployed on Render.

1. Deploy the backend (README → *Deploy*). Render gives you a URL like `https://agentgrid-api.onrender.com`.
2. Open `https://agentgrid-api.onrender.com/healthz` in a browser. It must show `{"ok":true}`.
3. Use the **Starter** plan on Render. On the free plan the service sleeps after 15 minutes. Webhooks wake it up, but the first reply then takes about a minute, and outbound email may be blocked.

AgentGrid works out its own public URL on Render (Render sets `RENDER_EXTERNAL_URL`). The webhook URLs shown in the console are therefore already correct, and you never type them by hand.

Where things live in the console:
- **Channels** (Telegram, WhatsApp, widget, API): sign in as a client admin (e.g. `owner@skyline.demo`) → **Agents** → click the agent (e.g. *Aria*) → **Channels** tab.
- **Integrations** (Slack, HubSpot, webhook secret): in a **client** workspace → **Settings** → **Integrations** tab.
- **Workspace settings** (notification email): **Settings** → **Workspace** tab.

---

## 1. LLM key

Without a key the agents run on the built-in offline demo model. With a key they use a real LLM.

### 1a. Get an OpenRouter key (recommended: one key, hundreds of models)
1. Go to **https://openrouter.ai** and sign in (Google or GitHub).
2. Top-right menu → **Credits** → **Add credits**. $5–10 is plenty for building, the demo and evals.
3. Top-right menu → **Keys** → **Create Key**. Name it `agentgrid`; leave the credit limit empty or set e.g. $10.
4. Copy the key (starts with `sk-or-v1-…`). **It is shown only once.**
5. Pick model IDs on **https://openrouter.ai/models**: open a model and copy its slug, e.g. `anthropic/claude-sonnet-4.5`, `openai/gpt-4o-mini`, `qwen/qwen-2.5-72b-instruct`. Choose models that list **tool calling / tools** support.

### 1b. Connect it. Option A: platform default (all agents)
1. Render dashboard → your **agentgrid-api** service → **Environment**.
2. Set:
   | Key | Value |
   |---|---|
   | `LLM_PROVIDER` | `openrouter` |
   | `LLM_API_KEY` | `sk-or-v1-…` |
   | `LLM_MODEL` | `anthropic/claude-sonnet-4.5` (main model, needs tool calling) |
   | `LLM_CHEAP_MODEL` | `openai/gpt-4o-mini` (summaries, suggestions) |
3. **Save Changes** → Render redeploys (about 2–3 minutes).
4. Check: Console → **AI models** → the *Platform default* card shows **Connected**. Click **Test**: you should see *Works, tool calling OK*.

### 1c. Connect it. Option B: per workspace / per agent (bring your own model)
1. Console → **AI models** → **Add provider**.
2. Provider: *OpenRouter* (or OpenAI / Anthropic / Qwen / Ollama / any OpenAI-compatible URL). The base URL and suggested model names fill in automatically.
3. Paste the API key, check the model names → **Save provider** → **Test**.
4. **Agents** → *agent* → **Settings** → *AI model* → choose the provider (optionally set a fallback provider/model) → **Save changes**.
5. **Playground** tab → send a message. *Last turn* shows the model name, tokens and cost.

Other providers, where to get keys:
| Provider | Get the key | Provider type in the console | Example models |
|---|---|---|---|
| OpenAI | https://platform.openai.com/api-keys (add billing first) | OpenAI | `gpt-4.1-mini`, `gpt-4.1-nano` |
| Anthropic | https://console.anthropic.com → Settings → API keys | Anthropic | `claude-sonnet-5-5`, `claude-haiku-5-5` |
| Qwen (Alibaba Cloud Model Studio / DashScope, international) | https://modelstudio.console.alibabacloud.com → API keys | Qwen | `qwen-plus`, `qwen-turbo` |
| Ollama (private, self-hosted) | No key; run `ollama pull qwen3:8b` on a server reachable from Render | Ollama (set base URL to `http://<server>:11434/v1`) | `qwen3:8b` |

---

## 2. Telegram bot

No review, no verification, ready in minutes.

### 2a. Create the bot and get the token
1. Install Telegram (phone or https://web.telegram.org) and sign in.
2. Search for **@BotFather** (the official one has a blue check mark) and open the chat → tap **Start**.
3. Send `/newbot`.
4. BotFather asks for a **name** (shown to users), e.g. `Skyline Realty Assistant`.
5. Then a **username**, which must end in `bot`, e.g. `skyline_realty_demo_bot`.
6. BotFather replies with the **HTTP API token**, like `7712345678:AAH3kQ…`. Copy it. Treat it like a password.
7. Optional polish (in the BotFather chat):
   - `/setdescription` → "Ask about our projects, prices and site visits."
   - `/setuserpic` → upload a logo.
   - `/setcommands` → `start - Start chatting`

### 2b. Connect it to an agent
1. Console → sign in as `owner@skyline.demo` → **Agents** → **Aria** → **Channels** tab → **Telegram** card.
2. Paste the token → **Connect**.
3. You'll see *Connected @your_bot_username (webhook)*. AgentGrid has called Telegram's `setWebhook` with a secret token for you.
4. Test: open `https://t.me/<your_bot_username>` → **Start** → type "What are the prices at Orchid Heights?".
5. The conversation appears live in **Inbox**. Type "talk to a person" to test handover, then reply from the inbox: the reply arrives in Telegram.

Notes:
- **One bot = one destination.** If you run the backend locally with the same token, local mode switches the bot to *polling* and removes the Render webhook. To go back, click **Disconnect** and **Connect** again on the deployed console. Better: use a second bot for local testing.
- To connect a second agent (e.g. *Mia* for BrightSmile), create another bot with BotFather.
- To change the token: BotFather → `/revoke`, then reconnect with the new token.

---

## 3. WhatsApp Cloud API test number

Meta gives every developer app a **free test phone number**. No business verification and no display-name approval are needed. Limits: it can message **up to 5 phone numbers you register**, and the default access token **expires every 24 hours** (step 3f shows how to make a permanent one).

### 3a. Create a Meta developer account
1. Go to **https://developers.facebook.com** and log in with your Facebook account.
2. If this is your first time: **Get Started** → accept the terms → verify your phone number/email → choose *Developer* as your role.

### 3b. Create the app
1. **My Apps** → **Create App**.
2. Use case: choose **"Connect with customers through WhatsApp"** (on older layouts: *Other* → app type **Business**).
3. App name, e.g. `AgentGrid Demo`; contact email.
4. **Business portfolio**: pick an existing one or let Meta create one. No verification is needed for the test number.
5. **Create app** (re-enter your Facebook password if asked).
6. If WhatsApp isn't added automatically: on the app dashboard find **WhatsApp** → **Set up**.

### 3c. Get the three values AgentGrid needs
Open **WhatsApp → API Setup** (sometimes *Getting started*) in the left menu.
1. **Phone number ID**: under *Send and receive messages*, the "From" field shows the **test number**; right below it is the **Phone number ID** (a long number like `612345678901234`). Copy it. *(Not the WhatsApp Business Account ID; that's a different number.)*
2. **Access token**: click **Generate access token** (temporary, 24 h), log in, allow access → copy the token (starts with `EAA…`).
3. **Your phone as a recipient**: in the **"To"** field → **Manage phone number list** → **Add phone number** → enter your WhatsApp number with country code (e.g. +91 98xxxxxxx) → Meta sends a code to your WhatsApp → enter it. Repeat for up to 5 testers (e.g. an evaluator).
4. **App secret**: left menu **App settings → Basic** → **App secret** → **Show** (re-enter your password) → copy it.

### 3d. Connect in AgentGrid
1. Console → **Agents** → **Aria** → **Channels** → **WhatsApp (Cloud API test number)**.
2. Paste **Phone number ID**, **Access token**, **App secret** → **Save**.
3. The card now shows a **Callback URL** (e.g. `https://agentgrid-api.onrender.com/webhooks/whatsapp/<id>`) and a **Verify token**. Keep this tab open.

### 3e. Point Meta's webhook at AgentGrid
1. Back in Meta: **WhatsApp → Configuration**.
2. Under **Webhook** → **Edit**:
   - **Callback URL** → paste the Callback URL from AgentGrid.
   - **Verify token** → paste the Verify token from AgentGrid.
   - **Verify and save**. Meta calls the URL; AgentGrid answers the challenge. If it fails, see [Troubleshooting](#9-troubleshooting).
3. Under **Webhook fields** → **Manage** → find **messages** → **Subscribe** (only `messages` is needed) → **Done**.
4. **Test**: from your registered phone, open WhatsApp and send "Hi" to the **test number** shown on the API Setup page. Aria replies within a few seconds, and the chat appears in the console **Inbox** with a WhatsApp icon.
   - The customer must write first. That opens WhatsApp's 24-hour service window in which AgentGrid can reply freely. (Messages that start a conversation from the business side require approved templates; that's on the roadmap.)

### 3f. Stop the token expiring every 24 hours (recommended before the demo)
1. Go to **https://business.facebook.com/settings** (Business Settings for the portfolio your app uses).
2. **Users → System users** → **Add** → name `agentgrid` → role **Admin** → **Create system user**.
3. Select the system user → **Assign assets**:
   - **Apps** → your app → *Full control* (Manage app).
   - **WhatsApp accounts** → the test WhatsApp Business Account → *Full control*.
   → **Save changes**.
4. **Generate new token** → select your app → **Token expiration: Never** → permissions **`whatsapp_business_messaging`** and **`whatsapp_business_management`** → **Generate token** → copy it.
5. AgentGrid → Agents → Aria → Channels → WhatsApp → **Disconnect**, then connect again with the **same Phone number ID**, the **new token** and the app secret.
6. Because reconnecting issues a new verify token, repeat **3e step 2** (paste the new verify token, Verify and save). The callback URL stays the same.

### 3g. Let an evaluator try it
Add their number in **API Setup → To → Manage phone number list** (max 5) and share the test number with them. Anyone else can use the console's **Channel simulator**, which runs the same pipeline.

---

## 4. Slack alerts

Used by workflows (e.g. Skyline's *Hot lead → CRM + sales alert* posts "New qualified lead … score 83").

### 4a. Create an incoming webhook
1. Go to **https://api.slack.com/apps** → **Create New App** → **From scratch**.
2. App name `AgentGrid Alerts`, pick your workspace → **Create App**.
3. Left menu **Incoming Webhooks** → switch **Activate Incoming Webhooks** to **On**.
4. Bottom of the page → **Add New Webhook to Workspace** (on newer layouts: *Add New Webhook*) → choose a channel, e.g. `#sales-leads` → **Allow**.
5. Copy the **Webhook URL** (`https://hooks.slack.com/services/T…/B…/…`).
6. Optional check from a terminal:
   ```bash
   curl -X POST -H "Content-Type: application/json" -d "{\"text\":\"AgentGrid test\"}" https://hooks.slack.com/services/XXX/YYY/ZZZ
   ```

### 4b. Connect it
1. Console → client workspace (e.g. Skyline) → **Settings** → **Integrations** → **Slack** → paste the URL → **Save**. The badge turns *Connected*.
2. Test: qualify a lead (website chat or playground: "I'm Rahul, 3 BHK in Whitefield, budget 1.4 crore, in 2 months, loan pre-approved, 9876543210"). Within seconds Slack shows the alert. **Workflows → Run history** shows the *Post to Slack* step as succeeded.
3. To alert on other events, edit a workflow → add a step with action **Post to Slack** (`notify.slack`) and params like `{"text": "Booked: {{ appointment.when }}"}`.

---

## 5. Email over SMTP

Without SMTP, every email a workflow sends (lead alerts, booking confirmations with a calendar invite) is kept in **Workflows → Email outbox**. That's enough for a demo. Add SMTP to actually deliver them. SMTP is **server-wide**, set with environment variables. AgentGrid uses **STARTTLS on port 587**.

### 5a. Option 1: Gmail (quickest)
1. Use a Gmail account you control (a fresh one for demos is fine).
2. Turn on **2-Step Verification**: https://myaccount.google.com/security → *2-Step Verification*.
3. Create an **App password**: https://myaccount.google.com/apppasswords → name it `AgentGrid` → **Create** → copy the 16-character password (remove spaces).
4. Values:
   | Variable | Value |
   |---|---|
   | `SMTP_HOST` | `smtp.gmail.com` |
   | `SMTP_PORT` | `587` |
   | `SMTP_USER` | `yourname@gmail.com` |
   | `SMTP_PASSWORD` | the 16-character app password |
   | `SMTP_FROM` | `Skyline Realty <yourname@gmail.com>` (Gmail sends as your address) |
   Limit: about 500 emails/day.

### 5b. Option 2: Brevo (free 300 emails/day, custom sender name)
1. Sign up at **https://www.brevo.com** and confirm your email.
2. **Senders, domains & dedicated IPs → Senders → Add a sender** → use an email you own → click the confirmation link Brevo sends.
3. **SMTP & API → SMTP** tab → **Generate a new SMTP key** → copy it.
4. Values: `SMTP_HOST=smtp-relay.brevo.com`, `SMTP_PORT=587`, `SMTP_USER=` the **login** shown on that page (looks like `8a1b2c001@smtp-brevo.com`), `SMTP_PASSWORD=` the SMTP key, `SMTP_FROM=AgentGrid Demo <the-sender-you-verified>`.

### 5c. Set the variables
- **Render**: service → **Environment** → add the five variables → **Save Changes** (it redeploys).
- **Local**: add them to `backend/.env` and restart the API.

### 5d. Make sure emails go to a real inbox
The demo workspaces use fake addresses (`sales@skyline.demo`). Change them:
1. Console → Skyline workspace → **Settings** → **Workspace** → **Notification email** → your real address → **Save**. (Same for BrightSmile.)
2. Booking confirmations go to the **customer's email** if they gave one in chat, otherwise to the notification email.
3. Test: book a site visit in the website chat. **Workflows → Email outbox** shows status **sent** (or **failed** with the reason), and your inbox receives the confirmation with an `invite.ics` attachment.

---

## 6. HubSpot CRM

Qualified leads are always written to AgentGrid's built-in CRM (Leads page). With HubSpot connected, the *Sync to CRM* workflow step also creates the contact in HubSpot.

1. Create a free account at **https://www.hubspot.com** (Free CRM) if you don't have one.
2. Click the **gear icon (Settings)** → left menu **Integrations → Private Apps**.
   (On newer accounts this may be under **Development → Legacy apps → Create a private app**.)
3. **Create a private app** → *Basic info*: name `AgentGrid`.
4. **Scopes** tab → search and tick:
   - `crm.objects.contacts.write`
   - `crm.objects.contacts.read`
5. **Create app** → confirm → **Show token** → copy it (starts with `pat-`).
6. Console → client workspace → **Settings** → **Integrations** → **HubSpot** → paste → **Save**.
7. Test: qualify a lead (score ≥ 60) → HubSpot → **CRM → Contacts** shows the new contact. In AgentGrid, **Workflows → Run history** shows `hubspot: <contact id>`, and the lead's details show *CRM: builtin, hubspot synced*. A contact whose email already exists counts as synced.

---

## 7. Outbound webhooks

Send AgentGrid events to any system (Zapier, Make, n8n, your own backend).

1. Console → **Settings** → **Integrations** → **Outbound webhooks** → enter a long random secret → **Save**.
2. **Workflows** → edit or create a workflow → add a step:
   - Action: **Call webhook** (`webhook.post`)
   - Params: `{"url": "https://your-system.example.com/agentgrid"}` (HTTPS required)
3. Each call is a JSON `POST` with headers `X-AgentGrid-Timestamp` and `X-AgentGrid-Signature: sha256=<hex>`, where the signature is HMAC-SHA256 over `"<timestamp>." + raw body` using your secret. Verify it on your side:
   ```python
   import hashlib, hmac, time

   def verify(secret: str, body: bytes, ts: str, sig: str) -> bool:
       if abs(time.time() - int(ts)) > 300:  # reject replays older than 5 minutes
           return False
       expected = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
       return hmac.compare_digest(expected, sig)
   ```
4. Quick test without code: use a request-bin URL (e.g. https://webhook.site) as the `url`, trigger the event, and watch the payload arrive.

Inbound integration (your system → agent) uses the REST channel: **Settings → API keys → Create key**, then `POST /v1/messages` (example on that page and at `/docs`).

---

## 8. Local development tunnel (optional)

Only needed to test **WhatsApp** webhooks against your laptop. Telegram works locally without this (polling), and everything else doesn't need it.

1. Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
2. Run the API locally, then:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
3. Copy the `https://<random>.trycloudflare.com` URL it prints.
4. In `backend/.env` set `PUBLIC_API_URL=https://<random>.trycloudflare.com` and restart the API. Telegram switches to webhook mode, and the WhatsApp callback URL in the console uses the tunnel.
5. In Meta, set the Callback URL to the tunnel one (step 3e). The tunnel URL changes every run, so for the demo use the Render URL.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Meta: *"The callback URL or verify token couldn't be validated"* | Backend not reachable (open `/healthz`), or the verify token doesn't match the one currently shown in AgentGrid (reconnecting creates a new one). If Render was asleep, wait a minute and press Verify again. |
| WhatsApp message sent but no reply | `messages` webhook field not subscribed (3e.3); your number isn't in the recipient list (3c.3); access token expired (24 h, see 3f); you messaged a different number than the test number. **Settings → Failed jobs** shows errors such as `WhatsApp send failed 401`. |
| WhatsApp error `(#131030) Recipient phone number not in allowed list` | Add the number under API Setup → To → Manage phone number list. |
| WhatsApp error `(#131047)` / re-engagement message | More than 24 h since the customer's last message. Have them message the test number again. |
| Telegram bot doesn't answer | Token reconnected on another environment (local polling vs Render webhook). Reconnect on the environment you want. Check that `PUBLIC_API_URL` / Render URL is HTTPS. |
| Slack step shows *skipped: Slack not connected* | The webhook is saved per client workspace; save it in the workspace whose agent ran. |
| Email outbox shows **failed** | Gmail: use an app password (not your normal password) and port 587. Brevo: the sender must be verified and the login is the SMTP login, not your email. Render's free plan may block outbound SMTP; use Starter. |
| Emails show **stored** but never arrive | SMTP isn't configured (expected behaviour), or the recipient is a fake demo address: set a real Notification email (5d). |
| HubSpot step error `401` / `403` | Token missing the `crm.objects.contacts.write` scope, or it was rotated. Create a new token and save it again. |
| *Platform default: offline demo model* after adding a key | Render didn't redeploy, or `LLM_API_KEY` has a typo. AI models → Test shows the provider's error message. |
| Replies say "not sure" too often with a real model | Upload more knowledge (Agents → Knowledge), and use *Test retrieval* to see what the agent reads. |

Security reminders: tokens and keys are stored encrypted per workspace and never shown again in the console. Don't commit them to git (`.env` is ignored). Rotate any key that appears in a screenshot or video.
