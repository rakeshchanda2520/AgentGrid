import { ArrowRight, CheckCircle2, Clock3, Mail, Pencil, Plus, RefreshCw, Trash2, XCircle, Zap } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, CardHead, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Tabs, Textarea, fmt, useLoad, useToast } from "../ui";

const ACTION_LABEL: Record<string, string> = {
  "crm.upsert_contact": "Sync to CRM",
  "hubspot.upsert": "Push to HubSpot",
  "notify.email": "Send email",
  "notify.slack": "Post to Slack",
  "webhook.post": "Call webhook",
  "channel.send_message": "Message the customer",
  "conversation.tag": "Tag conversation",
  delay: "Wait",
  condition: "Only if",
};

export default function Workflows() {
  const [tab, setTab] = useState("flows");
  return (
    <div className="rise">
      <PageHeader title="Workflows" sub="Business automation triggered by what happens in conversations. Each step runs as a durable background job with retries." />
      <Tabs tabs={[{ id: "flows", label: "Workflows" }, { id: "runs", label: "Run history" }, { id: "outbox", label: "Email outbox" }]} value={tab} onChange={setTab} />
      {tab === "flows" && <Flows />}
      {tab === "runs" && <Runs />}
      {tab === "outbox" && <Outbox />}
    </div>
  );
}

function Flows() {
  const toast = useToast();
  const flows = useLoad(() => api("/workflows"), []);
  const [edit, setEdit] = useState<any>(null);
  if (flows.loading && !flows.data) return <Loading />;
  if (flows.error) return <ErrorNote error={flows.error} onRetry={flows.reload} />;
  return (
    <>
      <div className="mb-4 flex justify-end">
        <Button onClick={() => setEdit({ name: "", trigger: { event: "lead.qualified", filter: [] }, steps: [{ id: "step1", action: "notify.email", params: { to: "{{ tenant.sales_email }}", subject: "New lead", body: "Lead {{ lead.fields.name }} scored {{ lead.score }}" } }], enabled: true })}>
          <Plus className="size-4" /> New workflow
        </Button>
      </div>
      {flows.data.length === 0 && <Card><Empty title="No workflows">Create one, or add an agent from a template: templates include ready-made workflows.</Empty></Card>}
      <div className="space-y-4">
        {flows.data.map((w: any) => (
          <Card key={w.id}>
            <div className="flex flex-wrap items-start gap-4 p-5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-semibold">{w.name}</h2>
                  <Badge tone={w.enabled ? "ok" : "neutral"}>{w.enabled ? "On" : "Off"}</Badge>
                  <span className="text-xs text-muted">{fmt.num(w.runs)} runs{w.failed ? ` · ${w.failed} failed` : ""}</span>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12.5px]">
                  <span className="inline-flex items-center gap-1 rounded-full bg-primary px-2.5 py-1 font-medium text-primary-ink"><Zap className="size-3" /> When {w.trigger.event}</span>
                  {(w.trigger.filter || []).map((f: any, i: number) => <Badge key={i} tone="gold">{f.field} {f.op} {String(f.value)}</Badge>)}
                  {w.steps.map((s: any) => (
                    <span key={s.id} className="inline-flex items-center gap-1.5">
                      <ArrowRight className="size-3.5 text-muted" />
                      <span className="rounded-full border border-line bg-white px-2.5 py-1">
                        {ACTION_LABEL[s.action] || s.action}
                        {s.action === "delay" && s.params?.minutes ? ` ${s.params.minutes} min` : ""}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex gap-1.5">
                <Button size="sm" variant="secondary" onClick={async () => { await api(`/workflows/${w.id}`, { method: "PATCH", body: { ...w, enabled: !w.enabled } }); flows.reload(); }}>{w.enabled ? "Turn off" : "Turn on"}</Button>
                <Button size="sm" variant="secondary" onClick={() => setEdit(w)}><Pencil className="size-3.5" /></Button>
                <Button size="sm" variant="ghost" aria-label="Delete" onClick={async () => { if (confirm(`Delete ${w.name}?`)) { await api(`/workflows/${w.id}`, { method: "DELETE" }); toast("Deleted"); flows.reload(); } }}><Trash2 className="size-3.5" /></Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
      {edit && <Editor wf={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); flows.reload(); }} />}
    </>
  );
}

function Editor({ wf, onClose, onSaved }: { wf: any; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const meta = useLoad(() => api("/workflows/meta"), []);
  const [name, setName] = useState(wf.name);
  const [event, setEvent] = useState(wf.trigger.event);
  const [filter, setFilter] = useState(JSON.stringify(wf.trigger.filter || [], null, 2));
  const [steps, setSteps] = useState<any[]>(wf.steps.map((s: any) => ({ ...s, paramsText: JSON.stringify(s.params || {}, null, 2) })));
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      const body = {
        name, enabled: wf.enabled ?? true,
        trigger: { event, filter: JSON.parse(filter || "[]") },
        steps: steps.map(({ paramsText, ...s }) => ({ ...s, params: JSON.parse(paramsText || "{}") })),
      };
      await api(wf.id ? `/workflows/${wf.id}` : "/workflows", { method: wf.id ? "PATCH" : "POST", body });
      toast("Workflow saved");
      onSaved();
    } catch (e: any) {
      toast(e instanceof SyntaxError ? "Filter and step parameters must be valid JSON" : e.message, "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title={wf.id ? "Edit workflow" : "New workflow"} wide>
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="When this happens"><Select value={event} onChange={(e) => setEvent(e.target.value)}>{meta.data?.events.map((ev: string) => <option key={ev}>{ev}</option>)}</Select></Field>
        </div>
        <Field label="Only if (JSON filters)" hint='e.g. [{"field": "lead.score", "op": ">=", "value": 60}]. Operators: == != > >= < <= in contains exists'>
          <Textarea rows={3} className="font-mono text-xs" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </Field>
        <div>
          <div className="mb-2 text-[13px] font-medium">Steps <span className="font-normal text-muted">· parameters accept {"{{ lead.fields.name }}"}, {"{{ contact.email }}"}, {"{{ appointment.when }}"}, {"{{ tenant.sales_email }}"}</span></div>
          <div className="space-y-3">
            {steps.map((s, i) => (
              <div key={i} className="rounded-[12px] border border-line bg-white p-3">
                <div className="grid gap-2 sm:grid-cols-[140px_1fr_auto]">
                  <Input value={s.id} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)))} aria-label="Step id" />
                  <Select value={s.action} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, action: e.target.value } : x)))}>
                    {meta.data?.actions.map((a: string) => <option key={a} value={a}>{ACTION_LABEL[a] || a} ({a})</option>)}
                  </Select>
                  <Button variant="ghost" size="sm" onClick={() => setSteps(steps.filter((_, j) => j !== i))} aria-label="Remove step"><Trash2 className="size-3.5" /></Button>
                </div>
                <Textarea rows={3} className="mt-2 font-mono text-xs" value={s.paramsText} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, paramsText: e.target.value } : x)))} aria-label="Parameters" />
              </div>
            ))}
          </div>
          <Button className="mt-3" size="sm" variant="secondary" onClick={() => setSteps([...steps, { id: `step${steps.length + 1}`, action: "delay", paramsText: '{"minutes": 30}' }])}><Plus className="size-3.5" /> Add step</Button>
        </div>
        <Button onClick={save} busy={busy}>Save workflow</Button>
      </div>
    </Modal>
  );
}

function Runs() {
  const toast = useToast();
  const runs = useLoad(() => api("/workflow-runs"), []);
  if (runs.loading && !runs.data) return <Loading />;
  if (runs.error) return <ErrorNote error={runs.error} onRetry={runs.reload} />;
  if (!runs.data.length) return <Card><Empty title="No runs yet">Runs appear when a trigger fires, for example a lead becomes qualified.</Empty></Card>;
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button size="sm" variant="secondary" onClick={runs.reload}><RefreshCw className="size-3.5" /> Refresh</Button></div>
      {runs.data.map((r: any) => (
        <Card key={r.id}>
          <div className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{r.workflow_name}</span>
              <Badge tone={r.status === "succeeded" ? "ok" : r.status === "failed" ? "bad" : r.status === "stopped" ? "neutral" : "info"}>{r.status === "stopped" ? "stopped by condition" : r.status}</Badge>
              <span className="text-xs text-muted">{r.event.type} · {fmt.dt(r.created_at)}</span>
              {r.status === "failed" && <Button size="sm" variant="secondary" className="ml-auto" onClick={async () => { await api(`/workflow-runs/${r.id}/retry`, { method: "POST" }); toast("Retrying from the failed step"); runs.reload(); }}><RefreshCw className="size-3.5" /> Retry</Button>}
            </div>
            <ol className="mt-3 space-y-1.5">
              {r.steps.map((s: any) => (
                <li key={s.step_id} className="flex items-start gap-2 text-[13px]">
                  {s.status === "succeeded" ? <CheckCircle2 className="mt-0.5 size-4 text-ok" /> : <XCircle className="mt-0.5 size-4 text-bad" />}
                  <span className="font-medium">{ACTION_LABEL[s.action] || s.action}</span>
                  <span className="min-w-0 flex-1 truncate text-muted">{s.error || summarizeOutput(s.output)}</span>
                  {s.attempts > 1 && <Badge>{s.attempts} attempts</Badge>}
                </li>
              ))}
              {r.status === "running" && <li className="flex items-center gap-2 text-[13px] text-muted"><Clock3 className="size-4" /> Waiting for the next step…</li>}
            </ol>
          </div>
        </Card>
      ))}
    </div>
  );
}

function summarizeOutput(o: any) {
  if (!o) return "";
  if (o.resume_at) return `until ${fmt.dt(o.resume_at)}`;
  if (o.to) return `to ${o.to} (${o.status})`;
  if ("passed" in o) return o.passed ? "condition met" : "condition not met";
  return Object.entries(o).map(([k, v]) => `${k}: ${v}`).join(", ");
}

function Outbox() {
  const mails = useLoad(() => api("/outbox"), []);
  const [open, setOpen] = useState<any>(null);
  if (mails.loading && !mails.data) return <Loading />;
  return (
    <Card>
      <CardHead title="Email outbox" sub="Every email a workflow sends is kept here. With SMTP configured it is also delivered." />
      {!mails.data?.length ? <Empty title="No emails yet" icon={<Mail className="size-7" />} /> : (
        <ul>
          {mails.data.map((m: any) => (
            <li key={m.id}>
              <button onClick={() => setOpen(m)} className="flex w-full flex-wrap items-center gap-3 border-b border-line/60 px-5 py-3 text-left text-sm hover:bg-white">
                <Mail className="size-4 text-muted" />
                <span className="min-w-0 flex-1 truncate"><span className="font-medium">{m.subject}</span><span className="text-muted"> · to {m.to_addr}</span></span>
                {m.has_invite && <Badge tone="gold">Calendar invite</Badge>}
                <Badge tone={m.status === "sent" ? "ok" : m.status === "failed" ? "bad" : "neutral"}>{m.status}</Badge>
                <span className="text-xs text-muted">{fmt.ago(m.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && (
        <Modal open onClose={() => setOpen(null)} title={open.subject}>
          <p className="mb-3 text-sm text-muted">To {open.to_addr} · {fmt.dt(open.created_at)}</p>
          <pre className="whitespace-pre-wrap rounded-[12px] bg-sunk/60 p-4 font-sans text-sm">{open.body}</pre>
          {open.error && <p className="mt-3 text-sm text-bad">{open.error}</p>}
        </Modal>
      )}
    </Card>
  );
}
