import { useEffect, useState } from "react";
import { EXAMPLES } from "../constants";
import Icon from "./Icon";

export default function IdeaForm({ onSubmit, busy, initial = "", submitLabel = "Launch the crew", showExamples = true, rows = 3 }) {
  const [idea, setIdea] = useState(initial);
  useEffect(() => setIdea(initial), [initial]);
  const ok = idea.trim().length >= 5;
  return (
    <form className="idea-form" onSubmit={(e) => { e.preventDefault(); if (ok) onSubmit(idea.trim()); }}>
      <textarea rows={rows} maxLength={500} required minLength={5} value={idea} onChange={(e) => setIdea(e.target.value)}
        placeholder="Describe your product idea in a sentence…" aria-label="Product idea" data-autofocus />
      {showExamples && (
        <div className="row wrap">
          {EXAMPLES.map((x) => <button type="button" key={x} className="chip" onClick={() => setIdea(x)}>{x}</button>)}
        </div>
      )}
      <div className="row between wrap">
        <span className="muted small">{idea.length}/500</span>
        <button className="btn primary" disabled={busy || !ok}>{busy ? "Starting the crew…" : <><Icon name="rocket" size={17} /> {submitLabel}</>}</button>
      </div>
    </form>
  );
}