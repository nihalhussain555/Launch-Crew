/* One change, two readings: the interleaved unified rows and the aligned side-by-side pair.
   The server sends both for every comparison, so switching views costs no request and no recompute. */
import Icon from "./Icon";

const MARK = { add: "+", del: "-", hunk: "@", ctx: " " };

export function DiffModeToggle({ mode, setMode }) {
  return (
    <div className="seg" role="group" aria-label="Diff view">
      {[["unified", "Unified"], ["side", "Side by side"]].map(([id, text]) => (
        <button key={id} type="button" className={mode === id ? "on" : ""} aria-pressed={mode === id}
          onClick={() => setMode(id)}>
          <Icon name={id === "side" ? "columns" : "code"} size={14} /> {text}
        </button>
      ))}
    </div>
  );
}

function Unified({ rows }) {
  return (
    <div className="diff" role="table" aria-label="Unified diff">
      {rows.map((r, i) => (
        <div key={i} className={`diff-line ${r.kind}`} role="row">
          <span className="diff-mark" aria-hidden="true">{MARK[r.kind] ?? " "}</span>
          <span className="diff-text">{r.text}</span>
        </div>
      ))}
    </div>
  );
}

function Aligned({ rows }) {
  const bad = (r) => r.l && (r.kind === "del" || r.kind === "chg");
  const good = (r) => r.r && (r.kind === "add" || r.kind === "chg");
  return (
    <div className="diff diff-side" role="table" aria-label="Side-by-side diff">
      {rows.map((r, i) => (r.kind === "gap" ? (
        <div key={i} className="diff-gap" role="row">… {r.lines} unchanged line(s)</div>
      ) : (
        <div key={i} className="diff-pair" role="row">
          <span className="diff-no">{r.l ? r.l.n : ""}</span>
          <span className={`diff-cell left${bad(r) ? " bad" : ""}`}>{r.l ? r.l.text : ""}</span>
          <span className="diff-no">{r.r ? r.r.n : ""}</span>
          <span className={`diff-cell right${good(r) ? " good" : ""}`}>{r.r ? r.r.text : ""}</span>
        </div>
      )))}
    </div>
  );
}

/** One file's rows in the chosen view. */
export function DiffBody({ rows, side, mode }) {
  return mode === "side" ? <Aligned rows={side || []} /> : <Unified rows={rows || []} />;
}

/** A whole file-set diff: every file named, counted and rendered in the same view. */
export function FileDiffList({ files, mode }) {
  return (
    <div className="stack">
      {files.map((f) => (
        <div key={f.file} className="stack">
          <p className="muted small">
            <strong className="mono">{f.file}</strong> · +{f.added} -{f.removed}
            {f.left_lines != null ? ` · ${f.left_lines} → ${f.right_lines} lines` : ""}
            {f.truncated ? " · rows truncated" : ""}
          </p>
          {!f.changed ? <p className="muted small">Identical in both states.</p>
            : <DiffBody rows={f.rows} side={f.side} mode={mode} />}
        </div>
      ))}
    </div>
  );
}
