import { KeyRound, RefreshCw, Trash2, UserPlus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { API_URL, api } from "../api";
import { useSession, type Brand } from "../session";
import { Badge, Button, Card, CardHead, Code, CopyButton, Empty, ErrorNote, Field, Input, Loading, Logo, Select, Tabs, Textarea, fmt, useLoad, useToast, PageHeader } from "../ui";

export default function SettingsPage() {
  const { can, tenant } = useSession();
  const [params, setParams] = useSearchParams();
  const tabs = [
    { id: "workspace", label: "Workspace" },
    ...(tenant?.kind === "client" ? [{ id: "integrations", label: "Integrations" }] : []),
    ...(can("branding") && tenant?.kind !== "client" ? [{ id: "branding", label: "White-label branding" }] : []),
    { id: "team", label: "Team" },
    ...(tenant?.kind === "client" ? [{ id: "keys", label: "API keys" }, { id: "jobs", label: "Failed jobs" }] : []),
    { id: "audit", label: "Audit log" },
  ];
  const tab = params.get("tab") && tabs.some((t) => t.id === params.get("tab")) ? params.get("tab")! : "workspace";
  return (
    <div className="rise">
      <PageHeader title="Settings" sub={tenant?.name} />
      <Tabs tabs={tabs} value={tab} onChange={(t) => setParams({ tab: t })} />
      {tab === "workspace" && <Workspace />}
      {tab === "integrations" && <Integrations />}
      {tab === "branding" && <Branding />}
      {tab === "team" && <Team />}
      {tab === "keys" && <Keys />}
      {tab === "jobs" && <Jobs />}
      {tab === "audit" && <Audit />}
    </div>
  );
}

function Workspace() {
  const { tenant } = useSession();
  const toast = useToast();
  const t = useLoad(() => api(`/tenants/${tenant!.id}`), [tenant?.id]);
  const [s, setS] = useState<any>(null);
  if (t.loading && !t.data) return <Loading />;
  if (t.error) return <ErrorNote error={t.error} />;
  const settings = s ?? t.data.settings;
  const set = (k: string, v: any) => setS({ ...settings, [k]: v });
  return (
    <Card className="max-w-2xl">
      <CardHead title="Workspace" sub="Used by agents, workflows and data retention" />
      <div className="space-y-4 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Timezone"><Select value={settings.timezone || "Asia/Kolkata"} onChange={(e) => set("timezone", e.target.value)}>{["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York", "UTC"].map((z) => <option key={z}>{z}</option>)}</Select></Field>
          <Field label="Data retention (days)" hint="Masked personal data is purged after this"><Input type="number" min={7} max={3650} value={settings.retention_days ?? 90} onChange={(e) => set("retention_days", Number(e.target.value))} /></Field>
        </div>
        <Field label="Notification email" hint="Workflows send lead alerts here"><Input type="email" value={settings.sales_email || ""} onChange={(e) => set("sales_email", e.target.value)} /></Field>
        <Field label="Chat consent notice" hint="Shown in the widget before the first message"><Textarea rows={2} value={settings.consent_text || ""} onChange={(e) => set("consent_text", e.target.value)} placeholder="Chats are handled by an AI assistant and may be reviewed by our staff." /></Field>
        <Field label="Blocked words" hint="Comma separated. Masked in AI replies."><Input value={(settings.blocked_terms || []).join(", ")} onChange={(e) => set("blocked_terms", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></Field>
        <Button onClick={async () => { try { await api(`/tenants/${tenant!.id}`, { method: "PATCH", body: { settings } }); toast("Saved"); } catch (e: any) { toast(e.message, "bad"); } }}>Save</Button>
      </div>
    </Card>
  );
}

function Integrations() {
  const { tenant } = useSession();
  const toast = useToast();
  const t = useLoad(() => api(`/tenants/${tenant!.id}`), [tenant?.id]);
  const [form, setForm] = useState({ hubspot_token: "", slack_webhook_url: "", webhook_secret: "" });
  if (t.loading && !t.data) return <Loading />;
  const on = t.data?.integrations || {};
  const rows: [keyof typeof form, string, string, string][] = [
    ["hubspot_token", "HubSpot", "Private app token (crm.objects.contacts.write). Qualified leads are created as contacts.", "pat-na1-…"],
    ["slack_webhook_url", "Slack", "Incoming webhook URL. Workflows post lead alerts to the channel.", "https://hooks.slack.com/services/…"],
    ["webhook_secret", "Outbound webhooks", "Secret used to sign webhook.post calls (X-AgentGrid-Signature, HMAC-SHA256).", "any long random string"],
  ];
  return (
    <div className="grid max-w-4xl gap-4">
      {rows.map(([k, name, help, ph]) => (
        <Card key={k}>
          <div className="flex flex-wrap items-end gap-3 p-5">
            <div className="min-w-[220px] flex-1">
              <div className="flex items-center gap-2 font-semibold">{name} <Badge tone={on[k] ? "ok" : "neutral"}>{on[k] ? "Connected" : "Optional"}</Badge></div>
              <p className="mt-1 text-[13px] text-muted">{help}</p>
            </div>
            <Input className="max-w-sm" type="password" placeholder={on[k] ? "•••••••• (saved)" : ph} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} autoComplete="off" />
            <Button variant="secondary" disabled={!form[k]} onClick={async () => { try { await api(`/tenants/${tenant!.id}/integrations`, { method: "PUT", body: { [k]: form[k] } }); toast(`${name} saved`); setForm({ ...form, [k]: "" }); t.reload(); } catch (e: any) { toast(e.message, "bad"); } }}>Save</Button>
          </div>
        </Card>
      ))}
      <p className="text-[13px] text-muted">Every integration is optional. Without HubSpot, leads still sync to the built-in CRM; without Slack, alerts are skipped and logged; emails always land in the Workflows → Email outbox.</p>
    </div>
  );
}

function Branding() {
  const { tenant, me, reload } = useSession();
  const toast = useToast();
  const [b, setB] = useState<Brand>({ ...tenant!.branding });
  const slug = me?.tenants.find((t) => t.id === tenant!.id)?.slug;
  const preview: Brand = { product_name: b.product_name || "AgentGrid", primary_color: b.primary_color || "#172554", accent_color: b.accent_color || "#C19A5B", logo_url: b.logo_url };
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_420px]">
      <Card>
        <CardHead title="White-label" sub="Your clients see your brand in the console and in every chat widget. Client workspaces can override widget colours." />
        <div className="space-y-4 p-5">
          <Field label="Product name"><Input value={b.product_name || ""} onChange={(e) => setB({ ...b, product_name: e.target.value })} placeholder="e.g. GrowthPilot AI" /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Primary colour"><div className="flex gap-2"><input type="color" value={preview.primary_color} onChange={(e) => setB({ ...b, primary_color: e.target.value })} className="h-10 w-12 rounded-[10px] border border-line" aria-label="Primary colour" /><Input value={b.primary_color || ""} onChange={(e) => setB({ ...b, primary_color: e.target.value })} /></div></Field>
            <Field label="Accent colour"><div className="flex gap-2"><input type="color" value={preview.accent_color} onChange={(e) => setB({ ...b, accent_color: e.target.value })} className="h-10 w-12 rounded-[10px] border border-line" aria-label="Accent colour" /><Input value={b.accent_color || ""} onChange={(e) => setB({ ...b, accent_color: e.target.value })} /></div></Field>
          </div>
          <Field label="Logo URL" hint="Optional. PNG or SVG, about 32 px tall."><Input value={b.logo_url || ""} onChange={(e) => setB({ ...b, logo_url: e.target.value })} placeholder="https://…" /></Field>
          <Field label="Support email"><Input value={b.support_email || ""} onChange={(e) => setB({ ...b, support_email: e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!b.hide_powered_by} onChange={(e) => setB({ ...b, hide_powered_by: e.target.checked })} /> Hide "Powered by AgentGrid"</label>
          <Button onClick={async () => {
            try {
              await api(`/tenants/${tenant!.id}/branding`, { method: "PATCH", body: Object.fromEntries(Object.entries(b).filter(([, v]) => v !== "" && v !== undefined)) });
              toast("Branding saved");
              await reload();
            } catch (e: any) {
              toast(e.message, "bad");
            }
          }}>Save branding</Button>
          {slug && <p className="text-[13px] text-muted">Branded sign-in page for your clients: <a className="underline" href={`/?brand=${slug}`}>{window.location.origin}/?brand={slug}</a></p>}
        </div>
      </Card>
      <Card>
        <CardHead title="Preview" />
        <div className="space-y-4 p-5">
          <div className="rounded-[14px] p-4" style={{ background: preview.primary_color }}>
            <span style={{ ["--primary" as any]: preview.primary_color, ["--accent" as any]: preview.accent_color }}><Logo brand={preview} light /></span>
          </div>
          <div className="rounded-[14px] border border-line bg-paper p-4">
            <div className="mb-3 rounded-[12px] px-3 py-2 text-sm text-white" style={{ background: preview.primary_color }}>Chat header · {preview.product_name}</div>
            <div className="w-fit rounded-[12px] border border-line bg-white px-3 py-2 text-sm">Hi! How can I help?</div>
            <div className="ml-auto mt-2 w-fit rounded-[12px] px-3 py-2 text-sm text-white" style={{ background: preview.primary_color }}>Show me 3BHK options</div>
            <div className="mt-3 h-1.5 w-1/2 rounded-full" style={{ background: preview.accent_color }} />
          </div>
        </div>
      </Card>
    </div>
  );
}

function Team() {
  const toast = useToast();
  const { can, tenant } = useSession();
  const users = useLoad(() => api("/users"), []);
  const [form, setForm] = useState({ email: "", name: "", role: "human_agent" });
  const [temp, setTemp] = useState<string | null>(null);
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
      <Card>
        <CardHead title="Members" sub="Role-based access. Data is isolated per workspace in the database." />
        {users.loading && !users.data ? <Loading /> : !users.data?.length ? <Empty title="No members" /> : (
          <ul>
            {users.data.map((u: any) => (
              <li key={u.id} className="flex items-center gap-3 border-b border-line/60 px-5 py-3 text-sm last:border-0">
                <div className="flex size-8 items-center justify-center rounded-full bg-sunk font-semibold text-accent-ink">{u.name.charAt(0)}</div>
                <div className="min-w-0 flex-1"><div className="font-medium">{u.name}</div><div className="text-xs text-muted">{u.email}</div></div>
                <Badge>{fmt.title(u.role)}</Badge>
                <button className="rounded-lg p-1.5 text-muted hover:bg-sunk" aria-label="Remove" onClick={async () => { if (confirm(`Remove ${u.name}?`)) { try { await api(`/users/${u.id}`, { method: "DELETE" }); users.reload(); } catch (e: any) { toast(e.message, "bad"); } } }}><Trash2 className="size-4" /></button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <CardHead title="Invite someone" />
        <div className="space-y-3 p-5">
          <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Email"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Role">
            <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {tenant?.kind === "agency" && can("clients") && <option value="agency_admin">Agency admin</option>}
              <option value="client_admin">Workspace admin</option>
              <option value="human_agent">Team member (inbox)</option>
              <option value="viewer">Viewer (dashboards only)</option>
            </Select>
          </Field>
          <Button disabled={!form.email || !form.name} onClick={async () => {
            try {
              const r = await api("/users", { body: form });
              setTemp(r.temporary_password);
              toast("Member added");
              setForm({ email: "", name: "", role: "human_agent" });
              users.reload();
            } catch (e: any) {
              toast(e.message, "bad");
            }
          }}><UserPlus className="size-4" /> Add member</Button>
          {temp && <div className="rounded-[10px] bg-warn-bg p-3 text-[13px] text-warn">Temporary password (shown once): <code className="font-semibold">{temp}</code></div>}
        </div>
      </Card>
    </div>
  );
}

function Keys() {
  const toast = useToast();
  const keys = useLoad(() => api("/api-keys"), []);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_420px]">
      <Card>
        <CardHead title="API keys" sub="For the REST channel (/v1/messages). Stored hashed; scoped to this workspace." />
        {!keys.data?.length ? <Empty title="No keys yet" icon={<KeyRound className="size-7" />} /> : (
          <ul>
            {keys.data.map((k: any) => (
              <li key={k.id} className="flex items-center gap-3 border-b border-line/60 px-5 py-3 text-sm last:border-0">
                <span className="font-mono">{k.prefix}…</span>
                <span className="flex-1">{k.name}</span>
                <span className="text-xs text-muted">{k.last_used_at ? `used ${fmt.ago(k.last_used_at)}` : "never used"}</span>
                {k.revoked_at ? <Badge tone="bad">revoked</Badge> : <Button size="sm" variant="ghost" onClick={async () => { await api(`/api-keys/${k.id}`, { method: "DELETE" }); keys.reload(); }}>Revoke</Button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <CardHead title="Create a key" />
        <div className="space-y-3 p-5">
          <Input placeholder="e.g. CRM integration" value={name} onChange={(e) => setName(e.target.value)} />
          <Button disabled={!name} onClick={async () => { try { const r = await api("/api-keys", { body: { name } }); setCreated(r.key); setName(""); keys.reload(); } catch (e: any) { toast(e.message, "bad"); } }}>Create key</Button>
          {created && (
            <div className="space-y-2">
              <div className="rounded-[10px] bg-warn-bg p-3 text-[13px] text-warn">Copy it now. It won't be shown again.</div>
              <div className="flex gap-2"><Input readOnly value={created} /><CopyButton text={created} /></div>
              <Code>{`curl -X POST ${API_URL}/v1/messages \\
  -H "X-API-Key: ${created}" \\
  -H "Content-Type: application/json" \\
  -d '{"agent_id": "<agent id>", "user_id": "u1", "text": "Hi"}'`}</Code>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function Jobs() {
  const toast = useToast();
  const jobs = useLoad(() => api("/jobs?status=dead"), []);
  if (jobs.loading && !jobs.data) return <Loading />;
  return (
    <Card>
      <CardHead title="Failed background jobs" sub="Jobs that failed after all retries (e.g. a channel was down). Retry once the cause is fixed." right={<Button size="sm" variant="secondary" onClick={jobs.reload}><RefreshCw className="size-3.5" /></Button>} />
      {!jobs.data?.length ? <Empty title="Nothing failed">All background work completed.</Empty> : (
        <ul>
          {jobs.data.map((j: any) => (
            <li key={j.id} className="border-b border-line/60 px-5 py-3 text-sm last:border-0">
              <div className="flex items-center gap-3"><span className="font-mono font-medium">{j.kind}</span><span className="text-xs text-muted">{j.attempts} attempts · {fmt.dt(j.created_at)}</span>
                <Button size="sm" variant="secondary" className="ml-auto" onClick={async () => { await api(`/jobs/${j.id}/retry`, { method: "POST" }); toast("Queued again"); jobs.reload(); }}>Retry</Button></div>
              <div className="mt-1 line-clamp-2 font-mono text-xs text-bad">{(j.last_error || "").trim().split("\n").pop()}</div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Audit() {
  const logs = useLoad(() => api("/audit-logs"), []);
  if (logs.loading && !logs.data) return <Loading />;
  if (logs.error) return <ErrorNote error={logs.error} />;
  return (
    <Card>
      <CardHead title="Audit log" sub="Who changed what, and when" />
      {!logs.data?.length ? <Empty title="No activity yet" /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr className="border-b border-line">{["When", "Who", "Action", "Target"].map((h) => <th key={h} className="px-5 py-2.5 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {logs.data.map((l: any, i: number) => (
                <tr key={i} className="border-b border-line/60 last:border-0">
                  <td className="whitespace-nowrap px-5 py-2.5 text-muted">{fmt.dt(l.ts)}</td>
                  <td className="px-5 py-2.5">{l.user_name || "System"}</td>
                  <td className="px-5 py-2.5"><Badge>{l.action}</Badge></td>
                  <td className="max-w-[320px] truncate px-5 py-2.5 text-muted">{l.target}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
