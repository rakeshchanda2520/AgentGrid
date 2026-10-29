import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, store } from "./api";

export type Tenant = { id: string; parent_id: string | null; kind: "platform" | "agency" | "client"; name: string; slug: string; branding: Brand; brand?: Brand; role: string | null };
export type Brand = {
  product_name?: string;
  primary_color?: string;
  accent_color?: string;
  logo_url?: string | null;
  support_email?: string | null;
  hide_powered_by?: boolean;
  widget_title?: string;
};
type Me = { user: { id: string; email: string; name: string; is_platform_admin: boolean }; active_tenant: string; role: string; tenants: Tenant[] };

const PERMS: Record<string, string[]> = {
  platform_admin: ["*"],
  agency_admin: ["clients", "branding", "models", "agents", "inbox", "leads", "workflows", "analytics", "users", "audit"],
  client_admin: ["models", "agents", "inbox", "leads", "workflows", "analytics", "users", "audit"],
  human_agent: ["inbox", "leads", "analytics"],
  viewer: ["analytics"],
};

export const DEFAULT_BRAND: Required<Pick<Brand, "product_name" | "primary_color" | "accent_color">> = {
  product_name: "AgentGrid",
  primary_color: "#172554",
  accent_color: "#C19A5B",
};

function darken(hex: string, amount: number) {
  const n = parseInt(hex.slice(1), 16);
  const f = (c: number) => Math.max(0, Math.round(c * (1 - amount)));
  return `#${[(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => f(c).toString(16).padStart(2, "0")).join("")}`;
}

/** The server resolves the full chain (platform → agency → client, nearest wins); fall back to what's visible. */
export function resolveBrand(tenants: Tenant[], id: string | null): Brand {
  const resolved = tenants.find((x) => x.id === id)?.brand;
  if (resolved) return resolved;
  const chain: Tenant[] = [];
  let t = tenants.find((x) => x.id === id);
  while (t) {
    chain.unshift(t);
    t = tenants.find((x) => x.id === t!.parent_id);
  }
  return chain.reduce<Brand>((b, x) => ({ ...b, ...Object.fromEntries(Object.entries(x.branding || {}).filter(([, v]) => v !== null && v !== "")) }), { ...DEFAULT_BRAND });
}

export function applyBrand(b: Brand) {
  const r = document.documentElement.style;
  const primary = b.primary_color || DEFAULT_BRAND.primary_color;
  const accent = b.accent_color || DEFAULT_BRAND.accent_color;
  r.setProperty("--primary", primary);
  r.setProperty("--accent", accent);
  r.setProperty("--accent-ink", accent.toLowerCase() === "#c19a5b" ? "#8a6a2f" : darken(accent, 0.45));
  document.title = b.product_name || "AgentGrid";
}

type Session = {
  me: Me | null;
  loading: boolean;
  tenant: Tenant | null;
  role: string;
  brand: Brand;
  can: (perm: string) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  switchTenant: (id: string) => void;
  reload: () => Promise<void>;
};

const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<string | null>(store.tenant());

  const reload = useCallback(async () => {
    if (!store.tokens()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      const data = await api<Me>("/auth/me", { tenant: store.tenant() });
      setMe(data);
      if (!store.tenant() || !data.tenants.some((t) => t.id === store.tenant())) {
        store.setTenant(data.active_tenant);
        setActive(data.active_tenant);
      }
    } catch {
      store.setTenant(null);
      try {
        const data = await api<Me>("/auth/me", { tenant: null });
        setMe(data);
        store.setTenant(data.active_tenant);
        setActive(data.active_tenant);
      } catch {
        setMe(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
    const out = () => setMe(null);
    window.addEventListener("ag:logout", out);
    return () => window.removeEventListener("ag:logout", out);
  }, [reload]);

  const tenant = me?.tenants.find((t) => t.id === active) || null;
  const role = me?.user.is_platform_admin ? "platform_admin" : tenant?.role || "viewer";
  const brand = useMemo(() => (me ? resolveBrand(me.tenants, active) : DEFAULT_BRAND), [me, active]);

  useEffect(() => {
    if (me) applyBrand(brand);
  }, [me, brand]);

  const value: Session = {
    me,
    loading,
    tenant,
    role,
    brand,
    can: (perm) => {
      const p = PERMS[role] || [];
      return p.includes("*") || p.includes(perm);
    },
    login: async (email, password) => {
      const tokens = await api("/auth/login", { body: { email, password }, tenant: null });
      store.setTokens(tokens);
      store.setTenant(null);
      setLoading(true);
      await reload();
    },
    logout: () => {
      const t = store.tokens();
      if (t) api("/auth/logout", { body: { refresh_token: t.refresh_token } }).catch(() => {});
      store.setTokens(null);
      store.setTenant(null);
      setMe(null);
      applyBrand(DEFAULT_BRAND);
    },
    switchTenant: (id) => {
      store.setTenant(id);
      setActive(id);
    },
    reload,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession() {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside provider");
  return s;
}
