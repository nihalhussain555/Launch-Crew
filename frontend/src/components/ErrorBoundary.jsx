import { Component } from "react";
import LaunchCrewLogo from "./LaunchCrewLogo";

/** Last-resort crash screen: shows the real error instead of a blank page, and offers a way out. */
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) { return { error }; }

  componentDidCatch(error, info) { console.error("UI crashed:", error, info?.componentStack); }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="crash">
        <div className="crash-card">
          <LaunchCrewLogo size={30} />
          <h1>Something went wrong</h1>
          <p className="muted">The app hit an error while rendering. Reloading usually clears it. If it keeps happening, send the detail below to support.</p>
          <pre className="crash-detail">{String(error?.stack || error)}</pre>
          <div className="row wrap">
            <button className="btn primary" onClick={() => window.location.reload()}>Reload the app</button>
            <button className="btn ghost" onClick={() => { try { localStorage.clear(); } catch { /* ignore */ } window.location.href = "/login"; }}>
              Clear saved login &amp; sign in again
            </button>
          </div>
        </div>
      </div>
    );
  }
}
