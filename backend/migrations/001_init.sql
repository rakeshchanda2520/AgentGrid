-- AgentGrid schema. Every tenant-owned table carries tenant_id and is protected by row-level security.
-- FORCE ROW LEVEL SECURITY makes policies apply to the table owner too (Render gives one DB user).
-- Request code sets app.tenant_ids (the caller's allowed tenants); a few platform paths (webhook
-- routing, job claiming, seeding) set app.system = 'on' explicitly. See app/db.py.

create extension if not exists vector;

create or replace function app_tenant_ok(t uuid) returns boolean language sql stable as $$
  select coalesce(current_setting('app.system', true), '') = 'on'
      or t = any (string_to_array(nullif(current_setting('app.tenant_ids', true), ''), ',')::uuid[])
$$;

create table tenants (
  id uuid primary key default gen_random_uuid(),
  parent_id uuid references tenants(id) on delete cascade,
  kind text not null check (kind in ('platform', 'agency', 'client')),
  name text not null,
  slug text not null unique,
  plan text not null default 'pro',
  settings jsonb not null default '{}',      -- non-secret settings (timezone, retention_days, quotas)
  secrets_enc bytea,                         -- encrypted JSON: hubspot token, slack webhook, webhook secret
  branding jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  name text not null,
  password_hash text not null,
  is_platform_admin boolean not null default false,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table memberships (
  user_id uuid not null references users(id) on delete cascade,
  tenant_id uuid not null references tenants(id) on delete cascade,
  role text not null check (role in ('agency_admin', 'client_admin', 'human_agent', 'viewer')),
  primary key (user_id, tenant_id)
);

create table refresh_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  revoked_at timestamptz
);

create table api_keys (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  prefix text not null,
  key_hash text not null unique,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);

create table llm_providers (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  kind text not null check (kind in ('openai', 'anthropic', 'openrouter', 'qwen', 'ollama', 'openai_compat')),
  base_url text,
  api_key_enc bytea,
  default_model text not null,
  cheap_model text,
  prices jsonb not null default '{}',        -- {"model": [usd_per_mtok_in, usd_per_mtok_out]}
  created_at timestamptz not null default now()
);

create table agents (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  template_key text not null,
  public_key text not null unique,
  persona text not null default '',
  provider_id uuid references llm_providers(id) on delete set null,
  model text,
  cheap_model text,
  fallback_provider_id uuid references llm_providers(id) on delete set null,
  fallback_model text,
  config jsonb not null default '{}',
  status text not null default 'active',
  created_at timestamptz not null default now()
);

create table channel_connections (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  type text not null check (type in ('whatsapp', 'telegram')),
  external_id text not null,                 -- WhatsApp phone_number_id / Telegram bot id
  secrets_enc bytea,                         -- encrypted JSON: access token / bot token / app secret
  webhook_secret text not null,
  config jsonb not null default '{}',
  status text not null default 'active',
  created_at timestamptz not null default now(),
  unique (type, external_id)
);

create table contacts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text,
  email text,
  phone text,
  channel text not null,
  channel_user_id text not null,
  consent_at timestamptz,
  attributes jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique (tenant_id, channel, channel_user_id)
);

create table conversations (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  contact_id uuid not null references contacts(id) on delete cascade,
  channel text not null,
  connection_id uuid references channel_connections(id) on delete set null,
  state text not null default 'BOT_ACTIVE'
    check (state in ('BOT_ACTIVE', 'PENDING_HUMAN', 'HUMAN_ACTIVE', 'RESOLVED')),
  assigned_user_id uuid references users(id) on delete set null,
  summary jsonb,
  memory jsonb not null default '{}',        -- agent scratchpad: offered slots, last recommendations
  tags text[] not null default '{}',
  csat smallint,
  first_response_ms integer,
  low_conf_turns integer not null default 0,
  escalated boolean not null default false,
  human_replied boolean not null default false,
  simulated boolean not null default false,
  outcome text,
  started_at timestamptz not null default now(),
  last_message_at timestamptz not null default now(),
  resolved_at timestamptz
);
create index on conversations (tenant_id, last_message_at desc);

create table messages (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'human', 'system')),
  content text not null,                     -- PII-tokenized (<PHONE_1>); see pii_tokens
  citations jsonb,
  trace jsonb,                               -- graph path + tool calls for this turn
  provider text,
  model text,
  tokens_in integer,
  tokens_out integer,
  tokens_cached integer,
  cost_usd numeric(12, 6),
  latency_ms integer,
  external_id text,
  author_id uuid,
  created_at timestamptz not null default now()
);
create index on messages (conversation_id, created_at);
create unique index messages_dedupe on messages (tenant_id, external_id) where external_id is not null;

create table pii_tokens (
  tenant_id uuid not null references tenants(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  token text not null,
  kind text not null,
  value_enc bytea not null,
  value_hash text not null,
  created_at timestamptz not null default now(),
  primary key (conversation_id, token)
);

create table leads (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  contact_id uuid not null references contacts(id) on delete cascade,
  conversation_id uuid unique references conversations(id) on delete set null,
  fields jsonb not null default '{}',
  score integer not null default 0,
  stage text not null default 'new',
  source_channel text,
  crm_ids jsonb not null default '{}',
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table appointments (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  contact_id uuid references contacts(id) on delete set null,
  conversation_id uuid references conversations(id) on delete set null,
  service text not null,
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  status text not null default 'booked' check (status in ('booked', 'cancelled', 'completed')),
  customer_name text,
  customer_contact text,
  created_at timestamptz not null default now(),
  check (ends_at > starts_at)
);
create index on appointments (agent_id, starts_at);

-- No double-booking per agent calendar. A per-agent advisory lock serialises concurrent bookings; the error code is
-- exclusion_violation (23P01), the same one an EXCLUDE constraint raises (that needs btree_gist, not available everywhere).
create or replace function appointments_no_overlap() returns trigger language plpgsql as $$
begin
  if new.status = 'booked' then
    perform pg_advisory_xact_lock(hashtext(new.agent_id::text));
    if exists (select 1 from appointments a where a.agent_id = new.agent_id and a.status = 'booked' and a.id <> new.id
               and tstzrange(a.starts_at, a.ends_at) && tstzrange(new.starts_at, new.ends_at)) then
      raise exception 'slot already booked' using errcode = '23P01';
    end if;
  end if;
  return new;
end $$;
create trigger appointments_no_overlap before insert or update on appointments
  for each row execute function appointments_no_overlap();

create table catalog_items (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  name text not null,
  description text not null default '',
  price numeric(14, 2),
  attributes jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table knowledge_sources (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  type text not null check (type in ('file', 'url', 'faq')),
  title text not null,
  uri text,
  raw_text text,
  status text not null default 'queued',
  error text,
  chunk_count integer not null default 0,
  created_at timestamptz not null default now()
);

create table knowledge_chunks (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  source_id uuid not null references knowledge_sources(id) on delete cascade,
  idx integer not null,
  content text not null,
  page integer,
  embedding vector(384),
  tsv tsvector generated always as (to_tsvector('english', content)) stored
);
create index on knowledge_chunks using hnsw (embedding vector_cosine_ops);
create index on knowledge_chunks using gin (tsv);
create index on knowledge_chunks (agent_id);

create table workflows (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  trigger jsonb not null,
  steps jsonb not null,
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table workflow_runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  workflow_id uuid not null references workflows(id) on delete cascade,
  event jsonb not null,
  status text not null default 'running' check (status in ('running', 'succeeded', 'failed', 'stopped')),
  outputs jsonb not null default '{}',
  error text,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);

create table workflow_step_runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  run_id uuid not null references workflow_runs(id) on delete cascade,
  step_id text not null,
  action text not null,
  status text not null,
  attempts integer not null default 1,
  output jsonb,
  error text,
  created_at timestamptz not null default now(),
  unique (run_id, step_id)
);

create table jobs (                          -- platform queue: no RLS, only claimed in system context
  id bigserial primary key,
  tenant_id uuid,
  kind text not null,
  payload jsonb not null default '{}',
  status text not null default 'queued' check (status in ('queued', 'running', 'done', 'dead')),
  run_at timestamptz not null default now(),
  attempts integer not null default 0,
  max_attempts integer not null default 3,
  last_error text,
  locked_at timestamptz,
  created_at timestamptz not null default now()
);
create index on jobs (status, run_at);

create table analytics_events (
  id bigserial primary key,
  tenant_id uuid not null references tenants(id) on delete cascade,
  type text not null,
  agent_id uuid,
  conversation_id uuid,
  channel text,
  props jsonb not null default '{}',
  ts timestamptz not null default now()
);
create index on analytics_events (tenant_id, ts);

create table usage_daily (
  tenant_id uuid not null references tenants(id) on delete cascade,
  day date not null,
  model text not null default '',
  messages integer not null default 0,
  tokens_in bigint not null default 0,
  tokens_out bigint not null default 0,
  cost_usd numeric(12, 6) not null default 0,
  primary key (tenant_id, day, model)
);

create table outbox_emails (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  to_addr text not null,
  subject text not null,
  body text not null,
  ics text,
  status text not null default 'stored',
  error text,
  created_at timestamptz not null default now()
);

create table audit_logs (
  id bigserial primary key,
  tenant_id uuid references tenants(id) on delete cascade,
  user_id uuid,
  action text not null,
  target text,
  meta jsonb not null default '{}',
  ip text,
  ts timestamptz not null default now()
);

do $$
declare t text;
begin
  foreach t in array array['api_keys', 'llm_providers', 'agents', 'channel_connections', 'contacts', 'conversations',
    'messages', 'pii_tokens', 'leads', 'appointments', 'catalog_items', 'knowledge_sources', 'knowledge_chunks',
    'workflows', 'workflow_runs', 'workflow_step_runs', 'analytics_events', 'usage_daily', 'outbox_emails']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy tenant_isolation on %I using (app_tenant_ok(tenant_id)) with check (app_tenant_ok(tenant_id))', t);
  end loop;
  -- audit rows without a tenant (platform actions) are visible only in system context
  alter table audit_logs enable row level security;
  alter table audit_logs force row level security;
  create policy tenant_isolation on audit_logs using (
    coalesce(current_setting('app.system', true), '') = 'on' or (tenant_id is not null and app_tenant_ok(tenant_id))
  ) with check (true);
end $$;
