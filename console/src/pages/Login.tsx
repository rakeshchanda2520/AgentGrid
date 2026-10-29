import { ArrowRight, MessageCircle, ShieldCheck, Sparkles, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { applyBrand, DEFAULT_BRAND, useSession, type Brand } from "../session";
import { Button, ErrorNote, Field, Input, Logo } from "../ui";

const DEMO_PASSWORD = "AgentGrid#Demo2026";
const DEMO = [
  { email: "agency@growthpilot.demo", who: "Agency admin", what: "White-labeled agency managing two clients" },
  { email: "owner@skyline.demo", who: "Real-estate client admin", what: "Skyline Realty: agent Aria" },
  { email: "agent@skyline.demo", who: "Sales team member", what: "Inbox and handovers" },
  { email: "owner@brightsmile.demo", who: "Clinic admin", what: "BrightSmile Dental: agent Mia" },
  { email: "admin@agentgrid.demo", who: "Platform admin", what: "Everything" },
];

export default function Login() {
  const { login } = useSession();
  const [params] = useSearchParams();
  const [brand, setBrand] = useState<Brand>(DEFAULT_BRAND);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const slug = params.get("brand");
    const p = slug ? api<Brand>(`/public/branding?slug=${encodeURIComponent(slug)}`, { tenant: null }) : Promise.resolve(DEFAULT_BRAND);
    p.then((b) => {
      setBrand(b);
      applyBrand(b);
    }).catch(() => {});
  }, [params]);

  async function submit(e?: React.FormEvent, creds?: { email: string; password: string }) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login((creds?.email ?? email).trim(), creds?.password ?? password);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const name = brand.product_name || "AgentGrid";
  return (
    <div className="grid min-h-full lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden overflow-hidden bg-primary px-12 py-12 text-paper lg:flex lg:flex-col">
        <Logo brand={brand} light />
        <div className="my-auto max-w-lg">
          <p className="mb-4 text-xs font-semibold uppercase tracking-[0.16em] text-accent">AI customer engagement platform</p>
          <h1 className="font-serif text-[44px] font-semibold leading-[1.08] tracking-tight">
            Agents that answer, qualify and book, on every channel.
          </h1>
          <p className="mt-5 text-[15px] leading-relaxed text-paper/80">
            Web chat, WhatsApp, Telegram and API. Grounded answers from your documents, automatic lead scoring, bookings and CRM workflows, with a
            human one click away.
          </p>
          <ul className="mt-9 space-y-4 text-sm text-paper/90">
            {[
              [<MessageCircle key="a" className="size-4" />, "One agent, four channels, one inbox"],
              [<Sparkles key="b" className="size-4" />, "Bring your own model: OpenAI, Anthropic, Qwen, OpenRouter, Ollama"],
              [<Workflow key="c" className="size-4" />, "Workflows: CRM sync, emails with calendar invites, reminders"],
              [<ShieldCheck key="d" className="size-4" />, "Tenant isolation in the database, personal data masked from the AI"],
            ].map(([icon, text], i) => (
              <li key={i} className="flex items-center gap-3">
                <span className="flex size-8 items-center justify-center rounded-full bg-paper/10 text-accent">{icon}</span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <div className="text-xs text-paper/60">{name === "AgentGrid" ? "AgentGrid PoC · TTG-AI-AGENTGRID" : "Powered by AgentGrid"}</div>
        <svg className="pointer-events-none absolute -right-24 -top-24 opacity-[0.07]" width="420" height="420" viewBox="0 0 32 32" aria-hidden>
          <rect x="7" y="7" width="8" height="8" rx="2" fill="#F3EBDD" />
          <rect x="17" y="7" width="8" height="8" rx="2" fill="#F3EBDD" />
          <rect x="7" y="17" width="8" height="8" rx="2" fill="#F3EBDD" />
          <rect x="17" y="17" width="8" height="8" rx="4" fill="#F3EBDD" />
        </svg>
      </section>

      <section className="flex items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-8 lg:hidden">
            <Logo brand={brand} />
          </div>
          <h2 className="font-serif text-[28px] font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-sm text-muted">to your {name} workspace</p>
          <form onSubmit={submit} className="mt-7 space-y-4">
            <Field label="Email">
              <Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </Field>
            <Field label="Password">
              <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </Field>
            {error && <ErrorNote error={error} />}
            <Button type="submit" busy={busy} className="w-full">
              Sign in <ArrowRight className="size-4" />
            </Button>
          </form>

          <div className="mt-9">
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">Demo accounts · one click</div>
            <div className="space-y-2">
              {DEMO.map((d) => (
                <button
                  key={d.email}
                  onClick={() => {
                    setEmail(d.email);
                    setPassword(DEMO_PASSWORD);
                    submit(undefined, { email: d.email, password: DEMO_PASSWORD });
                  }}
                  disabled={busy}
                  className="flex w-full items-center justify-between gap-3 rounded-[12px] border border-line bg-surface px-3.5 py-2.5 text-left transition hover:border-primary/40 hover:bg-white"
                >
                  <span>
                    <span className="block text-sm font-medium">{d.who}</span>
                    <span className="block text-xs text-muted">{d.what}</span>
                  </span>
                  <ArrowRight className="size-4 shrink-0 text-muted" />
                </button>
              ))}
            </div>
            <p className="mt-3 text-xs text-muted">
              Demo password: <code className="rounded bg-sunk px-1.5 py-0.5">{DEMO_PASSWORD}</code> · Try the agents on the{" "}
              <a className="underline" href="/demo/skyline">
                Skyline
              </a>{" "}
              and{" "}
              <a className="underline" href="/demo/brightsmile">
                BrightSmile
              </a>{" "}
              demo websites.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
