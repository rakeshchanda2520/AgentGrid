import { Download, MessageSquare, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../api";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, STAGE_TONE, Textarea, cx, fmt, useLoad, useToast } from "../ui";
import { ChannelIcon } from "./Inbox";

const STAGES = ["new", "engaged", "qualified", "hot", "booked", "won", "lost"];

export default function Leads() {
  const [stage, setStage] = useState("");
  const [q, setQ] = useState("");
  const [view, setView] = useState<"table" | "board">("table");
  const [open, setOpen] = useState<any>(null);
  const qs = new URLSearchParams({ ...(stage && { stage }), ...(q && { q }) }).toString();
  const leads = useLoad(() => api(`/leads${qs ? `?${qs}` : ""}`), [qs]);

  return (
    <div className="rise">
      <PageHeader
        title="Leads"
        sub="Captured and scored automatically from every conversation. Scores come from your template's weights, not the AI's opinion."
        actions={
          <>
            <div className="flex rounded-[10px] border border-line bg-surface p-0.5">
              {(["table", "board"] as const).map((v) => (
                <button key={v} onClick={() => setView(v)} className={cx("rounded-[8px] px-3 py-1.5 text-[13px] font-medium", view === v ? "bg-primary text-primary-ink" : "text-muted")}>
                  {v === "table" ? "Table" : "Pipeline"}
                </button>
              ))}
            </div>
            <Button variant="secondary" onClick={() => download("/leads/export.csv", "leads.csv")}>
              <Download className="size-4" /> Export CSV
            </Button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-3 top-3 size-4 text-muted" />
          <Input placeholder="Search name or details" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
        </div>
        <Select value={stage} onChange={(e) => setStage(e.target.value)} className="w-44" aria-label="Stage">
          <option value="">All stages</option>
          {STAGES.map((s) => <option key={s} value={s}>{fmt.title(s)}</option>)}
        </Select>
      </div>
      {leads.error && <ErrorNote error={leads.error} onRetry={leads.reload} />}
      {leads.loading && !leads.data ? <Loading /> : view === "table" ? (
        <Card>
          {leads.data?.length === 0 ? <Empty title="No leads match">Leads appear as soon as a customer shares details in any channel.</Empty> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    {["Name", "Score", "Stage", "Details", "Agent", "Channel", "Updated"].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {leads.data?.map((l: any) => (
                    <tr key={l.id} onClick={() => setOpen(l)} className="cursor-pointer border-b border-line/60 last:border-0 hover:bg-white">
                      <td className="px-4 py-3 font-medium">{l.fields.name || l.contact_name || "Unknown"}</td>
                      <td className="px-4 py-3"><ScoreBar v={l.score} /></td>
                      <td className="px-4 py-3"><Badge tone={STAGE_TONE[l.stage]}>{fmt.title(l.stage)}</Badge></td>
                      <td className="max-w-[320px] truncate px-4 py-3 text-muted">{summarize(l.fields)}</td>
                      <td className="px-4 py-3 text-muted">{l.agent_name}</td>
                      <td className="px-4 py-3 text-muted"><span className="inline-flex items-center gap-1.5"><ChannelIcon channel={l.channel || ""} /> {fmt.title(l.channel || "")}</span></td>
                      <td className="px-4 py-3 text-muted">{fmt.ago(l.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : (
        <div className="scroll-thin flex gap-3 overflow-x-auto pb-3">
          {STAGES.slice(0, 5).map((s) => {
            const items = (leads.data || []).filter((l: any) => l.stage === s);
            return (
              <div key={s} className="w-[260px] shrink-0 rounded-[14px] bg-sunk/70 p-2.5">
                <div className="mb-2 flex items-center justify-between px-1 text-[13px] font-semibold">
                  {fmt.title(s)} <span className="text-muted">{items.length}</span>
                </div>
                <div className="space-y-2">
                  {items.slice(0, 40).map((l: any) => (
                    <button key={l.id} onClick={() => setOpen(l)} className="block w-full rounded-[12px] border border-line bg-surface p-3 text-left shadow-soft hover:border-primary/30">
                      <div className="flex justify-between text-sm font-medium"><span className="truncate">{l.fields.name || l.contact_name || "Unknown"}</span><span>{l.score}</span></div>
                      <div className="mt-1 line-clamp-2 text-xs text-muted">{summarize(l.fields)}</div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
      <LeadModal lead={open} onClose={() => setOpen(null)} onSaved={leads.reload} />
    </div>
  );
}

function summarize(f: Record<string, any>) {
  return Object.entries(f)
    .filter(([k, v]) => v !== null && v !== "" && !["name", "phone", "email"].includes(k))
    .map(([k, v]) => (k === "budget" ? fmt.inr(v) : k === "timeline_months" ? `${v} mo` : String(v)))
    .join(" · ");
}

function ScoreBar({ v }: { v: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-sunk"><span className="block h-full rounded-full bg-accent" style={{ width: `${v}%` }} /></span>
      <span className="text-xs font-semibold">{v}</span>
    </span>
  );
}

function LeadModal({ lead, onClose, onSaved }: { lead: any; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [stage, setStage] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  if (!lead) return null;
  return (
    <Modal open={!!lead} onClose={onClose} title={lead.fields.name || lead.contact_name || "Lead"}>
      <div className="mb-4 flex items-center gap-3">
        <span className="font-serif text-4xl font-semibold">{lead.score}</span>
        <Badge tone={STAGE_TONE[lead.stage]}>{fmt.title(lead.stage)}</Badge>
        {lead.conversation_id && (
          <Link to={`/inbox/${lead.conversation_id}`} className="ml-auto inline-flex items-center gap-1.5 text-sm underline">
            <MessageSquare className="size-4" /> Open conversation
          </Link>
        )}
      </div>
      <dl className="mb-5 grid grid-cols-2 gap-x-4 gap-y-2 rounded-[12px] bg-sunk/60 p-4 text-sm">
        {Object.entries(lead.fields).map(([k, v]) => (
          <div key={k}><dt className="text-xs text-muted">{fmt.title(k)}</dt><dd className="font-medium">{k === "budget" ? fmt.inr(v as number) : String(v)}</dd></div>
        ))}
        {Object.keys(lead.crm_ids || {}).length > 0 && <div className="col-span-2 text-xs text-muted">CRM: {Object.keys(lead.crm_ids).join(", ")} synced</div>}
      </dl>
      <div className="space-y-4">
        <Field label="Stage">
          <Select defaultValue={lead.stage} onChange={(e) => setStage(e.target.value)}>
            {STAGES.map((s) => <option key={s} value={s}>{fmt.title(s)}</option>)}
          </Select>
        </Field>
        <Field label="Notes">
          <Textarea rows={3} defaultValue={lead.notes || ""} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <Button busy={busy} onClick={async () => {
          setBusy(true);
          try {
            await api(`/leads/${lead.id}`, { method: "PATCH", body: { stage: stage || undefined, notes: notes || undefined } });
            toast("Lead updated");
            onSaved();
            onClose();
          } catch (e: any) {
            toast(e.message, "bad");
          } finally {
            setBusy(false);
          }
        }}>Save</Button>
      </div>
    </Modal>
  );
}
