import { ArrowLeft, RotateCcw, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useTenantEvents } from "../realtime";
import { useSession } from "../session";
import { Button, Card, CardHead, Field, Input, PageHeader, Select, cx, useLoad, useToast } from "../ui";

const SKIN = {
  whatsapp: { name: "WhatsApp", head: "#075E54", bg: "#ECE5DD", me: "#DCF8C6", them: "#FFFFFF", ink: "#111B21" },
  telegram: { name: "Telegram", head: "#2AABEE", bg: "#DCE7F0", me: "#EFFDDE", them: "#FFFFFF", ink: "#0F1419" },
} as const;

type Msg = { id?: string; role: string; text: string };

export default function Simulator() {
  const { tenant } = useSession();
  const toast = useToast();
  const agents = useLoad(() => api("/agents"), []);
  const [channel, setChannel] = useState<"whatsapp" | "telegram">("whatsapp");
  const [agentId, setAgentId] = useState("");
  const [name, setName] = useState("Priya Sharma");
  const [user, setUser] = useState(() => `9198${Math.floor(10000000 + Math.random() * 89999999)}`);
  const [conv, setConv] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [waiting, setWaiting] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const skin = SKIN[channel];

  useEffect(() => {
    if (!agentId && agents.data?.length) setAgentId(agents.data[0].id);
  }, [agents.data, agentId]);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, waiting]);

  useTenantEvents(tenant?.id, (e) => {
    if (e.type !== "message" || !conv || e.conversation_id !== conv || e.message.role === "user") return;
    setWaiting(false);
    setMsgs((m) => (m.some((x) => x.id === e.message.id) ? m : [...m, { id: e.message.id, role: e.message.role, text: e.message.content }]));
  });

  async function send() {
    if (!text.trim() || !agentId) return;
    const t = text;
    setText("");
    setMsgs((m) => [...m, { role: "user", text: t }]);
    setWaiting(true);
    try {
      const r = await api(`/simulator/${channel}`, { body: { agent_id: agentId, user_id: user, name, text: t } });
      setConv(r.conversation_id);
      if (r.state && r.state !== "BOT_ACTIVE") setWaiting(false);
    } catch (e: any) {
      setWaiting(false);
      toast(e.message, "bad");
    }
  }

  function reset() {
    setUser(`9198${Math.floor(10000000 + Math.random() * 89999999)}`);
    setConv(null);
    setMsgs([]);
  }

  return (
    <div className="rise">
      <PageHeader title="Channel simulator" sub="Try WhatsApp and Telegram without a phone or a Meta account. Messages go through the same pipeline as real webhooks, so they show up in the inbox and trigger workflows." />
      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <Card className="h-fit">
          <CardHead title="Setup" />
          <div className="space-y-4 p-5">
            <Field label="Channel">
              <div className="grid grid-cols-2 gap-2">
                {(["whatsapp", "telegram"] as const).map((c) => (
                  <button key={c} onClick={() => { setChannel(c); reset(); }} className={cx("rounded-[10px] border px-3 py-2 text-sm font-medium", channel === c ? "border-primary bg-primary text-primary-ink" : "border-line bg-white")}>{SKIN[c].name}</button>
                ))}
              </div>
            </Field>
            <Field label="Agent"><Select value={agentId} onChange={(e) => { setAgentId(e.target.value); reset(); }}>{agents.data?.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
            <Field label="Customer name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label={channel === "whatsapp" ? "Customer phone (wa_id)" : "Telegram chat id"}><Input value={user} onChange={(e) => setUser(e.target.value)} /></Field>
            <Button variant="secondary" onClick={reset}><RotateCcw className="size-4" /> New customer</Button>
            {conv && <Link to={`/inbox/${conv}`} className="block text-sm underline">Open this conversation in the inbox</Link>}
          </div>
        </Card>

        <div className="flex justify-center">
          <div className="w-full max-w-[390px] overflow-hidden rounded-[36px] border-[10px] border-ink bg-ink shadow-soft">
            <div className="flex items-center gap-3 px-4 py-3 text-white" style={{ background: skin.head }}>
              <ArrowLeft className="size-5 opacity-80" />
              <div className="flex size-9 items-center justify-center rounded-full bg-white/20 font-semibold">{(agents.data?.find((a: any) => a.id === agentId)?.name || "A").charAt(0)}</div>
              <div className="leading-tight">
                <div className="text-[15px] font-semibold">{tenant?.name}</div>
                <div className="text-xs opacity-80">{waiting ? "typing…" : "online"}</div>
              </div>
            </div>
            <div className="scroll-thin h-[520px] space-y-2 overflow-y-auto px-3 py-4" style={{ background: skin.bg }}>
              {msgs.length === 0 && <div className="mx-auto mt-6 w-fit rounded-lg bg-white/80 px-3 py-1.5 text-center text-xs" style={{ color: skin.ink }}>Say hi, ask a price, share your budget, book a visit, or ask for a person.</div>}
              {msgs.map((m, i) => (
                <div key={i} className={cx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                  <div className="max-w-[80%] whitespace-pre-wrap rounded-[10px] px-3 py-2 text-[14px] leading-snug shadow-sm" style={{ background: m.role === "user" ? skin.me : skin.them, color: skin.ink }}>
                    {m.role === "human" && <div className="mb-0.5 text-[11px] font-semibold" style={{ color: skin.head }}>Team</div>}
                    {m.text.replace(/\s*\[S\d+\]/g, "")}
                  </div>
                </div>
              ))}
              {waiting && <div className="w-fit rounded-[10px] bg-white px-3 py-2 text-sm shadow-sm" style={{ color: skin.ink }}>…</div>}
              <div ref={end} />
            </div>
            <form className="flex gap-2 bg-[#F0F0F0] p-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
              <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Message" className="h-10 flex-1 rounded-full bg-white px-4 text-sm text-[#111] outline-none" aria-label="Message" />
              <button type="submit" className="flex size-10 items-center justify-center rounded-full text-white" style={{ background: skin.head }} aria-label="Send"><Send className="size-4" /></button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
