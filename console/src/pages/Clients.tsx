import { ArrowRight, Building2, Plus } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { useSession } from "../session";
import { Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, fmt, useLoad, useToast } from "../ui";

export default function Clients() {
  const { switchTenant, reload } = useSession();
  const toast = useToast();
  const rollup = useLoad(() => api("/analytics/agency?days=30"), []);
  const templates = useLoad(() => api("/templates"), []);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", template_key: "real_estate", agent_name: "Assistant", sales_email: "" });
  const [busy, setBusy] = useState(false);

  return (
    <div className="rise">
      <PageHeader title="Clients" sub="Every client gets an isolated workspace: its own agents, knowledge, inbox, leads and data. Your branding applies to all of them." actions={<Button onClick={() => setOpen(true)}><Plus className="size-4" /> New client</Button>} />
      {rollup.error && <ErrorNote error={rollup.error} onRetry={rollup.reload} />}
      {rollup.loading && !rollup.data ? <Loading /> : rollup.data?.length === 0 ? <Card><Empty title="No clients yet" icon={<Building2 className="size-7" />} /></Card> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rollup.data?.map((c: any) => (
            <Card key={c.id}>
              <div className="p-5">
                <div className="flex items-center gap-3">
                  <div className="flex size-10 items-center justify-center rounded-[12px] bg-sunk font-serif text-lg font-semibold text-accent-ink">{c.name.charAt(0)}</div>
                  <div className="min-w-0 flex-1"><h2 className="truncate font-semibold">{c.name}</h2><div className="text-xs text-muted">{c.agents} agent{c.agents === 1 ? "" : "s"} · last 30 days</div></div>
                </div>
                <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-[10px] bg-sunk/60 py-2"><dd className="font-serif text-lg font-semibold">{fmt.num(c.conversations)}</dd><dt className="text-[11px] text-muted">Chats</dt></div>
                  <div className="rounded-[10px] bg-sunk/60 py-2"><dd className="font-serif text-lg font-semibold">{fmt.num(c.qualified)}</dd><dt className="text-[11px] text-muted">Qualified</dt></div>
                  <div className="rounded-[10px] bg-sunk/60 py-2"><dd className="font-serif text-lg font-semibold">{fmt.num(c.booked)}</dd><dt className="text-[11px] text-muted">Booked</dt></div>
                </dl>
                <Button className="mt-4 w-full" variant="secondary" onClick={() => switchTenant(c.id)}>Open workspace <ArrowRight className="size-4" /></Button>
              </div>
            </Card>
          ))}
        </div>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="New client workspace">
        <div className="space-y-4">
          <Field label="Business name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Coastal Homes" /></Field>
          <Field label="Start with an agent from template">
            <Select value={form.template_key} onChange={(e) => setForm({ ...form, template_key: e.target.value })}>
              <option value="">No agent yet</option>
              {templates.data?.map((t: any) => <option key={t.key} value={t.key}>{t.name}</option>)}
            </Select>
          </Field>
          {form.template_key && <Field label="Agent name"><Input value={form.agent_name} onChange={(e) => setForm({ ...form, agent_name: e.target.value })} /></Field>}
          <Field label="Sales / notification email" hint="Where workflow emails go"><Input type="email" value={form.sales_email} onChange={(e) => setForm({ ...form, sales_email: e.target.value })} /></Field>
          <Button busy={busy} disabled={form.name.trim().length < 2} onClick={async () => {
            setBusy(true);
            try {
              const t = await api("/tenants", { body: { name: form.name, template_key: form.template_key || null, agent_name: form.agent_name, sales_email: form.sales_email || null } });
              toast(`${t.name} created`);
              await reload();
              switchTenant(t.id);
            } catch (e: any) {
              toast(e.message, "bad");
            } finally {
              setBusy(false);
            }
          }}>Create workspace</Button>
        </div>
      </Modal>
    </div>
  );
}
