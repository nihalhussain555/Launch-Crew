import { Link, useParams } from "react-router-dom";
import Icon from "../components/Icon";

/* Plain-language policy copy that describes what this product actually does with data. */
const UPDATED = "October 7, 2026";

const DOCS = {
  privacy: {
    title: "Privacy Policy",
    intro:
      "Launch Crew stores the minimum needed to run your workspace: your email and name, the ideas you submit, the pages our agents generate, and the feedback left on shareable preview links.",
    points: [
      ["What we keep", "Account details (email, display name), projects, runs, generated page files, deploy records, and stakeholder feedback attached to a preview link."],
      ["What we do not do", "We do not sell your data, and we do not use your workspace content to train third-party models."],
      ["Preview links", "Shared previews are unlisted. Anyone with the exact link can view the page and leave feedback; remove the link from the run to stop access."],
      ["On your device", "Two browser storage keys hold your session token and your appearance choice. Nothing else is written locally."],
      ["Removing your data", "Delete a project in the app to remove its runs, screenshots and feedback. To remove your account, email us and we will do it."],
    ],
  },
  terms: {
    title: "Terms of Service",
    intro:
      "These terms govern your use of Launch Crew. They are short on purpose: what you own, what we ask of you, and what you should expect from generated output.",
    points: [
      ["Your content", "You keep the rights to the ideas you submit and the pages generated in your workspace. You are responsible for what you publish."],
      ["Automated output", "Agent pages are drafts. They pass automated checks and a critic review, but you approve what goes live — readiness scores are guidance, not a warranty."],
      ["Acceptable use", "Do not use the product to publish deceptive, harmful, or infringing content, or to probe or overload the service."],
      ["Your account", "Keep your credentials safe, one person per account. We may suspend accounts that breach these terms."],
      ["Changes and availability", "The service is provided as it is, without an uptime guarantee, and features may change as the product evolves."],
    ],
  },
  cookies: {
    title: "Cookie & Storage Policy",
    intro:
      "This application does not set advertising or tracking cookies. It uses a small amount of first-party browser storage so you stay signed in and keep your appearance choice.",
    points: [
      ["Session", "One storage key holds your authentication token so the app can restore your session on the next visit."],
      ["Appearance", "One storage key remembers light, dark, or system theme, and whether you finished the product tour."],
      ["No third-party trackers", "We do not embed advertising pixels, cross-site trackers, or marketing cookies."],
      ["Clearing it", "Sign out, or clear site data in your browser. Both remove local entries; clearing site data also signs you out."],
    ],
  },
};

export default function Legal() {
  const { slug } = useParams();
  const doc = DOCS[slug] || DOCS.privacy;
  return (
    <section className="section legal-page">
      <p className="muted small back"><Link to="/"><Icon name="left" size={13} /> Back to home</Link></p>
      <h1>{doc.title}</h1>
      <p className="lead-copy">{doc.intro}</p>
      <div className="legal-grid">
        {doc.points.map(([head, body]) => (
          <div key={head} className="legal-item">
            <h3>{head}</h3>
            <p className="muted">{body}</p>
          </div>
        ))}
      </div>
      <p className="muted small">Last updated: {UPDATED}. Questions? Email <a href="mailto:hello@launchcrew.app">hello@launchcrew.app</a>.</p>
      <p className="small"><Link to="/about">About Launch Crew <Icon name="arrowRight" size={14} /></Link></p>
    </section>
  );
}
