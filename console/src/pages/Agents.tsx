import { Bot, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useSession } from "../session";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, fmt, useLoad, useToast } from "../ui";
import { ChannelIcon } from "./Inbox";

export default function Agents() {
  const { can } = useSession();
  const agents = useLoad(() => api("/agents"), []);
  const [open, setOpen] = useState(false);
  return (
    <div className="rise">
      <PageHeader
        title="Agents"
        sub="Each agent runs a LangGraph flow: deterministic guardrails around an LLM that uses your knowledge, catalog and calendar."
        actions={can("agents") && <Button onClick={() => setOpen(true)}><Plus className="size-4" /> New agent</Button>}
      />
      {agents.error && <ErrorNote error={agents.error} onRetry={agents.reload} />}
      {agents.loading && !agents.data ? <Loading /> : agents.data?.length === 0 ? (
        <Card><Empty title="No agents yet" icon={<Bot className="size-7" />}>Create one from an industry template to get started.</Empty></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {agents.data?.map((a: any) => (
            <Link key={a.id} to={`/agents/${a.id}`} className="group rounded-[16px] border border-line bg-surface p-5 shadow-soft transition hover:-translate-y-0.5 hover:border-primary/30">
              <div className="flex items-start gap-3">
                <div className="flex size-11 items-center justify-center rounded-full bg-primary font-serif text-lg font-semibold text-primary-ink">{a.name.charAt(0)}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><h2 className="truncate font-semibold">{a.name}</h2><Badge tone={a.status === "active" ? "ok" : "neutral"}>{a.status}</Badge></div>
                  <div className="text-[13px] text-muted">{fmt.title(a.template_key)}</div>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-[10px] bg-sunk/70 py-2"><div className="font-serif text-lg font-semibold">{fmt.num(a.conversations)}</div><div className="text-[11px] text-muted">Conversations</div></div>
                <div className="rounded-[10px] bg-sunk/70 py-2"><div className="font-serif text-lg font-semibold">{a.sources}</div><div className="text-[11px] text-muted">Documents</div></div>
                <div className="rounded-[10px] bg-sunk/70 py-2"><div className="font-serif text-lg font-semibold">{1 + a.channels.length + 1}</div><div className="text-[11px] text-muted">Channels</div></div>
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5 text-muted">
                {["web", "api", ...a.channels].map((c: string) => <Badge key={c}><ChannelIcon channel={c} className="size-3" /> {fmt.title(c)}</Badge>)}
                <span className="ml-auto text-xs">{a.model || "Platform default model"}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
      <NewAgent open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function NewAgent({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const nav = useNavigate();
  const templates = useLoad(() => api("/templates"), []);
  const [name, setName] = useState("");
  const [tpl, setTpl] = useState("real_estate");
  const [busy, setBusy] = useState(false);
  const chosen = templates.data?.find((t: any) => t.key === tpl);
  return (
    <Modal open={open} onClose={onClose} title="New agent from a template">
      <div className="space-y-4">
        <Field label="Agent name" hint="Customers see this name in the chat.">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Aria" />
        </Field>
        <Field label="Industry template">
          <Select value={tpl} onChange={(e) => setTpl(e.target.value)}>
            {templates.data?.map((t: any) => <option key={t.key} value={t.key}>{t.name}</option>)}
          </Select>
        </Field>
        {chosen && (
          <div className="rounded-[12px] bg-sunk/60 p-4 text-[13px]">
            <p>{chosen.description}</p>
            <p className="mt-2 text-muted">Qualifies: {chosen.fields.map(fmt.title).join(", ")}</p>
            {chosen.workflows.length > 0 && <p className="mt-1 text-muted">Includes workflows: {chosen.workflows.join("; ")}</p>}
          </div>
        )}
        <Button busy={busy} disabled={!name.trim()} onClick={async () => {
          setBusy(true);
          try {
            const a = await api("/agents", { body: { name, template_key: tpl } });
            toast(`${a.name} is ready. Add knowledge next.`);
            nav(`/agents/${a.id}?tab=knowledge`);
          } catch (e: any) {
            toast(e.message, "bad");
          } finally {
            setBusy(false);
          }
        }}>Create agent</Button>
      </div>
    </Modal>
  );
}
