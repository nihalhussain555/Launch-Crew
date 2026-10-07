import { Link } from "react-router-dom";
import Icon from "./Icon";

/** Route/section level failure state with an honest message and a way out. */
export default function ErrorState({ title = "We couldn’t load this", message, retry, back, backLabel = "Back to dashboard" }) {
  return (
    <div className="error-state" role="alert">
      <span className="err-ico" aria-hidden="true"><Icon name="alert" size={26} strokeWidth={1.6} /></span>
      <h3>{title}</h3>
      {message && <p className="muted">{message}</p>}
      <div className="row" style={{ justifyContent: "center" }}>
        {retry && <button className="btn ghost" onClick={retry}><Icon name="refresh" size={15} /> Try again</button>}
        {back && <Link className="btn primary" to={back}><Icon name="left" size={15} /> {backLabel}</Link>}
      </div>
    </div>
  );
}
