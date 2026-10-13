import { useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import Icon from "./Icon";

// The statuses in which the crew is working on a run, which is the only moment a Stop means anything.
const BUILDING = new Set(["queued", "running", "deploying"]);

/**
 * Stop the build, from the run page or the IDE toolbar.
 *
 * One press, no confirmation, because stopping is what the user just asked for. The backend answers with
 * what it actually reached - the step in flight is abandoned when the build runs in this worker, otherwise
 * the run ends at its next boundary - and that answer is shown as it came, not rewritten into reassurance.
 */
export default function StopBuild({ run, onChange, onRefresh, className = "btn danger small" }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!BUILDING.has(run?.status)) return null;
  const stopping = !!run.stop_requested;

  const stop = async () => {
    setBusy(true);
    try {
      const r = await api.stopRun(run.id);
      onChange?.(r.run);
      toast(r.message, "info");
    } catch (e) {
      toast(e.message, "error");
      // The build ended between the render and the click: re-read the run so the button goes away.
      if (e.status === 409) onRefresh?.();
    } finally { setBusy(false); }
  };

  return (
    <button className={className} onClick={stop} disabled={busy}
      title="End this build now. The crew stops at its next step, and a page it already published stays yours to review.">
      <Icon name="stop" size={14} /> {stopping ? "Stopping…" : "Stop build"}
    </button>
  );
}
