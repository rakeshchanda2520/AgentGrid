# Demo script (6–7 minutes)

Before recording: open the console URL once so the Render service is awake, and sign out.

| Time | Show | Say |
|---|---|---|
| 0:00 | Sign-in page | "AgentGrid lets businesses and agencies run AI agents on web chat, WhatsApp, Telegram and API. This is a live deployment." |
| 0:20 | Sign in as **Agency admin** | "An agency, GrowthPilot, has white-labeled the platform: their name and colours. The dashboard rolls up two client businesses." |
| 0:50 | Clients → *New client* (template: Healthcare clinic) | "Onboarding a client takes under a minute: pick a template and you get an agent, qualification rules and ready-made workflows." Delete or ignore it afterwards. |
| 1:20 | Open **Skyline Realty** → Agents → Aria → Knowledge → *Test retrieval* "payment plans" | "Agents answer from the business's own documents. Hybrid vector + keyword search; you can see exactly what the agent reads." |
| 1:50 | New tab: `/demo/skyline` → *Find my home* | "The client's website, one script tag. Aria recommends matching listings from the catalog." |
| 2:10 | Type: "I'm Rahul, 3 BHK in Whitefield, budget 1.4 crore, in 2 months, loan pre-approved, 9876543210" | "It qualifies the lead. The score comes from deterministic rules, not the model's opinion." |
| 2:40 | "Can I book a site visit?" → "option 1" | "Real availability, no double-booking." |
| 3:00 | Console → Workflows → Run history and Email outbox | "Booking and qualification triggered workflows: CRM sync, a sales alert, a confirmation with a calendar invite." |
| 3:30 | Website chat: "Does Orchid Heights have a helipad?" | "It doesn't make things up. Not in the documents, so it says so." |
| 3:50 | Website chat: "I want to talk to a person" | "Handover." |
| 4:00 | Inbox (signed in as Skyline team member, or same session) | "The team sees an AI summary, the lead card and the transcript. Claim, reply, and the customer sees it live. Suggest gives AI-drafted replies." |
| 4:40 | Channel simulator → WhatsApp / Telegram (or a real phone if connected) | "Same agent on WhatsApp and Telegram, same pipeline." |
| 5:10 | Agents → Aria → Playground: ask a question, open *Last turn* | "Every reply is explainable: graph path, tool calls, sources, latency, cost." |
| 5:30 | AI models page | "Bring your own model: OpenAI, Anthropic, Qwen, OpenRouter or a private server, per agent, with fallback." |
| 5:50 | Agents → How it works; `docs/SCALING.md` | "LangGraph with deterministic guards around the LLM. The PoC runs on Postgres; Kafka, Redis, Temporal and Airflow slot in at clear seams." |
| 6:20 | Dashboard | "Resolution, escalation, response time, funnel, cost per model. Thanks." |

## For evaluators trying it themselves

- Sign-in page → one-click demo accounts (password `AgentGrid#Demo2026`).
- `/demo/skyline` and `/demo/brightsmile`: live widgets.
- Channel simulator: WhatsApp and Telegram without a phone.
- `/docs` on the API URL: OpenAPI reference; REST channel example in Settings → API keys.
