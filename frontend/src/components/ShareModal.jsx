import { useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import { copyText } from "../utils";
import Icon from "./Icon";
import Modal from "./Modal";

/** Create / copy / revoke the public preview link. Visitors can leave feedback without an account. */
export default function ShareModal({ open, onClose, run, onChange }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const token = run.share_token;
  const url = token ? `${window.location.origin}/p/${token}` : "";

  const create = async () => {
    setBusy(true);
    try { const r = await api.share(run.id); onChange({ ...run, share_token: r.token }); toast("Share link created", "success"); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  const revoke = async () => {
    setBusy(true);
    try { await api.unshare(run.id); onChange({ ...run, share_token: null }); toast("Link revoked. Old URL no longer works.", "info"); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  const copy = async () => {
    if (await copyText(url)) toast("Link copied", "success");
    else toast("Could not copy. Select the link and copy it manually.", "error");
  };

  return (
    <Modal open={open} onClose={onClose} title="Share a preview" size="md"
      footer={<button className="btn ghost" onClick={onClose}>Done</button>}>
      <p className="muted">Send this link to teammates, clients or friends. They see the page and can leave feedback, no account needed. You can turn their feedback into an AI revision in one click.</p>
      {token ? (
        <>
          <div className="copy-row">
            <input readOnly value={url} onFocus={(e) => e.target.select()} aria-label="Preview link" data-autofocus />
            <button className="btn primary" onClick={copy}>Copy</button>
          </div>
          <p className="muted small">Anyone with the link can view this version and send feedback. Revoke it any time.</p>
          <button className="btn danger" onClick={revoke} disabled={busy}>Stop sharing</button>
        </>
      ) : (
        <button className="btn primary" onClick={create} disabled={busy} data-autofocus>{busy ? "Creating…" : <><Icon name="link" size={16} /> Create share link</>}</button>
      )}
    </Modal>
  );
}