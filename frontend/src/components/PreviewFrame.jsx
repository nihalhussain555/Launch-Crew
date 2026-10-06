import { useState } from "react";

/** Generated pages are untrusted: sandboxed iframe (scripts allowed for the page's own JS, no same-origin, no navigation). */
export default function PreviewFrame({ html, loading }) {
  const [mode, setMode] = useState("desktop");
  return (
    <section className="card">
      <div className="row between">
        <h2>Preview</h2>
        <div className="seg" role="group" aria-label="Viewport">
          {["desktop", "mobile"].map((m) => (
            <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{m === "desktop" ? "Desktop" : "Mobile"}</button>
          ))}
        </div>
      </div>
      {!html ? <div className="empty muted">{loading ? "Building the page…" : "The page will appear here once the Engineer finishes."}</div> : (
        <div className="frame-wrap">
          <iframe title="Landing page preview" sandbox="allow-scripts" srcDoc={html} className={`frame ${mode}`} />
        </div>
      )}
    </section>
  );
}
