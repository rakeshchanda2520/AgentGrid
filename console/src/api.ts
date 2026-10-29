export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

const SESSION = "ag_session";
const TENANT = "ag_tenant";

type Tokens = { access_token: string; refresh_token: string };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const store = {
  tokens(): Tokens | null {
    try {
      return JSON.parse(localStorage.getItem(SESSION) || "null");
    } catch {
      return null;
    }
  },
  setTokens(t: Tokens | null) {
    try {
      if (t) localStorage.setItem(SESSION, JSON.stringify(t));
      else localStorage.removeItem(SESSION);
    } catch {
      /* private mode: session lasts for this tab only */
    }
  },
  tenant(): string | null {
    try {
      return localStorage.getItem(TENANT);
    } catch {
      return null;
    }
  },
  setTenant(id: string | null) {
    try {
      if (id) localStorage.setItem(TENANT, id);
      else localStorage.removeItem(TENANT);
    } catch {
      /* ignore */
    }
  },
};

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  const t = store.tokens();
  if (!t) return false;
  refreshing ??= fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) return false;
      store.setTokens(await r.json());
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

type Opts = { method?: string; body?: unknown; form?: FormData; raw?: boolean; tenant?: string | null };

export async function api<T = any>(path: string, opts: Opts = {}, retried = false): Promise<T> {
  const headers: Record<string, string> = {};
  const tokens = store.tokens();
  if (tokens) headers.Authorization = `Bearer ${tokens.access_token}`;
  const tenant = opts.tenant === undefined ? store.tenant() : opts.tenant;
  if (tenant) headers["X-Tenant-Id"] = tenant;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  } catch {
    throw new ApiError(0, "Can't reach the server. If it was idle it may be waking up: try again in a few seconds.");
  }
  if (res.status === 401 && !retried && tokens && !path.startsWith("/auth/")) {
    if (await refresh()) return api<T>(path, opts, true);
    store.setTokens(null);
    window.dispatchEvent(new Event("ag:logout"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg).join("; ") : msg;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg || `Request failed (${res.status})`);
  }
  if (opts.raw) return res as unknown as T;
  return res.status === 204 ? (undefined as T) : res.json();
}

export function wsUrl(path: string) {
  return API_URL.replace(/^http/, "ws") + path;
}

export async function download(path: string, filename: string) {
  const res = await api<Response>(path, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
