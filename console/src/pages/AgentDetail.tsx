import { ArrowLeft, ExternalLink, FileUp, Link2, RefreshCw, RotateCcw, Search, Send, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { API_URL, api } from "../api";
import { useSession } from "../session";
import { Badge, Button, Card, CardHead, Code, CopyButton, Empty, ErrorNote, Field, Input, Loading, PageHeader, Select, Tabs, Textarea, cx, fmt, useLoad, useToast } from "../ui";
import { Trace } from "./Inbox";

const TABS = [
  { id: "playground", label: "Playground" },
  { id: "settings", label: "Settings" },
  { id: "knowledge", label: "Knowledge" },
  { id: "catalog", label: "Catalog" },
  { id: "channels", label: "Channels" },
  { id: "flow", label: "How it works" },
];
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export default function AgentDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "playground";
  const agent = useLoad(() => api(`/agents/${id}`), [id]);
  if (agent.loading && !agent.data) return <Loading />;
  if (agent.error) return <ErrorNote error={agent.error} onRetry={agent.reload} />;
  const a = agent.data;
  return (
    <div className="rise">
      <Link to="/agents" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" /> Agents</Link>
      <PageHeader
        title={a.name}
        sub={<>{fmt.title(a.template_key)} · {a.model ? `Model ${a.model}` : "Platform default model"} · <Badge tone={a.status === "active" ? "ok" : "neutral"}>{a.status}</Badge></>}
      />
      <Tabs tabs={TABS} value={tab} onChange={(t) => setParams({ tab: t })} />
      {tab === "playground" && <Playground agent={a} />}
      {tab === "settings" && <SettingsTab agent={a} onSaved={agent.reload} />}
      {tab === "knowledge" && <Knowledge agent={a} />}
      {tab === "catalog" && <Catalog agent={a} />}
      {tab === "channels" && <Channels agent={a} onChange={agent.reload} />}
      {tab === "flow" && <Flow />}
    </div>
  );
}

// ---------------------------------------------------------------- playground

function Playground({ agent }: { agent: any }) {
  const toast = useToast();
  const { tenant } = useSession();
  const [session, setSession] = useState(() => `s${Date.now().toString(36)}`);
  const [msgs, setMsgs] = useState<{ role: string; text: string; citations?: any[] }[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<any>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  async function send(t = text) {
    if (!t.trim() || busy) return;
    setMsgs((m) => [...m, { role: "user", text: t }]);
    setText("");
    setBusy(true);
    try {
      const r = await api(`/agents/${agent.id}/playground`, { body: { text: t, session } });
      setLast(r);
      setMsgs((m) => [...m, { role: "assistant", text: r.reply || r.note || "(no reply)", citations: r.citations }]);
    } catch (e: any) {
      toast(e.message, "bad");
    } finally {
      setBusy(false);
    }
  }

  const quick = agent.config.quick_replies || [];
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
      <Card className="flex h-[620px] flex-col">
        <CardHead
          title="Talk to your agent"
          sub="Same pipeline as real channels: guardrails, tools, knowledge, workflows. Conversations here are marked simulated."
          right={<Button size="sm" variant="ghost" onClick={async () => { await api(`/agents/${agent.id}/playground/reset`, { body: { text: "x", session } }); setSession(`s${Date.now().toString(36)}`); setMsgs([]); setLast(null); }}><RotateCcw className="size-3.5" /> Reset</Button>}
        />
        <div className="scroll-thin flex-1 space-y-3 overflow-y-auto bg-paper/60 px-5 py-4">
          <Bubble role="assistant" text={(agent.config.greeting || "Hi!").replace("{agent}", agent.name).replace("{company}", tenant?.name || "us")} />
          {msgs.map((m, i) => <Bubble key={i} {...m} />)}
          {busy && <div className="text-[13px] text-muted">{agent.name} is thinking…</div>}
          <div ref={end} />
        </div>
        {msgs.length === 0 && (
          <div className="flex flex-wrap gap-1.5 px-5 pb-2">
            {quick.map((q: string) => <button key={q} onClick={() => send(q)} className="rounded-full border border-primary/40 bg-white px-3 py-1 text-[12.5px] text-primary hover:bg-primary hover:text-primary-ink">{q}</button>)}
          </div>
        )}
        <form className="flex gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about prices, share your budget, book a visit, or ask for a person…" aria-label="Message" />
          <Button type="submit" busy={busy}><Send className="size-4" /></Button>
        </form>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHead title="Last turn" sub="What the agent did and why" />
          <div className="p-4">
            {last?.trace ? (
              <>
                <Trace t={last.trace} />
                <div className="mt-3 grid grid-cols-2 gap-2 text-[12.5px]">
                  <div className="rounded-[10px] bg-sunk/60 px-3 py-2"><div className="text-muted">Latency</div><div className="font-semibold">{fmt.ms(last.usage?.latency_ms)}</div></div>
                  <div className="rounded-[10px] bg-sunk/60 px-3 py-2"><div className="text-muted">Cost</div><div className="font-semibold">{fmt.usd(last.usage?.cost_usd)}</div></div>
                  <div className="rounded-[10px] bg-sunk/60 px-3 py-2"><div className="text-muted">Tokens in / out</div><div className="font-semibold">{fmt.num(last.usage?.tokens_in)} / {fmt.num(last.usage?.tokens_out)}</div></div>
                  <div className="rounded-[10px] bg-sunk/60 px-3 py-2"><div className="text-muted">Model</div><div className="truncate font-semibold">{last.trace.model}</div></div>
                </div>
                {last.state === "PENDING_HUMAN" && <div className="mt-3 rounded-[10px] bg-warn-bg px-3 py-2 text-[13px] text-warn">Handed over to a person. See it in the <Link className="underline" to={`/inbox/${last.conversation_id}`}>inbox</Link>.</div>}
              </>
            ) : <p className="text-[13px] text-muted">Send a message to see the graph path, tool calls, retrieved sources, lead score and cost.</p>}
          </div>
        </Card>
        {last?.trace?.retrieved && Object.keys(last.trace.retrieved).length > 0 && (
          <Card>
            <CardHead title="Retrieved knowledge" />
            <div className="space-y-2 p-4">
              {Object.entries(last.trace.retrieved).map(([label, r]: any) => (
                <div key={label} className="rounded-[10px] bg-sunk/60 px-3 py-2 text-[12.5px]">
                  <div className="font-semibold">[{label}] {r.title}{r.page ? ` p.${r.page}` : ""}</div>
                  <div className="mt-0.5 line-clamp-3 text-muted">{r.snippet}</div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function Bubble({ role, text, citations }: { role: string; text: string; citations?: any[] }) {
  return (
    <div className={cx("flex", role === "user" ? "justify-end" : "justify-start")}>
      <div className={cx("max-w-[82%] whitespace-pre-wrap rounded-[14px] px-3.5 py-2.5 text-sm leading-relaxed", role === "user" ? "rounded-br-[4px] bg-primary text-primary-ink" : "rounded-bl-[4px] border border-line bg-white")}>
        {text.replace(/\s*\[S\d+\]/g, "")}
        {citations && citations.length > 0 && <div className="mt-2 border-t border-dashed border-line pt-1.5 text-[11.5px] text-muted">Sources: {[...new Set(citations.map((c) => `${c.title}${c.page ? ` p.${c.page}` : ""}`))].join(" · ")}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- settings

function list(s: string) {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

function SettingsTab({ agent, onSaved }: { agent: any; onSaved: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const providers = useLoad(() => (can("models") ? api("/llm-providers") : Promise.resolve({ providers: [] })), []);
  const [a, setA] = useState(() => structuredClone(agent));
  const [busy, setBusy] = useState(false);
  const cfg = a.config;
  const set = (path: (string | number)[], v: any) =>
    setA((prev: any) => {
      const next = structuredClone(prev);
      let o = next;
      for (const k of path.slice(0, -1)) o = o[k];
      o[path[path.length - 1]] = v;
      return next;
    });

  async function save() {
    setBusy(true);
    try {
      await api(`/agents/${agent.id}`, {
        method: "PATCH",
        body: {
          name: a.name, persona: a.persona, status: a.status, config: a.config,
          ...(a.provider_id ? { provider_id: a.provider_id, model: a.model || null, cheap_model: a.cheap_model || null } : { clear_provider: true }),
          fallback_provider_id: a.fallback_provider_id || null, fallback_model: a.fallback_model || null,
        },
      });
      toast("Agent saved");
      onSaved();
    } catch (e: any) {
      toast(e.message, "bad");
    } finally {
      setBusy(false);
    }
  }
  const editable = can("agents");
  const plat = providers.data?.platform_default;
  return (
    <fieldset disabled={!editable} className="grid gap-5 xl:grid-cols-2">
      <Card>
        <CardHead title="Identity" sub="Who the agent is and how it greets people" />
        <div className="space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name"><Input value={a.name} onChange={(e) => set(["name"], e.target.value)} /></Field>
            <Field label="Status"><Select value={a.status} onChange={(e) => set(["status"], e.target.value)}><option value="active">Active</option><option value="paused">Paused</option></Select></Field>
          </div>
          <Field label="Persona and tone"><Textarea rows={3} value={a.persona} onChange={(e) => set(["persona"], e.target.value)} /></Field>
          <Field label="Greeting" hint="{agent} and {company} are filled in automatically."><Textarea rows={2} value={cfg.greeting || ""} onChange={(e) => set(["config", "greeting"], e.target.value)} /></Field>
          <Field label="Quick replies" hint="Comma separated"><Input value={(cfg.quick_replies || []).join(", ")} onChange={(e) => set(["config", "quick_replies"], list(e.target.value))} /></Field>
          <Field label="Business profile" hint="Short facts the agent always knows (address, hours, offerings). Details belong in Knowledge."><Textarea rows={4} value={cfg.business_profile || ""} onChange={(e) => set(["config", "business_profile"], e.target.value)} /></Field>
        </div>
      </Card>
      <Card>
        <CardHead title="AI model" sub="Bring your own model per agent, with an automatic fallback" />
        <div className="space-y-4 p-5">
          <Field label="Provider" hint={plat ? `Platform default: ${plat.offline ? "offline demo model (no key set)" : `${plat.kind} · ${plat.model}`}` : undefined}>
            <Select value={a.provider_id || ""} onChange={(e) => set(["provider_id"], e.target.value || null)}>
              <option value="">Platform default</option>
              {providers.data?.providers.map((p: any) => <option key={p.id} value={p.id}>{p.name} ({p.kind})</option>)}
            </Select>
          </Field>
          {a.provider_id && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Main model" hint="Blank = provider default"><Input value={a.model || ""} onChange={(e) => set(["model"], e.target.value)} /></Field>
              <Field label="Cheap model" hint="Summaries, suggestions"><Input value={a.cheap_model || ""} onChange={(e) => set(["cheap_model"], e.target.value)} /></Field>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Fallback provider">
              <Select value={a.fallback_provider_id || ""} onChange={(e) => set(["fallback_provider_id"], e.target.value || null)}>
                <option value="">None</option>
                {providers.data?.providers.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </Field>
            <Field label="Fallback model"><Input value={a.fallback_model || ""} onChange={(e) => set(["fallback_model"], e.target.value)} /></Field>
          </div>
          {!can("models") ? null : <Link to="/models" className="text-sm underline">Add or test model providers</Link>}
        </div>
      </Card>
      <Card>
        <CardHead title="Lead qualification" sub="What the agent collects and how each answer is scored (deterministic)" />
        <div className="p-5">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="pb-2 font-medium">Field</th><th className="pb-2 font-medium">What it means</th><th className="pb-2 text-right font-medium">Points</th></tr></thead>
            <tbody>
              {Object.entries(cfg.qualification.fields).map(([k, f]: any) => (
                <tr key={k} className="border-t border-line/60">
                  <td className="py-2 pr-3 font-medium">{fmt.title(k)}</td>
                  <td className="py-2 pr-3 text-muted">{f.label}</td>
                  <td className="w-20 py-2"><Input type="number" min={0} max={50} value={f.weight} onChange={(e) => set(["config", "qualification", "fields", k, "weight"], Number(e.target.value))} className="h-8 text-right" /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 grid grid-cols-3 gap-3">
            {["engaged", "qualified", "hot"].map((s) => (
              <Field key={s} label={`${fmt.title(s)} at`}><Input type="number" value={cfg.qualification.stages[s]} onChange={(e) => set(["config", "qualification", "stages", s], Number(e.target.value))} /></Field>
            ))}
          </div>
        </div>
      </Card>
      <Card>
        <CardHead title="Booking and handover" />
        <div className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {DAYS.map((d) => (
              <Field key={d} label={fmt.title(d)}><Input placeholder="closed" value={cfg.booking.hours[d] || ""} onChange={(e) => set(["config", "booking", "hours", d], e.target.value)} className="h-9 text-[13px]" /></Field>
            ))}
          </div>
          <p className="text-xs text-muted">Services: {cfg.booking.services.map((s: any) => `${s.name} (${s.minutes} min)`).join(", ")} · Timezone {cfg.booking.timezone}</p>
          <Field label="Hand over when the customer says" hint="Comma separated"><Input value={cfg.handover.keywords.join(", ")} onChange={(e) => set(["config", "handover", "keywords"], list(e.target.value))} /></Field>
          <Field label="Always hand over on these topics"><Input value={cfg.handover.sensitive_topics.join(", ")} onChange={(e) => set(["config", "handover", "sensitive_topics"], list(e.target.value))} /></Field>
          <Field label="Hand over after this many unsure answers in a row"><Input type="number" min={1} max={5} value={cfg.handover.low_confidence_turns} onChange={(e) => set(["config", "handover", "low_confidence_turns"], Number(e.target.value))} className="w-24" /></Field>
        </div>
      </Card>
      {editable && <div className="xl:col-span-2"><Button onClick={save} busy={busy}>Save changes</Button></div>}
    </fieldset>
  );
}

// ---------------------------------------------------------------- knowledge

function Knowledge({ agent }: { agent: any }) {
  const { can } = useSession();
  const toast = useToast();
  const sources = useLoad(() => api(`/agents/${agent.id}/knowledge`), [agent.id]);
  const [faq, setFaq] = useState({ title: "", text: "" });
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!sources.data?.some((s: any) => s.status === "queued")) return;
    const t = setTimeout(sources.reload, 2000);
    return () => clearTimeout(t);
  }, [sources.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(kind: string, fn: () => Promise<any>, ok: string) {
    setBusy(kind);
    try {
      await fn();
      toast(ok);
      sources.reload();
    } catch (e: any) {
      toast(e.message, "bad");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_400px]">
      <div className="space-y-5">
        <Card>
          <CardHead title="Documents" sub="Split, embedded locally and searched with hybrid (vector + keyword) retrieval. Answers cite these sources." />
          {sources.loading && !sources.data ? <Loading /> : sources.data?.length === 0 ? <Empty title="No knowledge yet">Upload a brochure, price list or FAQ.</Empty> : (
            <ul>
              {sources.data?.map((s: any) => (
                <li key={s.id} className="flex flex-wrap items-center gap-3 border-b border-line/60 px-5 py-3 text-sm last:border-0">
                  <span className="min-w-0 flex-1"><span className="font-medium">{s.title}</span><span className="text-muted"> · {s.type}{s.chunk_count ? ` · ${s.chunk_count} chunks` : ""}</span>{s.error && <span className="block text-xs text-bad">{s.error}</span>}</span>
                  <Badge tone={s.status === "ready" ? "ok" : s.status === "error" ? "bad" : "info"}>{s.status}</Badge>
                  {can("agents") && <>
                    <button className="rounded-lg p-1.5 text-muted hover:bg-sunk" title="Re-index" aria-label="Re-index" onClick={() => run("re", () => api(`/knowledge/${s.id}/reindex`, { method: "POST" }), "Re-indexing")}><RefreshCw className="size-4" /></button>
                    <button className="rounded-lg p-1.5 text-muted hover:bg-sunk" title="Delete" aria-label="Delete" onClick={() => confirm(`Delete ${s.title}?`) && run("del", () => api(`/knowledge/${s.id}`, { method: "DELETE" }), "Deleted")}><Trash2 className="size-4" /></button>
                  </>}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <CardHead title="Test retrieval" sub="See exactly what the agent would read for a question" />
          <div className="p-5">
            <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (q.trim()) setResults(await api(`/agents/${agent.id}/knowledge/search`, { body: { query: q } })); }}>
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. what are the payment plans?" />
              <Button type="submit"><Search className="size-4" /></Button>
            </form>
            {results && (
              <div className="mt-4 space-y-2">
                <Badge tone={results.confident ? "ok" : "warn"}>{results.confident ? "Confident: the agent will answer" : "Not confident: the agent will say it's unsure"}</Badge>
                {results.results.map((r: any, i: number) => (
                  <div key={i} className="rounded-[10px] bg-sunk/60 p-3 text-[13px]">
                    <div className="flex justify-between font-medium"><span>{r.title}{r.page ? ` p.${r.page}` : ""}</span><span className="text-xs text-muted">similarity {r.similarity?.toFixed(2) ?? "–"}</span></div>
                    <p className="mt-1 line-clamp-3 text-muted">{r.content}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>
      {can("agents") && (
        <div className="space-y-5">
          <Card>
            <CardHead title="Upload a file" sub="PDF, DOCX, TXT, MD, CSV or HTML, up to 15 MB" />
            <div className="p-5">
              <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md,.csv,.html,.htm" className="block w-full text-sm file:mr-3 file:rounded-[10px] file:border-0 file:bg-sunk file:px-3 file:py-2 file:text-sm file:font-medium" />
              <Button className="mt-3" busy={busy === "file"} onClick={() => {
                const f = fileRef.current?.files?.[0];
                if (!f) return toast("Choose a file first", "bad");
                const form = new FormData();
                form.append("file", f);
                run("file", () => api(`/agents/${agent.id}/knowledge/file`, { form }), "Uploaded. Indexing now.").then(() => { if (fileRef.current) fileRef.current.value = ""; });
              }}><FileUp className="size-4" /> Upload</Button>
            </div>
          </Card>
          <Card>
            <CardHead title="Add an FAQ or note" />
            <div className="space-y-3 p-5">
              <Input placeholder="Title" value={faq.title} onChange={(e) => setFaq({ ...faq, title: e.target.value })} />
              <Textarea rows={4} placeholder="Q: Do you allow pets?&#10;A: Yes, all communities are pet friendly." value={faq.text} onChange={(e) => setFaq({ ...faq, text: e.target.value })} />
              <Button busy={busy === "faq"} disabled={!faq.title || faq.text.length < 10} onClick={() => run("faq", () => api(`/agents/${agent.id}/knowledge/text`, { body: faq }), "Added").then(() => setFaq({ title: "", text: "" }))}>Add</Button>
            </div>
          </Card>
          <Card>
            <CardHead title="Import a web page" />
            <div className="flex gap-2 p-5">
              <Input placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
              <Button busy={busy === "url"} disabled={!url.startsWith("http")} onClick={() => run("url", () => api(`/agents/${agent.id}/knowledge/url`, { body: { url } }), "Fetching page").then(() => setUrl(""))}><Link2 className="size-4" /></Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- catalog

function Catalog({ agent }: { agent: any }) {
  const { can } = useSession();
  const toast = useToast();
  const items = useLoad(() => api(`/agents/${agent.id}/catalog`), [agent.id]);
  const [form, setForm] = useState({ name: "", price: "", description: "", attributes: '{"location": "", "type": "", "tags": []}' });
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
      <Card>
        <CardHead title="Catalog" sub="The agent's recommend_items tool ranks these by fit to what the customer asked for" />
        {items.loading && !items.data ? <Loading /> : items.data?.length === 0 ? <Empty title="Catalog is empty" /> : (
          <ul>
            {items.data?.map((it: any) => (
              <li key={it.id} className="flex items-start gap-3 border-b border-line/60 px-5 py-3 text-sm last:border-0">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{it.name} <span className="font-normal text-accent-ink">{fmt.inr(it.price)}</span></div>
                  <div className="text-[13px] text-muted">{it.description}</div>
                  <div className="mt-1 flex flex-wrap gap-1">{Object.entries(it.attributes).map(([k, v]) => <Badge key={k}>{k}: {Array.isArray(v) ? v.join(", ") : String(v)}</Badge>)}</div>
                </div>
                {can("agents") && <button className="rounded-lg p-1.5 text-muted hover:bg-sunk" aria-label="Delete item" onClick={async () => { await api(`/catalog/${it.id}`, { method: "DELETE" }); items.reload(); }}><Trash2 className="size-4" /></button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {can("agents") && (
        <Card>
          <CardHead title="Add an item" />
          <div className="space-y-3 p-5">
            <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Price (INR)"><Input type="number" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></Field>
            <Field label="Description"><Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
            <Field label="Attributes (JSON)" hint="Matched against what the customer says: location, type, bedrooms, tags"><Textarea rows={3} className="font-mono text-xs" value={form.attributes} onChange={(e) => setForm({ ...form, attributes: e.target.value })} /></Field>
            <Button disabled={!form.name} onClick={async () => {
              try {
                await api(`/agents/${agent.id}/catalog`, { body: { name: form.name, description: form.description, price: form.price ? Number(form.price) : null, attributes: JSON.parse(form.attributes || "{}") } });
                toast("Item added");
                setForm({ ...form, name: "", price: "", description: "" });
                items.reload();
              } catch (e: any) {
                toast(e instanceof SyntaxError ? "Attributes must be valid JSON" : e.message, "bad");
              }
            }}>Add item</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- channels

function demoPath(key: string) {
  return key === "pk_skyline_aria" ? "/demo/skyline" : key === "pk_brightsmile_mia" ? "/demo/brightsmile" : `/demo/preview?key=${key}`;
}

function Channels({ agent, onChange }: { agent: any; onChange: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const [tg, setTg] = useState("");
  const [wa, setWa] = useState({ phone_number_id: "", access_token: "", app_secret: "" });
  const [waResult, setWaResult] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const tgConn = agent.channels.find((c: any) => c.type === "telegram");
  const waConn = agent.channels.find((c: any) => c.type === "whatsapp");
  const edit = can("agents");

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card>
        <CardHead title="Website chat widget" sub="Paste before </body> on any website" right={<Badge tone="ok">Live</Badge>} />
        <div className="space-y-3 p-5">
          <Code>{agent.widget_script}</Code>
          <div className="flex flex-wrap gap-2">
            <CopyButton text={agent.widget_script} label="Copy snippet" />
            <a href={demoPath(agent.public_key)} target="_blank" rel="noreferrer"><Button size="sm" variant="secondary"><ExternalLink className="size-3.5" /> Open demo website</Button></a>
          </div>
        </div>
      </Card>

      <Card>
        <CardHead title="Telegram" sub="Instant: no review or verification" right={tgConn ? <Badge tone="ok">Connected</Badge> : <Badge>Not connected</Badge>} />
        <div className="space-y-3 p-5 text-sm">
          {tgConn ? (
            <>
              <p>Bot <a className="font-medium underline" href={`https://t.me/${tgConn.config.username}`} target="_blank" rel="noreferrer">@{tgConn.config.username}</a> is answering as {agent.name}.</p>
              {edit && <Button size="sm" variant="danger" onClick={async () => { await api(`/channels/${tgConn.id}`, { method: "DELETE" }); onChange(); }}>Disconnect</Button>}
            </>
          ) : edit ? (
            <>
              <ol className="list-decimal space-y-1 pl-5 text-muted">
                <li>In Telegram, open <a className="underline" href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a> and send <code>/newbot</code>.</li>
                <li>Pick a name and username, then copy the token it gives you.</li>
                <li>Paste it here. We register the webhook for you.</li>
              </ol>
              <div className="flex gap-2">
                <Input placeholder="123456:ABC-DEF…" value={tg} onChange={(e) => setTg(e.target.value)} />
                <Button busy={busy === "tg"} disabled={tg.length < 20} onClick={async () => {
                  setBusy("tg");
                  try {
                    const r = await api(`/agents/${agent.id}/channels/telegram`, { body: { bot_token: tg } });
                    toast(`Connected @${r.config.username} (${r.mode})`);
                    setTg("");
                    onChange();
                  } catch (e: any) {
                    toast(e.message, "bad");
                  } finally {
                    setBusy("");
                  }
                }}>Connect</Button>
              </div>
            </>
          ) : <p className="text-muted">Not connected.</p>}
        </div>
      </Card>

      <Card>
        <CardHead title="WhatsApp (Cloud API test number)" sub="Free Meta test number, no business verification needed" right={waConn ? <Badge tone="ok">Connected</Badge> : <Badge>Not connected</Badge>} />
        <div className="space-y-3 p-5 text-sm">
          {waConn && (
            <div className="space-y-2">
              <p>Phone number ID <span className="font-mono">{waConn.external_id}</span></p>
              <Field label="Callback URL (paste in Meta → WhatsApp → Configuration)"><div className="flex gap-2"><Input readOnly value={waConn.webhook_url} /><CopyButton text={waConn.webhook_url} /></div></Field>
              {(waResult?.verify_token || waConn.verify_token) && <Field label="Verify token"><div className="flex gap-2"><Input readOnly value={waResult?.verify_token || waConn.verify_token} /><CopyButton text={waResult?.verify_token || waConn.verify_token} /></div></Field>}
              {edit && <Button size="sm" variant="danger" onClick={async () => { await api(`/channels/${waConn.id}`, { method: "DELETE" }); setWaResult(null); onChange(); }}>Disconnect</Button>}
            </div>
          )}
          {!waConn && edit && (
            <>
              <ol className="list-decimal space-y-1 pl-5 text-muted">
                <li>At developers.facebook.com create an app (type Business) and add the WhatsApp product.</li>
                <li>In WhatsApp → API Setup, add your phone as a recipient and copy the <b>Phone number ID</b> and <b>temporary access token</b>.</li>
                <li>In App settings → Basic, copy the <b>App secret</b>. Paste all three here.</li>
                <li>Copy the Callback URL and Verify token we show into WhatsApp → Configuration and subscribe to <b>messages</b>.</li>
              </ol>
              <div className="grid gap-2">
                <Input placeholder="Phone number ID" value={wa.phone_number_id} onChange={(e) => setWa({ ...wa, phone_number_id: e.target.value })} />
                <Input placeholder="Access token" value={wa.access_token} onChange={(e) => setWa({ ...wa, access_token: e.target.value })} />
                <Input placeholder="App secret" value={wa.app_secret} onChange={(e) => setWa({ ...wa, app_secret: e.target.value })} />
              </div>
              <Button busy={busy === "wa"} disabled={!wa.phone_number_id || !wa.access_token || !wa.app_secret} onClick={async () => {
                setBusy("wa");
                try {
                  setWaResult(await api(`/agents/${agent.id}/channels/whatsapp`, { body: wa }));
                  toast("Saved. Finish the webhook step in Meta.");
                  onChange();
                } catch (e: any) {
                  toast(e.message, "bad");
                } finally {
                  setBusy("");
                }
              }}>Save</Button>
            </>
          )}
          <p className="text-xs text-muted">No Meta account? Use the <Link className="underline" to="/simulator">channel simulator</Link>: it runs the same WhatsApp and Telegram pipeline.</p>
        </div>
      </Card>

      <Card>
        <CardHead title="REST API" sub="Connect any system: CRM, app, IVR" right={<Badge tone="ok">Live</Badge>} />
        <div className="space-y-3 p-5 text-sm">
          <Code>{`curl -X POST ${API_URL}/v1/messages \\
  -H "X-API-Key: ag_…" -H "Content-Type: application/json" \\
  -d '{"agent_id": "${agent.id}", "user_id": "crm-42", "text": "What are the payment plans?"}'`}</Code>
          <p className="text-muted">Create keys in <Link className="underline" to="/settings?tab=keys">Settings → API keys</Link>. Full reference at <a className="underline" href={`${API_URL}/docs`} target="_blank" rel="noreferrer">/docs</a>.</p>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- flow

const NODES = [
  { id: "guard_in", title: "Input guard", body: "Mask personal data. Handover keywords and sensitive topics route straight to a person." },
  { id: "agent", title: "LLM agent", body: "Any provider via LangChain. Decides which tools to call; answers only from tool results." },
  { id: "tools", title: "Tools", body: "search_knowledge · update_lead · recommend_items · check_availability · book_appointment · handover_to_human" },
  { id: "guard_out", title: "Output guard", body: "Drop citations that weren't retrieved, filter blocked terms, count unsure answers." },
  { id: "handover", title: "Handover", body: "Pause the AI, write a summary for the team, notify by workflow." },
];

function Flow() {
  const graph = useLoad(() => api("/agents/graph"), []);
  return (
    <div className="space-y-5">
      <Card>
        <CardHead title="The agent graph (LangGraph)" sub="Deterministic code decides state, scores and bookings; the LLM handles language and tool choice." />
        <div className="grid gap-3 p-5 md:grid-cols-5">
          {NODES.map((n, i) => (
            <div key={n.id} className={cx("relative rounded-[14px] border p-4", n.id === "agent" ? "border-primary bg-primary text-primary-ink" : n.id === "handover" ? "border-warn/30 bg-warn-bg" : "border-line bg-white")}>
              <div className="text-[11px] font-semibold uppercase tracking-[0.08em] opacity-70">Step {i + 1}</div>
              <div className="mt-1 font-semibold">{n.title}</div>
              <p className={cx("mt-1.5 text-[12.5px] leading-relaxed", n.id === "agent" ? "text-primary-ink/80" : "text-muted")}>{n.body}</p>
              <code className="mt-2 block text-[11px] opacity-60">{n.id}</code>
            </div>
          ))}
        </div>
        <p className="px-5 pb-5 text-[13px] text-muted">Agent ⇄ tools loops until the model answers (max ~6 tool rounds). Two unsure answers in a row, a sensitive topic, or a request for a person all end in handover.</p>
      </Card>
      <Card>
        <CardHead title="Generated from code" sub="graph.get_graph().draw_mermaid()" right={graph.data && <CopyButton text={graph.data.mermaid} />} />
        <div className="p-5">{graph.data ? <Code>{graph.data.mermaid}</Code> : <Loading />}</div>
      </Card>
    </div>
  );
}
