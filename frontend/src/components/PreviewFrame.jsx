import { useState } from "react";
import AiWorking from "./AiWorking";
import EmptyState from "./EmptyState";

/** Generated pages are untrusted: sandboxed iframe (scripts allowed for the page's own JS, no same-origin, no navigation). */
export default function PreviewFrame({ html, loading }) {
  const [mode, setMode] = useState("desktop");

  const download = () => {
    const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "index.html" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <section className="card">
      <div className="row between wrap">
        <h2>Preview</h2>
        <div className="row">
          <button className="btn ghost small" onClick={download} disabled={!html}>Download .html</button>
          <div className="seg" role="group" aria-label="Viewport">
            {["desktop", "mobile"].map((m) => (
              <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{m === "desktop" ? "Desktop" : "Mobile"}</button>
            ))}
          </div>
        </div>
      </div>
      {!html ? (loading ? <AiWorking label="Building your page…" />
        : <EmptyState icon="monitor" title="No page yet" text="The preview appears here once the Engineer finishes." />) : (
        <div className="frame-wrap">
          <iframe title="Landing page preview" sandbox="allow-scripts" srcDoc={html} className={`frame ${mode}`} />
        </div>
      )}
    </section>
  );
}