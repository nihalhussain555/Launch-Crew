import { useState } from "react";
import Modal from "./Modal";

/** Confirm dialog. `onConfirm` may be async; the button shows a busy state until it settles. */
export default function ConfirmModal({ open, title, message, children, confirmLabel = "Confirm", danger = false, onConfirm, onClose }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await onConfirm(); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={busy ? () => {} : onClose} title={title} size="sm"
      footer={<>
        <button className="btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
        <button className={`btn ${danger ? "danger" : "primary"}`} onClick={go} disabled={busy} data-autofocus>{busy ? "Working…" : confirmLabel}</button>
      </>}>
      {message && <p>{message}</p>}
      {children}
    </Modal>
  );
}