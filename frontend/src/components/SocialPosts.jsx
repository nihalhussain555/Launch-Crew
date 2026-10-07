import { useState } from "react";
import { copyText } from "../utils";

function Copy({ text }) {
  const [ok, setOk] = useState(false);
  return <button className="btn ghost small" onClick={async () => { if (await copyText(text)) { setOk(true); setTimeout(() => setOk(false), 1500); } }}>{ok ? "Copied" : "Copy"}</button>;
}

export default function SocialPosts({ posts, email }) {
  if (!posts?.length) return null;
  return (
    <section className="card">
      <h2>Launch kit</h2>
      {posts.map((p, i) => (
        <div className="post" key={i}>
          <div className="row between"><span className="pill">{p.platform}</span><Copy text={p.text} /></div>
          <p>{p.text}</p>
        </div>
      ))}
      {email && (
        <div className="post">
          <div className="row between"><span className="pill">Email</span><Copy text={`${email.subject}\n\n${email.body}`} /></div>
          <strong>{email.subject}</strong>
          <p style={{ whiteSpace: "pre-wrap" }}>{email.body}</p>
        </div>
      )}
    </section>
  );
}