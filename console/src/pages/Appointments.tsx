import { CalendarDays } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, Select, useLoad, useToast } from "../ui";

export default function Appointments() {
  const toast = useToast();
  const appts = useLoad(() => api("/appointments"), []);
  const groups: Record<string, any[]> = {};
  for (const a of appts.data || []) {
    const day = new Date(a.starts_at).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
    (groups[day] ||= []).push(a);
  }
  return (
    <div className="rise">
      <PageHeader title="Appointments" sub="Booked by the AI agents in conversation, without double-booking. Confirmation emails carry a calendar invite." />
      {appts.error && <ErrorNote error={appts.error} onRetry={appts.reload} />}
      {appts.loading && !appts.data ? <Loading /> : Object.keys(groups).length === 0 ? (
        <Card><Empty title="No appointments yet" icon={<CalendarDays className="size-7" />}>Ask an agent to book a visit in the playground or on a demo website.</Empty></Card>
      ) : (
        <div className="space-y-5">
          {Object.entries(groups).map(([day, items]) => (
            <Card key={day}>
              <div className="border-b border-line px-5 py-3 font-semibold">{day}</div>
              <ul>
                {items.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-3 border-b border-line/60 px-5 py-3 text-sm last:border-0">
                    <span className="w-24 font-semibold tabular-nums">{new Date(a.starts_at).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}</span>
                    <span className="min-w-0 flex-1">
                      <span className="font-medium">{a.service}</span>
                      <span className="text-muted"> · {a.customer_name || "Customer"} {a.customer_contact && `· ${a.customer_contact}`}</span>
                    </span>
                    <span className="text-xs text-muted">{a.agent_name}</span>
                    {a.conversation_id && <Link className="text-xs underline" to={`/inbox/${a.conversation_id}`}>Conversation</Link>}
                    <Badge tone={a.status === "booked" ? "ok" : a.status === "cancelled" ? "bad" : "neutral"}>{a.status}</Badge>
                    <Select
                      className="h-8 w-32 text-xs"
                      value={a.status}
                      aria-label="Change status"
                      onChange={async (e) => {
                        try {
                          await api(`/appointments/${a.id}`, { method: "PATCH", body: { status: e.target.value } });
                          appts.reload();
                        } catch (err: any) {
                          toast(err.message, "bad");
                        }
                      }}
                    >
                      <option value="booked">Booked</option>
                      <option value="completed">Completed</option>
                      <option value="cancelled">Cancelled</option>
                    </Select>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
