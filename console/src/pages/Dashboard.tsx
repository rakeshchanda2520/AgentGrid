import { ArrowRight, Bot, Headset, Hourglass } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { useSession } from "../session";
import { Button, Card, CardHead, ErrorNote, Loading, PageHeader, Select, Stat, fmt, useLoad } from "../ui";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const tip = { contentStyle: { borderRadius: 12, border: "1px solid #E2D6C1", background: "#FBF7F0", fontSize: 12 }, cursor: { fill: "rgba(23,37,84,.04)" } };

export default function Dashboard() {
  const { tenant, switchTenant, can } = useSession();
  const [days, setDays] = useState(30);
  const isClient = tenant?.kind === "client";
  const { data, error, loading, reload } = useLoad(() => api(`/analytics/overview?days=${days}`), [days]);
  const live = useLoad(() => (isClient ? api("/analytics/live") : Promise.resolve(null)), []);
  const rollup = useLoad(() => (!isClient ? api(`/analytics/agency?days=${days}`) : Promise.resolve([])), [days]);
  const primary = css("--primary") || "#172554";
  const accent = css("--accent") || "#C19A5B";

  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} onRetry={reload} />;
  const k = data.kpis;
  const series = data.series.map((d: any) => ({ ...d, day: new Date(d.day).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) }));

  return (
    <div className="rise">
      <PageHeader
        title={isClient ? "Dashboard" : `${tenant?.name}`}
        sub={isClient ? `How ${tenant?.name}'s AI agents are performing.` : "Performance across every client workspace you manage."}
        actions={
          <Select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Date range" className="w-40">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </Select>
        }
      />

      {isClient && live.data && (
        <div className="mb-5 flex flex-wrap gap-2">
          <Link to="/inbox" className="inline-flex items-center gap-2 rounded-full border border-warn/25 bg-warn-bg px-3.5 py-1.5 text-[13px] font-medium text-warn">
            <Hourglass className="size-3.5" /> {live.data.waiting_for_human} waiting for a person <ArrowRight className="size-3.5" />
          </Link>
          <span className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-1.5 text-[13px] text-muted">
            <Headset className="size-3.5" /> {live.data.with_human} with your team
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-1.5 text-[13px] text-muted">
            <Bot className="size-3.5" /> {live.data.active_with_ai} active with AI now
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Conversations" value={fmt.num(k.conversations)} hint={`${fmt.num(k.messages)} messages`} />
        <Stat label="Automated resolution" value={fmt.pct(k.automated_resolution_rate)} hint="Resolved with no human reply" />
        <Stat label="Escalation rate" value={fmt.pct(k.escalation_rate)} hint="Handed to a person" />
        <Stat label="First response (median)" value={fmt.ms(k.first_response_p50_ms)} hint={`p95 ${fmt.ms(k.first_response_p95_ms)}`} />
        <Stat label="Qualified leads" value={fmt.num(k.leads_qualified)} hint={`${fmt.pct(k.lead_conversion_rate)} of ${fmt.num(k.leads_captured)} captured`} />
        <Stat label="Appointments booked" value={fmt.num(k.appointments)} hint={`${fmt.pct(k.booking_rate)} of qualified leads`} />
        <Stat label="Customer rating" value={k.csat ? `${k.csat.toFixed(1)} / 5` : "–"} hint={`${fmt.num(k.csat_responses)} ratings`} />
        <Stat label="LLM cost" value={fmt.usd(k.llm_cost_usd)} hint={`${fmt.num(k.tokens_in + k.tokens_out)} tokens`} />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHead title="Conversations per day" sub="Total, qualified and escalated" />
          <div className="h-[260px] px-2 pb-3 pt-4">
            <ResponsiveContainer>
              <AreaChart data={series} margin={{ left: -18, right: 12 }}>
                <defs>
                  <linearGradient id="gConv" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={primary} stopOpacity={0.22} />
                    <stop offset="100%" stopColor={primary} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#E2D6C1" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#4A5578" }} tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis tick={{ fontSize: 11, fill: "#4A5578" }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip {...tip} />
                <Area type="monotone" dataKey="conversations" name="Conversations" stroke={primary} strokeWidth={2} fill="url(#gConv)" />
                <Area type="monotone" dataKey="qualified" name="Qualified" stroke={accent} strokeWidth={2} fill="transparent" />
                <Area type="monotone" dataKey="escalated" name="Escalated" stroke="#9B2C2C" strokeWidth={1.5} strokeDasharray="4 3" fill="transparent" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <CardHead title="Lead funnel" sub="From first message to booking" />
          <div className="space-y-3.5 px-5 py-5">
            {data.funnel.map((f: any) => {
              const top = data.funnel[0].value || 1;
              return (
                <div key={f.stage}>
                  <div className="mb-1 flex justify-between text-[13px]">
                    <span className="text-muted">{f.stage}</span>
                    <span className="font-semibold">{fmt.num(f.value)}</span>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-sunk">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(3, (100 * f.value) / top)}%`, opacity: 0.55 + (0.45 * f.value) / top }} />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      {!isClient && (
        <Card className="mt-5">
          <CardHead title="Client workspaces" sub="Open a workspace to see its inbox, agents and settings" />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr className="border-b border-line">
                  {["Client", "Agents", "Conversations", "Escalated", "Qualified", "Booked", "LLM cost", ""].map((h) => (
                    <th key={h} className="px-5 py-2.5 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(rollup.data || []).map((r: any) => (
                  <tr key={r.id} className="border-b border-line/60 last:border-0">
                    <td className="px-5 py-3 font-medium">{r.name}</td>
                    <td className="px-5 py-3">{r.agents}</td>
                    <td className="px-5 py-3">{fmt.num(r.conversations)}</td>
                    <td className="px-5 py-3">{fmt.pct(r.conversations ? r.escalated / r.conversations : null)}</td>
                    <td className="px-5 py-3">{fmt.num(r.qualified)}</td>
                    <td className="px-5 py-3">{fmt.num(r.booked)}</td>
                    <td className="px-5 py-3">{fmt.usd(Number(r.cost_usd))}</td>
                    <td className="px-5 py-3 text-right">
                      <Button size="sm" variant="secondary" onClick={() => switchTenant(r.id)}>
                        Open <ArrowRight className="size-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card>
          <CardHead title="Channels" sub="Where conversations start" />
          <div className="h-[220px] px-2 pb-3 pt-4">
            <ResponsiveContainer>
              <BarChart data={data.channels} layout="vertical" margin={{ left: 12, right: 18 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="channel" tick={{ fontSize: 12, fill: "#172554" }} tickLine={false} axisLine={false} width={72} tickFormatter={fmt.title} />
                <Tooltip {...tip} />
                <Bar dataKey="conversations" name="Conversations" radius={[0, 6, 6, 0]} barSize={18}>
                  {data.channels.map((_: any, i: number) => (
                    <Cell key={i} fill={i === 0 ? primary : i === 1 ? accent : "#7D8BB0"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card className="lg:col-span-2">
          <CardHead title="AI agents" sub="Volume, escalations and speed per agent" />
          <SimpleTable
            cols={["Agent", "Conversations", "Resolved by AI", "Escalated", "First response"]}
            rows={data.agents.map((a: any) => [
              a.name,
              fmt.num(a.conversations),
              fmt.pct(a.conversations ? a.auto_resolved / a.conversations : null),
              fmt.pct(a.conversations ? a.escalated / a.conversations : null),
              fmt.ms(a.frt_p50),
            ])}
          />
        </Card>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHead title="Team performance" sub="Human agents after handover" />
          <SimpleTable cols={["Team member", "Conversations", "Replies"]} rows={data.humans.map((h: any) => [h.name, fmt.num(h.conversations), fmt.num(h.replies)])} empty="No human replies in this period." />
        </Card>
        <Card>
          <CardHead title="Model usage" sub={can("models") ? <Link className="underline" to="/models">Manage AI models</Link> : "Tokens and cost by model"} />
          <SimpleTable
            cols={["Model", "Replies", "Tokens", "Cost"]}
            rows={data.usage.map((u: any) => [u.model || "–", fmt.num(u.messages), fmt.num(Number(u.tokens_in) + Number(u.tokens_out)), fmt.usd(Number(u.cost_usd))])}
            empty="No model usage yet."
          />
        </Card>
      </div>
    </div>
  );
}

export function SimpleTable({ cols, rows, empty = "Nothing here yet." }: { cols: string[]; rows: React.ReactNode[][]; empty?: string }) {
  if (!rows.length) return <div className="px-5 py-8 text-center text-sm text-muted">{empty}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-line">
            {cols.map((c) => (
              <th key={c} className="px-5 py-2.5 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/60 last:border-0">
              {r.map((c, j) => (
                <td key={j} className={j === 0 ? "px-5 py-3 font-medium" : "px-5 py-3 text-muted"}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
