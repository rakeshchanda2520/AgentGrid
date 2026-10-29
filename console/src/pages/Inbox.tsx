import { ArrowLeft, Bot, CalendarCheck, ChevronDown, Globe, Hand, MessageCircle, RotateCcw, Send, Sparkles, UserRound } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useTenantEvents } from "../realtime";
import { useSession } from "../session";
import { Badge, Button, Card, Empty, ErrorNote, Loading, STAGE_TONE, STATE_LABEL, STATE_TONE, Textarea, cx, fmt, useLoad, useToast } from "../ui";

const FILTERS = [
  { id: "PENDING_HUMAN", label: "Needs a person" },
  { id: "mine", label: "Mine" },
  { id: "all", label: "All" },
  { id: "BOT_ACTIVE", label: "AI handling" },
  { id: "RESOLVED", label: "Resolved" },
];

export function ChannelIcon({ channel, className = "size-3.5" }: { channel: string; className?: string }) {
  if (channel === "web") return <Globe className={className} aria-label="Web chat" />;
  if (channel === "whatsapp") return <MessageCircle className={className} aria-label="WhatsApp" />;
  if (channel === "telegram") return <Send className={className} aria-label="Telegram" />;
  return <Bot className={className} aria-label={channel} />;
}

export default function InboxPage() {
  const { id } = useParams();
  const { tenant } = useSession();
  const [filter, setFilter] = useState("all");
  const q = filter === "all" ? "" : filter === "mine" ? "?mine=true" : `?state=${filter}`;
  const list = useLoad(() => api(`/conversations${q}`), [q]);
  const reloadTimer = useRef<number | undefined>(undefined);

  useTenantEvents(tenant?.id, () => {
    window.clearTimeout(reloadTimer.current);
    reloadTimer.current = window.setTimeout(() => list.reload(), 400);
  });

  return (
    <div className="rise -mx-4 -my-6 grid h-[calc(100vh-57px)] grid-cols-1 sm:-mx-6 lg:-mx-8 lg:-my-8 lg:h-screen md:grid-cols-[320px_1fr] xl:grid-cols-[340px_1fr_320px]">
      <aside className={cx("flex min-h-0 flex-col border-r border-line bg-surface", id && "hidden md:flex")}>
        <div className="px-4 pb-3 pt-5">
          <h1 className="font-serif text-2xl font-semibold">Inbox</h1>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={cx("rounded-full px-3 py-1 text-[12.5px] font-medium", filter === f.id ? "bg-primary text-primary-ink" : "bg-sunk text-muted hover:text-ink")}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto border-t border-line">
          {list.loading && !list.data && <Loading />}
          {list.error && <div className="p-4"><ErrorNote error={list.error} onRetry={list.reload} /></div>}
          {list.data?.length === 0 && <Empty title="All clear">No conversations in this view.</Empty>}
          {list.data?.map((c: any) => (
            <Link
              key={c.id}
              to={`/inbox/${c.id}`}
              className={cx("block border-b border-line/70 px-4 py-3 transition hover:bg-white", c.id === id && "bg-white shadow-[inset_3px_0_0_var(--primary)]")}
            >
              <div className="flex items-center gap-2">
                <span className="text-muted"><ChannelIcon channel={c.channel} /></span>
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">{c.contact_name || "Visitor"}</span>
                <span className="text-[11px] text-muted">{fmt.ago(c.last_message_at)}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-[13px] text-muted">{(c.preview || "").replace(/\s*\[S\d+\]/g, "")}</p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <Badge tone={STATE_TONE[c.state]}>{STATE_LABEL[c.state]}</Badge>
                {c.lead_stage && c.lead_stage !== "new" && <Badge tone={STAGE_TONE[c.lead_stage]}>{fmt.title(c.lead_stage)} · {c.lead_score}</Badge>}
                {c.simulated && <Badge>Simulated</Badge>}
                <span className="ml-auto text-[11px] text-muted">{c.agent_name}</span>
              </div>
            </Link>
          ))}
        </div>
      </aside>
      {id ? <Thread key={id} id={id} onChange={list.reload} /> : (
        <div className="hidden items-center justify-center md:flex xl:col-span-2">
          <Empty title="Pick a conversation" icon={<MessageCircle className="size-7" />}>
            Conversations that need a person are listed first. Claim one to take over from the AI.
          </Empty>
        </div>
      )}
    </div>
  );
}

function Thread({ id, onChange }: { id: string; onChange: () => void }) {
  const { tenant, can } = useSession();
  const toast = useToast();
  const nav = useNavigate();
  const conv = useLoad(() => api(`/conversations/${id}`), [id]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const end = useRef<HTMLDivElement>(null);

  const scroll = useCallback(() => setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50), []);
  useEffect(() => {
    if (conv.data) scroll();
  }, [conv.data?.messages?.length, scroll]); // eslint-disable-line react-hooks/exhaustive-deps

  useTenantEvents(tenant?.id, (e) => {
    if (e.conversation_id !== id) return;
    if (e.type === "message") {
      conv.setData((d: any) => (d && !d.messages.some((m: any) => m.id === e.message.id) ? { ...d, messages: [...d.messages, e.message], state: e.state || d.state } : d));
    } else conv.reload();
  });

  async function act(action: string) {
    setBusy(action);
    try {
      await api(`/conversations/${id}/${action}`, { method: "POST" });
      await conv.reload();
      onChange();
      toast(action === "claim" ? "You're now handling this conversation" : action === "resolve" ? "Marked as resolved" : "Handed back to the AI agent");
    } catch (e: any) {
      toast(e.message, "bad");
    } finally {
      setBusy("");
    }
  }

  async function send() {
    if (!text.trim()) return;
    setBusy("send");
    try {
      await api(`/conversations/${id}/reply`, { body: { text } });
      setText("");
      setSuggestions([]);
      await conv.reload();
      onChange();
    } catch (e: any) {
      toast(e.message, "bad");
    } finally {
      setBusy("");
    }
  }

  async function suggest() {
    setBusy("suggest");
    try {
      setSuggestions((await api(`/conversations/${id}/suggestions`)).replies);
    } catch (e: any) {
      toast(e.message, "bad");
    } finally {
      setBusy("");
    }
  }

  if (conv.loading && !conv.data) return <div className="xl:col-span-2"><Loading /></div>;
  if (conv.error) return <div className="p-6 xl:col-span-2"><ErrorNote error={conv.error} onRetry={conv.reload} /></div>;
  const c = conv.data;

  return (
    <>
      <section className="flex min-h-0 flex-col bg-paper">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-3">
          <button onClick={() => nav("/inbox")} className="rounded-lg p-1.5 text-muted hover:bg-sunk md:hidden" aria-label="Back">
            <ArrowLeft className="size-4" />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate font-semibold">{c.contact?.name || "Visitor"}</h2>
              <Badge tone={STATE_TONE[c.state]}>{STATE_LABEL[c.state]}</Badge>
            </div>
            <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
              <ChannelIcon channel={c.channel} /> {fmt.title(c.channel)} · Agent {c.agent_name}
              {c.assigned_name && <> · Assigned to {c.assigned_name}</>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {c.state === "PENDING_HUMAN" && (
              <Button size="sm" onClick={() => act("claim")} busy={busy === "claim"}>
                <Hand className="size-3.5" /> Claim
              </Button>
            )}
            {(c.state === "PENDING_HUMAN" || c.state === "HUMAN_ACTIVE") && (
              <Button size="sm" variant="secondary" onClick={() => act("return-to-bot")} busy={busy === "return-to-bot"}>
                <RotateCcw className="size-3.5" /> Return to AI
              </Button>
            )}
            {c.state !== "RESOLVED" && (
              <Button size="sm" variant="secondary" onClick={() => act("resolve")} busy={busy === "resolve"}>
                Resolve
              </Button>
            )}
          </div>
        </header>

        <div className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-5 sm:px-6">
          {c.messages.map((m: any) => (
            <Message key={m.id} m={m} agent={c.agent_name} showTrace={can("agents")} />
          ))}
          <div ref={end} />
        </div>

        <div className="border-t border-line bg-surface px-4 py-3">
          {suggestions.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {suggestions.map((s) => (
                <button key={s} onClick={() => setText(s)} className="rounded-full border border-line bg-white px-3 py-1 text-left text-[12.5px] text-ink hover:border-primary/40">
                  {s}
                </button>
              ))}
            </div>
          )}
          {c.state === "BOT_ACTIVE" && <p className="mb-2 text-xs text-muted">The AI is handling this. Sending a message takes over the conversation.</p>}
          <div className="flex items-end gap-2">
            <Textarea
              rows={2}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder={`Reply on ${fmt.title(c.channel)}…`}
              aria-label="Reply"
              className="min-h-[44px] flex-1 resize-none"
            />
            <div className="flex flex-col gap-1.5">
              <Button size="sm" variant="secondary" onClick={suggest} busy={busy === "suggest"} title="Agent Copilot: suggest replies">
                <Sparkles className="size-3.5" /> Suggest
              </Button>
              <Button size="sm" onClick={send} busy={busy === "send"} disabled={!text.trim()}>
                <Send className="size-3.5" /> Send
              </Button>
            </div>
          </div>
        </div>
      </section>
      <ContextPanel c={c} onErased={() => nav("/inbox")} />
    </>
  );
}

function Message({ m, agent, showTrace }: { m: any; agent: string; showTrace: boolean }) {
  const [open, setOpen] = useState(false);
  const customer = m.role === "user";
  const text = (m.content || "").replace(/\s*\[S\d+\]/g, "");
  return (
    <div className={cx("flex", customer ? "justify-start" : "justify-end")}>
      <div className={cx("max-w-[78%]", !customer && "items-end text-right")}>
        <div className="mb-1 flex items-center gap-1.5 text-[11px] text-muted" style={{ justifyContent: customer ? "flex-start" : "flex-end" }}>
          {m.role === "assistant" ? <><Bot className="size-3" /> {agent} (AI)</> : m.role === "human" ? <><UserRound className="size-3" /> {m.author_name || "Team"}</> : "Customer"}
          <span>· {fmt.dt(m.created_at)}</span>
        </div>
        <div
          className={cx(
            "whitespace-pre-wrap rounded-[14px] px-3.5 py-2.5 text-left text-sm leading-relaxed",
            customer && "rounded-tl-[4px] border border-line bg-white",
            m.role === "assistant" && "rounded-tr-[4px] bg-sunk",
            m.role === "human" && "rounded-tr-[4px] bg-primary text-primary-ink",
          )}
        >
          {text}
          {m.citations?.length > 0 && (
            <div className="mt-2 border-t border-dashed border-line pt-1.5 text-[11.5px] text-muted">
              Sources: {[...new Set(m.citations.map((x: any) => `${x.title}${x.page ? ` p.${x.page}` : ""}`))].join(" · ")}
            </div>
          )}
        </div>
        {showTrace && m.trace && (
          <div className="mt-1 text-left">
            <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 text-[11px] text-muted hover:text-ink">
              <ChevronDown className={cx("size-3 transition", open && "rotate-180")} /> Why this reply · {m.trace.model} · {fmt.ms(m.latency_ms)}
              {m.cost_usd != null && Number(m.cost_usd) > 0 && <> · {fmt.usd(Number(m.cost_usd))}</>}
            </button>
            {open && <Trace t={m.trace} />}
          </div>
        )}
      </div>
    </div>
  );
}

export function Trace({ t }: { t: any }) {
  return (
    <div className="mt-1.5 space-y-2 rounded-[12px] border border-line bg-surface p-3 text-[12px]">
      <div className="flex flex-wrap items-center gap-1">
        {t.path.map((p: string, i: number) => (
          <span key={i} className="inline-flex items-center gap-1">
            <Badge tone={p === "handover" ? "warn" : p === "tools" ? "gold" : "info"}>{p}</Badge>
            {i < t.path.length - 1 && <span className="text-muted">→</span>}
          </span>
        ))}
      </div>
      {t.tool_calls?.map((tc: any, i: number) => (
        <div key={i}>
          <span className="font-mono font-semibold text-ink">{tc.name}</span>
          <span className="font-mono text-muted"> {JSON.stringify(tc.args)}</span>
          {t.tool_results?.[i] && <div className="mt-0.5 whitespace-pre-wrap text-muted">{t.tool_results[i].result.slice(0, 280)}</div>}
        </div>
      ))}
      {t.handover && <div className="text-warn">Handover: {t.handover}</div>}
      {t.lead?.score != null && <div className="text-muted">Lead score after this turn: {t.lead.score} ({t.lead.stage})</div>}
    </div>
  );
}

function ContextPanel({ c, onErased }: { c: any; onErased: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const lead = c.lead;
  const fields = Object.entries(lead?.fields || {}).filter(([, v]) => v !== null && v !== "");
  return (
    <aside className="scroll-thin hidden min-h-0 space-y-4 overflow-y-auto border-l border-line bg-surface p-4 xl:block">
      {c.summary && (
        <Card className="border-accent/40 bg-[#FBF3E4]">
          <div className="p-4">
            <div className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-accent-ink">
              <Sparkles className="size-3.5" /> Handover summary
            </div>
            <ul className="list-disc space-y-1 pl-4 text-[13px] text-ink">
              {c.summary.bullets?.map((b: string) => <li key={b}>{b}</li>)}
            </ul>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              <Badge>{c.summary.intent}</Badge>
              <Badge tone={c.summary.sentiment === "negative" ? "bad" : c.summary.sentiment === "positive" ? "ok" : "neutral"}>{c.summary.sentiment}</Badge>
            </div>
          </div>
        </Card>
      )}
      <Card>
        <div className="p-4">
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">Lead</span>
            {lead && <Badge tone={STAGE_TONE[lead.stage]}>{fmt.title(lead.stage)}</Badge>}
          </div>
          {lead ? (
            <>
              <div className="mt-3 flex items-baseline gap-2">
                <span className="font-serif text-4xl font-semibold">{lead.score}</span>
                <span className="text-sm text-muted">/ 100</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sunk">
                <div className="h-full rounded-full bg-accent" style={{ width: `${lead.score}%` }} />
              </div>
              <dl className="mt-4 space-y-2 text-[13px]">
                {fields.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3">
                    <dt className="text-muted">{fmt.title(k)}</dt>
                    <dd className="text-right font-medium">{k === "budget" ? fmt.inr(v as number) : String(v)}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            <p className="mt-2 text-[13px] text-muted">No qualification details captured yet.</p>
          )}
        </div>
      </Card>
      {c.appointments?.length > 0 && (
        <Card>
          <div className="p-4">
            <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">Appointments</div>
            {c.appointments.map((a: any) => (
              <div key={a.id} className="flex items-center gap-2 py-1 text-[13px]">
                <CalendarCheck className="size-4 text-ok" /> {a.service}, {fmt.dt(a.starts_at)} <Badge tone={a.status === "booked" ? "ok" : "neutral"}>{a.status}</Badge>
              </div>
            ))}
          </div>
        </Card>
      )}
      <Card>
        <div className="space-y-1.5 p-4 text-[13px]">
          <div className="mb-1 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">Contact</div>
          <div className="flex justify-between"><span className="text-muted">Name</span><span>{c.contact?.name || "–"}</span></div>
          <div className="flex justify-between"><span className="text-muted">Phone</span><span>{c.contact?.phone || "–"}</span></div>
          <div className="flex justify-between"><span className="text-muted">Email</span><span className="truncate pl-3">{c.contact?.email || "–"}</span></div>
          <div className="flex justify-between"><span className="text-muted">Consent</span><span>{c.contact?.consent_at ? fmt.dt(c.contact.consent_at) : "–"}</span></div>
          {can("users") && (
            <div className="flex gap-2 pt-2">
              <Button size="sm" variant="secondary" onClick={async () => {
                const data = await api(`/contacts/${c.contact.id}/export`);
                const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
                const a = document.createElement("a");
                a.href = url;
                a.download = "contact-export.json";
                a.click();
              }}>Export data</Button>
              <Button size="sm" variant="danger" onClick={async () => {
                if (!confirm("Erase this contact and all their conversations? This cannot be undone.")) return;
                await api(`/contacts/${c.contact.id}`, { method: "DELETE" });
                toast("Contact erased");
                onErased();
              }}>Erase</Button>
            </div>
          )}
        </div>
      </Card>
    </aside>
  );
}
