# Security and data protection

| Area | Control (in the code) | Where |
|---|---|---|
| Tenant isolation | PostgreSQL row-level security on every tenant table, `FORCE`d so it binds the owner role too; each request sets `app.tenant_ids` to the caller's allowed workspaces for that transaction only. Platform paths (webhook routing, job claiming, seeding) use an explicit system context. App queries also filter by tenant. | `migrations/001_init.sql`, `app/db.py` |
| Isolation tests | Cross-tenant reads return 0 rows at the SQL level; API returns 404 for another tenant's conversation and 403 for a forged `X-Tenant-Id` | `tests/test_security.py` |
| AuthN | Argon2 password hashes; 60-minute JWT access tokens; rotating refresh tokens stored hashed; login rate limits per IP and per email | `app/security.py`, `app/api/auth.py` |
| AuthZ | Five roles (platform admin, agency admin, client admin, team member, viewer) mapped to permissions; every route declares the permission it needs | `app/auth.py` |
| Personal data and the LLM | Phones, emails, card numbers (Luhn), Aadhaar (Verhoeff), PAN are replaced with tokens like `<PHONE_1>` **before** storage and before the LLM sees them. Originals are encrypted per tenant and per conversation; tools resolve tokens server-side; tokens never resolve in another conversation | `app/security.py`, `app/conversations.py` |
| Secrets at rest | LLM keys, channel tokens and integration secrets are encrypted with per-tenant Fernet keys derived from a master key (KMS in production) and never returned to the browser | `app/security.py` |
| Webhooks in | Meta `X-Hub-Signature-256` HMAC verification, per-connection verify token; Telegram secret-token header; duplicate deliveries dropped by a unique index | `app/api/public.py` |
| Webhooks out | HMAC-SHA256 over `timestamp.body` (`X-AgentGrid-Signature`, `X-AgentGrid-Timestamp`) for replay protection; HTTPS only | `app/integrations.py` |
| Prompt injection | Tenant/agent ids come from server context, never from model arguments; instructions inside customer messages and documents are treated as data; citations are validated; output filter; eval suite includes injection cases | `app/agent/*`, `evals/scenarios.yaml` |
| Workflow templating | Jinja2 sandbox (no attribute access to internals); filters use whitelisted comparisons, no `eval` | `app/workflows.py` |
| Widget / API abuse | Per-visitor and per-IP message limits; per-workspace API rate limit; scoped, hashed, revocable API keys | `app/api/public.py`, `app/api/admin.py` |
| Audit | Logins (including failures), config, model and key changes, knowledge uploads, handover actions, exports, erasures | `audit_logs` |
| Privacy rights | Contact export and erase (cascade) endpoints; consent timestamp captured from the widget; retention purge of personal-data tokens | `app/api/inbox.py`, `app/conversations.py` |
| Supply chain | Locked dependencies (`uv.lock`, `package-lock.json`), non-root container user, no secrets in images, `.env` git-ignored | `Dockerfile`, `.gitignore` |

## Compliance notes

- **DPDP / GDPR**: data minimisation (masked transcripts), consent capture, export and erasure, configurable retention.
- **HIPAA-style workloads** (the clinic demo): sensitive medical topics always escalate to staff; the platform can run on a private model (Ollama/vLLM, or Bedrock in the customer's AWS account) with local embeddings, so nothing leaves their infrastructure. A dedicated database per tenant is the next step.

## Known PoC limits

- Access and refresh tokens are kept in browser storage because the console (Vercel) and API (Render) are on different sites. Production puts both under one domain and uses httpOnly cookies.
- Per-tenant keys are derived from one master key; production uses KMS-wrapped random data keys with rotation.
- Rate limits are per process (in memory); production uses Redis.
