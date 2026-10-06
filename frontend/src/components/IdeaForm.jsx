import { useState } from "react";

const EXAMPLES = ["A habit tracker for night-shift workers", "A meal-prep planner for busy parents", "A language-exchange app for retirees"];

export default function IdeaForm({ onSubmit, busy }) {
  const [idea, setIdea] = useState("");
  return (
    <form className="card" onSubmit={(e) => { e.preventDefault(); onSubmit(idea.trim()); }}>
      <h2>What are we launching?</h2>
      <textarea rows={3} maxLength={500} required minLength={5} value={idea} onChange={(e) => setIdea(e.target.value)}
        placeholder="Describe your product idea in a sentence…" />
      <div className="row wrap">
        {EXAMPLES.map((x) => <button type="button" key={x} className="chip" onClick={() => setIdea(x)}>{x}</button>)}
      </div>
      <button className="btn primary" disabled={busy || idea.trim().length < 5}>{busy ? "Starting the crew…" : "Launch the crew"}</button>
    </form>
  );
}
