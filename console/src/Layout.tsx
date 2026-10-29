import {
  Bot,
  Building2,
  CalendarDays,
  Cpu,
  Inbox,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquareShare,
  Settings,
  Users2,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "./api";
import { useTenantEvents } from "./realtime";
import { useSession } from "./session";
import { Badge, Logo, Select, cx } from "./ui";

type Item = { to: string; label: string; icon: ReactNode; perm: string; scope: "client" | "agency" | "any" };

const NAV: Item[] = [
  { to: "/", label: "Dashboard", icon: <LayoutDashboard className="size-4" />, perm: "analytics", scope: "any" },
  { to: "/inbox", label: "Inbox", icon: <Inbox className="size-4" />, perm: "inbox", scope: "client" },
  { to: "/leads", label: "Leads", icon: <Users2 className="size-4" />, perm: "leads", scope: "client" },
  { to: "/appointments", label: "Appointments", icon: <CalendarDays className="size-4" />, perm: "leads", scope: "client" },
  { to: "/agents", label: "Agents", icon: <Bot className="size-4" />, perm: "analytics", scope: "client" },
  { to: "/workflows", label: "Workflows", icon: <Workflow className="size-4" />, perm: "workflows", scope: "client" },
  { to: "/simulator", label: "Channel simulator", icon: <MessageSquareShare className="size-4" />, perm: "inbox", scope: "client" },
  { to: "/clients", label: "Clients", icon: <Building2 className="size-4" />, perm: "clients", scope: "agency" },
  { to: "/models", label: "AI models", icon: <Cpu className="size-4" />, perm: "models", scope: "any" },
  { to: "/settings", label: "Settings", icon: <Settings className="size-4" />, perm: "users", scope: "any" },
];

const ROLE_LABEL: Record<string, string> = {
  platform_admin: "Platform admin",
  agency_admin: "Agency admin",
  client_admin: "Workspace admin",
  human_agent: "Team member",
  viewer: "Viewer",
};

export default function Layout() {
  const { me, tenant, role, brand, can, logout, switchTenant } = useSession();
  const [open, setOpen] = useState(false);
  const [waiting, setWaiting] = useState(0);
  const loc = useLocation();
  const isClient = tenant?.kind === "client";

  useEffect(() => {
    setOpen(false);
  }, [loc.pathname]);

  useEffect(() => {
    if (!tenant || !isClient || !can("inbox")) return;
    let alive = true;
    const poll = () => api("/analytics/live").then((d) => alive && setWaiting(d.waiting_for_human || 0)).catch(() => {});
    poll();
    const t = window.setInterval(poll, 20000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenant?.id]);

  useTenantEvents(isClient && can("inbox") ? tenant?.id : undefined, (e) => {
    if (e.type === "conversation" || (e.type === "message" && e.state)) api("/analytics/live").then((d) => setWaiting(d.waiting_for_human || 0)).catch(() => {});
  });

  const items = NAV.filter((i) => can(i.perm) && (i.scope === "any" || (i.scope === "client" ? isClient : tenant?.kind !== "client")));
  const groups = me
    ? me.tenants.filter((t) => t.kind !== "client").map((g) => ({ g, kids: me.tenants.filter((t) => t.parent_id === g.id && t.kind === "client") }))
    : [];
  const orphans = me ? me.tenants.filter((t) => t.kind === "client" && !me.tenants.some((g) => g.id === t.parent_id)) : [];

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-5 pb-5 pt-6">
        <Logo brand={brand} />
        <button className="rounded-lg p-1.5 text-muted hover:bg-sunk lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
          <X className="size-5" />
        </button>
      </div>
      <div className="px-4 pb-4">
        <label className="mb-1.5 block px-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Workspace</label>
        <Select value={tenant?.id || ""} onChange={(e) => switchTenant(e.target.value)} aria-label="Switch workspace">
          {groups.map(({ g, kids }) => (
            <optgroup key={g.id} label={g.kind === "platform" ? "Platform" : g.name}>
              <option value={g.id}>{g.kind === "agency" ? `${g.name} (agency)` : g.name}</option>
              {kids.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </optgroup>
          ))}
          {orphans.map((k) => (
            <option key={k.id} value={k.id}>
              {k.name}
            </option>
          ))}
        </Select>
      </div>
      <nav className="scroll-thin flex-1 space-y-0.5 overflow-y-auto px-3" aria-label="Main">
        {items.map((i) => (
          <NavLink
            key={i.to}
            to={i.to}
            end={i.to === "/"}
            className={({ isActive }) =>
              cx("flex items-center gap-3 rounded-[10px] px-3 py-2 text-sm font-medium transition", isActive ? "bg-primary text-primary-ink" : "text-muted hover:bg-sunk hover:text-ink")
            }
          >
            {i.icon}
            <span className="flex-1">{i.label}</span>
            {i.to === "/inbox" && waiting > 0 && <Badge tone="warn">{waiting}</Badge>}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-line px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-full bg-sunk text-sm font-semibold text-accent-ink">{me?.user.name.charAt(0)}</div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{me?.user.name}</div>
            <div className="truncate text-xs text-muted">{ROLE_LABEL[role] || role}</div>
          </div>
          <button onClick={logout} className="rounded-lg p-2 text-muted hover:bg-sunk hover:text-ink" aria-label="Sign out" title="Sign out">
            <LogOut className="size-4" />
          </button>
        </div>
        {!brand.hide_powered_by && brand.product_name !== "AgentGrid" && <div className="mt-3 text-[11px] text-muted">Powered by AgentGrid</div>}
      </div>
    </div>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-[256px] shrink-0 border-r border-line bg-surface lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 bg-ink/30 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-[280px] bg-surface shadow-soft" onClick={(e) => e.stopPropagation()}>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3 lg:hidden">
          <button onClick={() => setOpen(true)} className="rounded-lg p-1.5 text-ink hover:bg-sunk" aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          <Logo brand={brand} />
        </div>
        <main className="scroll-thin flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1320px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            {tenant && tenant.kind !== "client" && loc.pathname === "/" && (
              <div className="mb-5 text-xs text-muted">
                {tenant.kind === "agency" ? "Agency view: totals across all your client workspaces." : "Platform view: totals across every client workspace."}
              </div>
            )}
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
