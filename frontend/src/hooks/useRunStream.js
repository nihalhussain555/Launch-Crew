import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export const EVENT_TYPES = ["agent_started", "agent_message", "tool_call", "rate_limited", "check_results", "critic_feedback",
  "screenshot_ready", "awaiting_approval", "deployed", "failed"];
const FINAL = new Set(["deployed", "failed"]);

/** Live SSE connection. Replays history on connect, dedupes by seq, closes after a final event. */
export function useRunStream(runId, onEvent) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    setEvents([]);
    const es = new EventSource(api.streamUrl(runId));
    const seen = new Set();
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false); // the browser reconnects automatically (Last-Event-ID)
    EVENT_TYPES.forEach((type) =>
      es.addEventListener(type, (e) => {
        const seq = Number(e.lastEventId);
        if (seen.has(seq)) return;
        seen.add(seq);
        let data = {};
        try { data = JSON.parse(e.data); } catch { /* ignore malformed */ }
        const ev = { seq, type, data };
        setEvents((prev) => [...prev, ev]);
        cb.current?.(ev);
        if (FINAL.has(type)) { es.close(); setConnected(false); }
      })
    );
    return () => es.close();
  }, [runId]);

  return { events, connected };
}
