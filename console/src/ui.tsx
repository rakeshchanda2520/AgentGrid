import { Check, Copy, Loader2, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { Brand } from "./session";

// ---------------------------------------------------------------- formatting

export const fmt = {
  num: (v?: number | null) => (v == null ? "–" : Intl.NumberFormat("en-IN").format(v)),
  pct: (v?: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`),
  ms: (v?: number | null) => (v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`),
  usd: (v?: number | null) => (v == null ? "n/a" : `$${Number(v).toFixed(v < 1 ? 4 : 2)}`),
  inr: (v?: number | string | null) => {
    if (v == null || v === "") return "–";
    const n = Number(v);
    return n >= 1e7 ? `₹${(n / 1e7).toFixed(2)} Cr` : n >= 1e5 ? `₹${(n / 1e5).toFixed(1)} L` : `₹${n.toLocaleString("en-IN")}`;
  },
  ago: (iso?: string | null) => {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  },
  dt: (iso?: string | null) =>
    iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "–",
  title: (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
};

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- data loading

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fn());
      setError(null);
    } catch (e: any) {
      setError(e.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    load();
  }, [load]);
  return { data, setData, error, loading, reload: load };
}

// ---------------------------------------------------------------- brand

export function Logo({ brand, compact = false, light = false }: { brand: Brand; compact?: boolean; light?: boolean }) {
  const name = brand.product_name || "AgentGrid";
  if (brand.logo_url) return <img src={brand.logo_url} alt={name} className="h-8 w-auto" />;
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill={light ? "#F3EBDD" : "var(--primary)"} />
        <rect x="7" y="7" width="8" height="8" rx="2" fill={light ? "var(--primary)" : "#F3EBDD"} />
        <rect x="17" y="7" width="8" height="8" rx="2" fill={light ? "var(--primary)" : "#F3EBDD"} opacity=".55" />
        <rect x="7" y="17" width="8" height="8" rx="2" fill={light ? "var(--primary)" : "#F3EBDD"} opacity=".55" />
        <rect x="17" y="17" width="8" height="8" rx="4" fill="var(--accent)" />
      </svg>
      {!compact && <span className={cx("font-serif text-[19px] font-semibold tracking-tight", light ? "text-paper" : "text-ink")}>{name}</span>}
    </span>
  );
}

// ---------------------------------------------------------------- primitives

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; busy?: boolean };

export function Button({ variant = "primary", size = "md", busy, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-[10px] font-medium transition disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-primary text-primary-ink hover:brightness-110",
        variant === "secondary" && "border border-line bg-surface text-ink hover:bg-sunk",
        variant === "ghost" && "text-muted hover:bg-sunk hover:text-ink",
        variant === "danger" && "border border-bad/30 bg-bad-bg text-bad hover:brightness-95",
        className,
      )}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cx("rounded-[16px] border border-line bg-surface shadow-soft", className)}>{children}</section>;
}

export function CardHead({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
      <div>
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        {sub && <p className="mt-0.5 text-[13px] text-muted">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

const TONES: Record<string, string> = {
  neutral: "bg-sunk text-muted",
  ok: "bg-ok-bg text-ok",
  warn: "bg-warn-bg text-warn",
  bad: "bg-bad-bg text-bad",
  info: "bg-info-bg text-info",
  gold: "bg-[#F5EAD6] text-accent-ink",
  primary: "bg-primary text-primary-ink",
};

export function Badge({ tone = "neutral", children, className }: { tone?: keyof typeof TONES | string; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium whitespace-nowrap", TONES[tone] || TONES.neutral, className)}>{children}</span>;
}

export const STATE_TONE: Record<string, string> = { BOT_ACTIVE: "info", PENDING_HUMAN: "warn", HUMAN_ACTIVE: "gold", RESOLVED: "ok" };
export const STATE_LABEL: Record<string, string> = { BOT_ACTIVE: "AI handling", PENDING_HUMAN: "Needs a person", HUMAN_ACTIVE: "With team", RESOLVED: "Resolved" };
export const STAGE_TONE: Record<string, string> = { new: "neutral", engaged: "info", qualified: "gold", hot: "warn", booked: "ok", won: "ok", lost: "bad" };

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-serif text-[28px] font-semibold leading-tight tracking-tight text-ink">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-sm text-muted">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

const fieldCls = "w-full rounded-[10px] border border-line bg-white px-3 text-sm text-ink placeholder:text-muted/60 focus:border-primary focus:outline-none";

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(fieldCls, "h-10", props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(fieldCls, "py-2.5 leading-relaxed", props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(fieldCls, "h-10 pr-8", props.className)} />;
}

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: string }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div role="tablist" className="mb-5 flex gap-1 overflow-x-auto border-b border-line scroll-thin">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cx(
            "-mb-px whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium transition",
            value === t.id ? "border-primary text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-[14px] border border-line bg-surface px-4 py-3.5 shadow-soft">
      <div className="text-[12.5px] font-medium text-muted">{label}</div>
      <div className={cx("mt-1 font-serif text-[26px] font-semibold leading-none tracking-tight", tone === "bad" ? "text-bad" : "text-ink")}>{value}</div>
      {hint && <div className="mt-1.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon && <div className="text-accent-ink">{icon}</div>}
      <div className="font-medium text-ink">{title}</div>
      {children && <div className="max-w-sm text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-[12px] border border-bad/25 bg-bad-bg px-4 py-3 text-sm text-bad" role="alert">
      <span>{error}</span>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/30 p-0 backdrop-blur-[2px] sm:items-center sm:p-6" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        className={cx("rise max-h-[92vh] w-full overflow-y-auto rounded-t-[18px] border border-line bg-surface shadow-soft sm:rounded-[18px]", wide ? "sm:max-w-3xl" : "sm:max-w-lg")}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-surface px-5 py-4">
          <h2 className="font-serif text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-sunk" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="sm"
      variant="secondary"
      onClick={() => {
        navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} {done ? "Copied" : label}
    </Button>
  );
}

export function Code({ children }: { children: string }) {
  return <pre className="scroll-thin overflow-x-auto rounded-[12px] bg-ink px-4 py-3 text-[12.5px] leading-relaxed text-paper">{children}</pre>;
}

// ---------------------------------------------------------------- toasts

type Toast = { id: number; text: string; tone: "ok" | "bad" };
const ToastCtx = createContext<(text: string, tone?: "ok" | "bad") => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "ok" | "bad" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 left-1/2 z-[60] flex -translate-x-1/2 flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={cx("rise rounded-[12px] px-4 py-2.5 text-sm shadow-soft", t.tone === "ok" ? "bg-ink text-paper" : "bg-bad text-white")}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
