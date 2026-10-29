import { Component, lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import Layout from "./Layout";
import Login from "./pages/Login";
import { SessionProvider, useSession } from "./session";
import { Loading, ToastProvider } from "./ui";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const InboxPage = lazy(() => import("./pages/Inbox"));
const Leads = lazy(() => import("./pages/Leads"));
const Appointments = lazy(() => import("./pages/Appointments"));
const Agents = lazy(() => import("./pages/Agents"));
const AgentDetail = lazy(() => import("./pages/AgentDetail"));
const Workflows = lazy(() => import("./pages/Workflows"));
const Simulator = lazy(() => import("./pages/Simulator"));
const Models = lazy(() => import("./pages/Models"));
const Clients = lazy(() => import("./pages/Clients"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const DemoSite = lazy(() => import("./pages/DemoSite"));

/** A crash in one page shows a recoverable message instead of a blank console. */
class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto max-w-lg px-6 py-24 text-center">
        <h1 className="font-serif text-2xl font-semibold">Something went wrong on this page</h1>
        <p className="mt-2 text-sm text-muted">{this.state.error.message}</p>
        <button className="mt-6 rounded-[10px] bg-primary px-4 py-2 text-sm font-medium text-primary-ink" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}

function App() {
  const { me, loading, tenant } = useSession();
  if (loading) return <Loading label="Opening your workspace" />;
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/demo/:slug" element={<DemoSite />} />
        {!me ? (
          <Route path="*" element={<Login />} />
        ) : (
          <Route element={<Layout />}>
            <Route index element={<Dashboard key={tenant?.id} />} />
            <Route path="inbox" element={<InboxPage key={tenant?.id} />} />
            <Route path="inbox/:id" element={<InboxPage key={tenant?.id} />} />
            <Route path="leads" element={<Leads key={tenant?.id} />} />
            <Route path="appointments" element={<Appointments key={tenant?.id} />} />
            <Route path="agents" element={<Agents key={tenant?.id} />} />
            <Route path="agents/:id" element={<AgentDetail key={tenant?.id} />} />
            <Route path="workflows" element={<Workflows key={tenant?.id} />} />
            <Route path="simulator" element={<Simulator key={tenant?.id} />} />
            <Route path="models" element={<Models key={tenant?.id} />} />
            <Route path="clients" element={<Clients key={tenant?.id} />} />
            <Route path="settings" element={<SettingsPage key={tenant?.id} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        )}
      </Routes>
    </Suspense>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <SessionProvider>
          <Boundary>
            <App />
          </Boundary>
        </SessionProvider>
      </ToastProvider>
    </BrowserRouter>
  </StrictMode>,
);
