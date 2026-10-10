import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const ACTIVE = new Set(["queued", "running", "deploying"]);
const EVERY = 4000;

/**
 * One run, kept current: fetched on selection and re-fetched while its status is still moving,
 * so a page (or a hand-written patch) that finishes in the background shows up here by itself.
 */
export function useRun(runId) {
  const [run, setRun] = useState(null);
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    if (!runId) { setRun(null); return null; }
    try {
      const r = await api.getRun(runId);
      setRun(r); setErr("");
      return r;
    } catch (e) { setErr(e.message); return null; }
  }, [runId]);

  useEffect(() => { setRun(null); setErr(""); refresh(); }, [refresh]);
  useEffect(() => {
    if (!run || !ACTIVE.has(run.status)) return undefined;
    const t = setTimeout(refresh, EVERY);
    return () => clearTimeout(t);
  }, [run, refresh]);

  return { run, setRun, err, refresh, working: !!run && ACTIVE.has(run.status) };
}
