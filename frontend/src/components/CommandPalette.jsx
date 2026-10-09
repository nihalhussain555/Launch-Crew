import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import Modal from "./Modal";
import Icon from "./Icon";

export default function CommandPalette({ open, onClose }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const [recent, setRecent] = useState([]);

  useEffect(() => {
    if (!open) return;
    setQ(""); setIdx(0);
    api.stats().then((s) => setRecent(s.recent_runs || [])).catch(() => {});
  }, [open]);

  const items = useMemo(() => {
    const base = [
      { id: "dash", label: "Go to Dashboard", icon: "home", run: () => nav("/dashboard") },
      { id: "projects", label: "Go to Projects", icon: "folder", run: () => nav("/projects") },
      { id: "templates", label: "Browse idea templates", icon: "sparkle", run: () => nav("/templates") },
      { id: "settings", label: "Open Settings", icon: "gear", run: () => nav("/settings") },
      { id: "env", label: "Open environment manager", icon: "key", run: () => nav("/settings", { state: { openEnv: true } }) },
    ];
    const runs = recent.map((r) => ({ id: r.id, label: `Open run: ${r.idea.slice(0, 60)}`, icon: "rocket", run: () => nav(`/runs/${r.id}`) }));
    const all = [...base, ...runs];
    const t = q.trim().toLowerCase();
    return t ? all.filter((i) => i.label.toLowerCase().includes(t)) : all;
  }, [q, recent, nav]);

  useEffect(() => setIdx(0), [q]);
  const go = (item) => { if (!item) return; onClose(); item.run(); };
  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(items[idx]); }
  };

  return (
    <Modal open={open} onClose={onClose} title="Command palette" size="sm">
      <input className="palette-input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
        placeholder="Type a command or search your runs…" aria-label="Search commands" data-autofocus />
      <ul className="palette-list" role="listbox">
        {items.length === 0 && <li className="muted palette-empty">No matches</li>}
        {items.map((it, i) => (
          <li key={it.id} role="option" aria-selected={i === idx} className={`palette-item ${i === idx ? "on" : ""}`}
            onMouseEnter={() => setIdx(i)} onClick={() => go(it)}>
            <Icon name={it.icon} size={18} /> <span>{it.label}</span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}