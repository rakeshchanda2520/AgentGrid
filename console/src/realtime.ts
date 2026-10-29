import { useEffect, useRef } from "react";
import { store, wsUrl } from "./api";

/** Live tenant events (new messages, state changes) over the inbox socket. Reconnects with backoff. */
export function useTenantEvents(tenantId: string | undefined, onEvent: (e: any) => void) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    if (!tenantId) return;
    let ws: WebSocket | null = null;
    let tries = 0;
    let stopped = false;
    let ping: number | undefined;
    const connect = () => {
      const token = store.tokens()?.access_token;
      if (!token || stopped) return;
      ws = new WebSocket(wsUrl(`/ws/inbox?token=${encodeURIComponent(token)}&tenant=${tenantId}`));
      ws.onopen = () => {
        tries = 0;
        ping = window.setInterval(() => ws?.readyState === 1 && ws.send("ping"), 25000);
      };
      ws.onmessage = (m) => handler.current(JSON.parse(m.data));
      ws.onclose = () => {
        window.clearInterval(ping);
        if (!stopped) setTimeout(connect, Math.min(15000, 1000 * 2 ** tries++));
      };
    };
    connect();
    return () => {
      stopped = true;
      window.clearInterval(ping);
      ws?.close();
    };
  }, [tenantId]);
}
