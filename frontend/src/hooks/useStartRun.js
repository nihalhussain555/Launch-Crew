import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../toast";

/** idea -> project -> run -> navigate to the live run page. */
export function useStartRun() {
  const nav = useNavigate();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const start = useCallback(async (idea) => {
    setBusy(true);
    try {
      const p = await api.createProject(idea);
      const run = await api.createRun(p.id);
      nav(`/runs/${run.id}`);
      return true;
    } catch (e) {
      toast(e.message, "error");
      return false;
    } finally {
      setBusy(false);
    }
  }, [nav, toast]);
  return { start, busy };
}