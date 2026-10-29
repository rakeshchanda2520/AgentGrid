import { CheckCircle2, Cpu, Plus, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, CardHead, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, useLoad, useToast } from "../ui";

const PRESETS: Record<string, { label: string; base: string; model: string; cheap: string; keyHint: string }> = {
  openrouter: { label: "OpenRouter (hundreds of models)", base: "https://openrouter.ai/api/v1", model: "anthropic/claude-sonnet-4.5", cheap: "openai/gpt-4o-mini", keyHint: "sk-or-…" },
  openai: { label: "OpenAI", base: "", model: "gpt-4.1-mini", cheap: "gpt-4.1-nano", keyHint: "sk-…" },
  anthropic: { label: "Anthropic", base: "", model: "claude-sonnet-5-5", cheap: "claude-haiku-5-5", keyHint: "sk-ant-…" },
  qwen: { label: "Qwen (Alibaba Cloud DashScope)", base: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", model: "qwen-plus", cheap: "qwen-turbo", keyHint: "sk-…" },
  ollama: { label: "Ollama (self-hosted, private)", base: "http://localhost:11434/v1", model: "qwen3:8b", cheap: "qwen3:4b", keyHint: "not needed" },
  openai_compat: { label: "Any OpenAI-compatible endpoint (vLLM, Groq, Together…)", base: "https://", model: "", cheap: "", keyHint: "" },
};

export default function Models() {
  const toast = useToast();
  const data = useLoad(() => api("/llm-providers"), []);
  const [open, setOpen] = useState(false);
  const [tests, setTests] = useState<Record<string, any>>({});
  const [testing, setTesting] = useState("");

  async function test(id: string) {
    setTesting(id);
    try {
      const r = await api(id === "platform" ? "/llm-providers/test-platform" : `/llm-providers/${id}/test`, { method: "POST" });
      setTests((t) => ({ ...t, [id]: r }));
    } finally {
      setTesting("");
    }
  }

  if (data.loading && !data.data) return <Loading />;
  if (data.error) return <ErrorNote error={data.error} onRetry={data.reload} />;
  const plat = data.data.platform_default;
  return (
    <div className="rise">
      <PageHeader title="AI models" sub="Bring your own model. Any agent can use a different provider, with its own key, and fall back to another if it fails." actions={<Button onClick={() => setOpen(true)}><Plus className="size-4" /> Add provider</Button>} />
      <Card className="mb-5">
        <CardHead title="Platform default" sub="Used by agents that don't pick a provider" right={plat.offline ? <Badge tone="warn">Offline demo model</Badge> : <Badge tone="ok">Connected</Badge>} />
        <div className="flex flex-wrap items-center gap-4 p-5 text-sm">
          <div className="min-w-0 flex-1">
            {plat.offline ? (
              <p className="text-muted">No platform API key is set, so agents run on the built-in offline model. It uses the real tools, knowledge and workflows, but replies are rule-based. Add a provider here (or set <code>LLM_API_KEY</code> on the server) for real AI replies.</p>
            ) : (
              <p><span className="font-medium">{plat.kind}</span> · main <span className="font-mono">{plat.model}</span> · cheap <span className="font-mono">{plat.cheap_model}</span></p>
            )}
          </div>
          {!plat.offline && <TestResult r={tests.platform} />}
          {!plat.offline && <Button size="sm" variant="secondary" busy={testing === "platform"} onClick={() => test("platform")}>Test</Button>}
        </div>
      </Card>
      <Card>
        <CardHead title="Your providers" sub="Keys are encrypted with a per-workspace key and never shown again" />
        {data.data.providers.length === 0 ? <Empty title="No providers yet" icon={<Cpu className="size-7" />}>Add OpenAI, Anthropic, Qwen, OpenRouter or a private Ollama server.</Empty> : (
          <ul>
            {data.data.providers.map((p: any) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 border-b border-line/60 px-5 py-3.5 text-sm last:border-0">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{p.name} <Badge>{p.kind}</Badge> {!p.has_key && p.kind !== "ollama" && <Badge tone="warn">no key</Badge>}</div>
                  <div className="mt-0.5 text-[13px] text-muted">main <span className="font-mono">{p.default_model}</span>{p.cheap_model && <> · cheap <span className="font-mono">{p.cheap_model}</span></>}</div>
                </div>
                <TestResult r={tests[p.id]} />
                <Button size="sm" variant="secondary" busy={testing === p.id} onClick={() => test(p.id)}>Test</Button>
                <Button size="sm" variant="ghost" aria-label="Delete provider" onClick={async () => { if (confirm(`Delete ${p.name}? Agents using it fall back to the platform default.`)) { await api(`/llm-providers/${p.id}`, { method: "DELETE" }); toast("Provider deleted"); data.reload(); } }}><Trash2 className="size-3.5" /></Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <p className="mt-4 text-[13px] text-muted">Pick a provider per agent in Agents → Settings → AI model. The test call checks the key and that the model supports tool calling, which agents need.</p>
      <AddProvider open={open} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); data.reload(); }} />
    </div>
  );
}

function TestResult({ r }: { r?: any }) {
  if (!r) return null;
  return r.ok ? (
    <span className="inline-flex items-center gap-1 text-[13px] text-ok"><CheckCircle2 className="size-4" /> Works{r.tool_calling ? ", tool calling OK" : ", but no tool call"}</span>
  ) : (
    <span className="inline-flex max-w-xs items-center gap-1 truncate text-[13px] text-bad" title={r.error}><XCircle className="size-4 shrink-0" /> {r.error}</span>
  );
}

function AddProvider({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [kind, setKind] = useState("openrouter");
  const p = PRESETS[kind];
  const [form, setForm] = useState({ name: "", base_url: p.base, api_key: "", default_model: p.model, cheap_model: p.cheap });
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={open} onClose={onClose} title="Add a model provider">
      <div className="space-y-4">
        <Field label="Provider">
          <Select value={kind} onChange={(e) => { const k = e.target.value; setKind(k); setForm({ ...form, base_url: PRESETS[k].base, default_model: PRESETS[k].model, cheap_model: PRESETS[k].cheap }); }}>
            {Object.entries(PRESETS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </Field>
        <Field label="Display name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={p.label.split(" (")[0]} /></Field>
        {kind !== "anthropic" && kind !== "openai" && <Field label="Base URL"><Input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></Field>}
        <Field label="API key" hint="Stored encrypted. Never sent back to the browser."><Input type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder={p.keyHint} autoComplete="off" /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Main model" hint="Customer conversations (needs tool calling)"><Input value={form.default_model} onChange={(e) => setForm({ ...form, default_model: e.target.value })} /></Field>
          <Field label="Cheap model" hint="Summaries and suggestions"><Input value={form.cheap_model} onChange={(e) => setForm({ ...form, cheap_model: e.target.value })} /></Field>
        </div>
        <Button busy={busy} disabled={!form.default_model} onClick={async () => {
          setBusy(true);
          try {
            await api("/llm-providers", { body: { ...form, name: form.name || p.label.split(" (")[0], kind, base_url: form.base_url || null, cheap_model: form.cheap_model || null } });
            toast("Provider added. Use Test to check it.");
            onSaved();
          } catch (e: any) {
            toast(e.message, "bad");
          } finally {
            setBusy(false);
          }
        }}>Save provider</Button>
      </div>
    </Modal>
  );
}
