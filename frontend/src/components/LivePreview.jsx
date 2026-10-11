import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL, api } from "../api";
import AiWorking from "./AiWorking";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import Icon from "./Icon";
import { useToast } from "../toast";

/** Viewports the page can be measured in. Widths match the ones the Chromium pass uses. */
const VIEWPORTS = [
  { id: "desktop", label: "Desktop", width: "100%", note: "1280 wide" },
  { id: "tablet", label: "Tablet", width: "768px", note: "768 wide" },
  { id: "mobile", label: "Mobile", width: "375px", note: "375 wide, like the audit" },
];

const MAX_LINES = 40;
const CHANNEL_TIMEOUT_MS = 3000;

/* The bounds the frame applies to a selection. They are the ones the server applies in
   `visual_edit.describe` (16 classes, 12 attribute pairs, clipped text), so what the page reports and what
   the source mapping compares against are the same shape - which is what makes `matches` and `index`
   countable on both sides instead of merely similar. */
const SEL_CLASSES = 16, SEL_ATTRS = 12, SEL_TEXT = 400, SEL_PATH = 200;

/* Runs inside the sandboxed frame and reports what really happened there back to this app over postMessage.
   It is added at render time, never written to the published file, and the page it observes keeps its own
   opaque origin - so it can report errors without being able to read anything of ours. */
const PROBE = [
  "<script>(function(){var post=function(t,d){try{parent.postMessage(Object.assign({__lc_preview:t},d||{}),'*')}catch(e){}};",
  "window.addEventListener('error',function(e){post('error',{message:String((e&&e.message)||'Script error'),file:String((e&&e.filename)||'').slice(0,140),line:(e&&e.lineno)||0,col:(e&&e.colno)||0})},true);",
  "window.addEventListener('unhandledrejection',function(e){var r=e&&e.reason;post('error',{message:'Unhandled promise rejection: '+String((r&&r.message)||r||'').slice(0,200)})});",
  "['error','warn'].forEach(function(l){var f=console[l];console[l]=function(){var a=Array.prototype.slice.call(arguments).map(function(x){try{return typeof x==='object'?JSON.stringify(x).slice(0,180):String(x)}catch(e){return String(x)}}).join(' ').slice(0,280);post('console',{level:l,text:a});if(f)f.apply(console,arguments)}});",
  // ---- selection: one armed click reports the node the user meant, then the frame goes back to normal.
  "var sel=0,box=0,lab=0,ovl=0,last=0,clip=function(s,n){s=String(s==null?'':s).replace(/\\s+/g,' ').trim();return s.length>n?s.slice(0,n):s},",
  "probe=function(n){try{return!!(n&&n.closest&&n.closest('[data-lc-probe]'))}catch(e){return false}},",
  "skip=function(k){return k==='id'||k==='class'||k.indexOf('data-lc')===0},",
  `clsof=function(n){var o=[],c=n.classList||[];for(var i=0;i<c.length&&o.length<${SEL_CLASSES};i++){var x=String(c[i]);if(x&&o.indexOf(x)<0)o.push(x)}return o},`,
  `kyof=function(n){var o=[],a=n.attributes||[];for(var i=0;i<a.length&&o.length<${SEL_ATTRS};i++){var k=String(a[i].name).toLowerCase();if(!skip(k)&&o.indexOf(k)<0)o.push(k)}return o},`,
  "ident=function(n){return{tag:n.tagName.toLowerCase(),id:clip(n.getAttribute('id')||'',64),classes:clsof(n),keys:kyof(n)}},",
  "like=function(a,b){var s=function(x){return x.slice().sort().join('|')};",
  "return a.id?a.id===b.id:s(a.classes)===s(b.classes)&&s(a.keys)===s(b.keys)},",
  "group=function(n){var d=ident(n),all=document.getElementsByTagName(d.tag),m=0,at=-1;",
  "for(var i=0;i<all.length;i++){if(probe(all[i]))continue;if(like(d,ident(all[i]))){if(all[i]===n)at=m;m++}}return{matches:m,index:at}},",
  `shown=function(n){var t='',w=null;try{w=document.createTreeWalker(n,4,null,null)}catch(e){}if(w){var x;while((x=w.nextNode())){if(x.nodeValue)t+=' '+x.nodeValue}}else t=n.textContent||'';return clip(t,${SEL_TEXT})},`,
  `chain=function(n){var p=[],c=n,i=0;while(c&&c.tagName&&i<5){var d=ident(c);p.unshift(d.tag+(d.id?'#'+d.id:'')+(d.classes.length?'.'+d.classes.slice(0,2).join('.'):''));c=c.parentElement;i++}return clip(p.join(' > '),${SEL_PATH})},`,
  "tell=function(n){var d=ident(n),g=group(n),pairs=[],a=n.attributes||[];",
  "for(var i=0;i<a.length&&pairs.length<32;i++){var k=String(a[i].name).toLowerCase();if(skip(k))continue;pairs.push([k,clip(a[i].value,80)])}",
  "return{tag:d.tag,id:d.id,classes:d.classes,text:shown(n),attrs:pairs,index:g.index<0?null:g.index,matches:g.matches,path:chain(n)}};",
  "var paint=function(n){if(!sel||!n||!n.getBoundingClientRect)return;var r=n.getBoundingClientRect();",
  "if(r.width<1&&r.height<1)return;ovl.style.cssText='display:block;left:'+r.left+'px;top:'+r.top+'px;width:'+r.width+'px;height:'+r.height+'px';",
  "var d=ident(n);lab.textContent=clip(d.tag+(d.id?'#'+d.id:'')+(d.classes.length?'.'+d.classes[0]:''),70);",
  "lab.style.cssText='display:block;left:'+Math.max(2,Math.min(r.left,innerWidth-lab.offsetWidth-6))+'px;top:'+(r.top>20?r.top-18:Math.min(r.bottom+2,innerHeight-18))+'px'};",
  "var unhook=function(){[ovl,lab,box].forEach(function(e){if(e&&e.parentNode)e.parentNode.removeChild(e)});ovl=lab=box=last=null;",
  "try{document.documentElement.style.cursor=''}catch(e){}};",
  "var hook=function(){if(box)return;box=document.createElement('div');box.setAttribute('data-lc-probe','1');",
  "box.style.cssText='position:fixed;inset:0;z-index:2147483644;pointer-events:none;outline:1px dashed rgba(8,145,178,.55);outline-offset:-2px';",
  "try{document.documentElement.style.cursor='crosshair'}catch(e){}",
  "ovl=document.createElement('div');ovl.setAttribute('data-lc-probe','1');",
  "ovl.style.cssText='display:none;position:fixed;z-index:2147483645;pointer-events:none;border:2px solid #0891B2;background:rgba(8,145,178,.14);border-radius:3px';",
  "lab=document.createElement('div');lab.setAttribute('data-lc-probe','1');",
  "lab.style.cssText='display:none;position:fixed;z-index:2147483646;pointer-events:none;font:12px/1.4 ui-monospace,monospace;background:#0B1220;color:#F1F7FC;padding:2px 7px;border-radius:6px';",
  "var host=document.body||document.documentElement;if(!host)return;[box,ovl,lab].forEach(function(e){host.appendChild(e)})};",
  "var off=function(){if(!sel)return;sel=0;unhook();post('seloff',{})};",
  "window.addEventListener('message',function(e){var c=e.data&&e.data.__lc_preview_ctl;if(!c)return;if(c.select){sel=1;hook()}else off()});",
  "document.addEventListener('mouseover',function(e){if(sel){last=e.target;paint(e.target)}},true);",
  "['scroll','resize'].forEach(function(t){window.addEventListener(t,function(){if(sel&&last)paint(last)},true)});",
  "document.addEventListener('click',function(e){if(!sel)return;if(probe(e.target)||!e.target.tagName)return;e.preventDefault();e.stopPropagation();",
  "var el=tell(e.target);post('select',{element:el});off()},true);",
  "document.addEventListener('keydown',function(e){if(sel&&e.key==='Escape')off()},true);",
  "document.addEventListener('DOMContentLoaded',function(){post('ready',{nodes:document.getElementsByTagName('*').length,scripts:document.scripts.length})});",
  "window.addEventListener('load',function(){post('loaded',{title:String(document.title||'').slice(0,80)})});",
  "})();</script>",
].join("");

function withProbe(html) {
  if (!html) return html;
  const open = html.search(/<head[^>]*>/i);
  if (open < 0) return PROBE + html;
  const at = html.indexOf(">", open) + 1;
  return html.slice(0, at) + PROBE + html.slice(at);
}

const clip = (s, n) => {
  const t = String(s ?? "");
  return t.length > n ? `${t.slice(0, n)}…` : t;
};

/** The workspace's live preview: what the crew published, in a frame that cannot reach this app.
 *
 * `selecting`/`onSelect` are the visual editor's arm: this component tells the frame to watch for one
 * click, and the frame answers with the element it describes. Nothing is read out of the frame directly -
 * the page has an opaque origin, so the only thing that crosses is the report it posts.
 */
export default function LivePreview({ runId, version, working, selecting = false, onPickingChange, onSelect }) {
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [statusErr, setStatusErr] = useState("");
  const [html, setHtml] = useState("");
  const [mode, setMode] = useState("desktop");
  const [lines, setLines] = useState([]);
  const [channel, setChannel] = useState("idle");     // idle | probing | live | silent
  const [nonce, setNonce] = useState(0);              // bump to remount the frame: refresh without a rebuild
  const [busy, setBusy] = useState("");
  const [ticket, setTicket] = useState(null);
  const [ready, setReady] = useState(false);          // this frame's probe has reported back
  const frame = useRef(null);

  const load = useCallback(async () => {
    if (!runId) return;
    setStatusErr("");
    try {
      const [s, text] = await Promise.all([api.previewStatus(runId), api.fileText(runId, "index.html").catch(() => "")]);
      setStatus(s);
      setHtml(text);
      setLines([]);
      setChannel(s.preview.supported && text ? "probing" : "idle");
      setReady(false);
      setNonce((n) => n + 1);
    } catch (e) {
      setStatusErr(e.message);
      setStatus(null);
    }
  }, [runId]);

  useEffect(() => { load(); }, [load, version]);

  // An honest preview says when it heard nothing: silence is not the same as a clean page.
  useEffect(() => {
    if (channel !== "probing") return undefined;
    const t = setTimeout(() => setChannel((c) => (c === "probing" ? "silent" : c)), CHANNEL_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [channel, nonce]);

  const ctl = useCallback((select) => {
    frame.current?.contentWindow?.postMessage({ __lc_preview_ctl: { select } }, "*");
  }, []);

  // Only a boolean leaves this app, and only once the frame has proved it is listening.
  useEffect(() => { if (ready) ctl(selecting); }, [ready, selecting, ctl]);

  const disarm = useCallback(() => { ctl(false); onPickingChange?.(false); }, [ctl, onPickingChange]);

  useEffect(() => {
    if (!selecting) return undefined;
    const onKey = (e) => { if (e.key === "Escape") disarm(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selecting, disarm]);

  useEffect(() => {
    const onMessage = (e) => {
      if (!frame.current || e.source !== frame.current.contentWindow) return;
      const d = e.data;
      if (!d || typeof d !== "object" || !d.__lc_preview) return;
      if (d.__lc_preview === "ready" || d.__lc_preview === "loaded") { setChannel("live"); setReady(true); return; }
      if (d.__lc_preview === "select") { onSelect?.(d.element); return; }
      if (d.__lc_preview === "seloff") { onPickingChange?.(false); return; }
      const text = d.__lc_preview === "console"
        ? `${d.level === "warn" ? "console.warn" : "console.error"}: ${clip(d.text, 200)}`
        : `${clip(d.message, 180)}${d.file ? ` — ${clip(d.file, 60)}:${d.line || 0}` : ""}`;
      setLines((prev) => {
        if (prev.some((l) => l.text === text)) return prev;
        const kind = d.__lc_preview === "console" && d.level === "warn" ? "warn" : "error";
        return [{ at: new Date().toLocaleTimeString(), kind, text }, ...prev].slice(0, MAX_LINES);
      });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [onSelect, onPickingChange]);

  const open = async () => {
    setBusy("link");
    try {
      const s = await api.previewStart(runId);
      setTicket(s.ticket);
      setStatus(s);
      window.open(`${API_URL}${s.ticket.path}`, "_blank", "noopener,noreferrer");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const stop = async () => {
    setBusy("stop");
    try {
      const r = await api.previewStop(runId);
      setTicket(null);
      toast(r.revoked ? `Revoked ${r.revoked} preview link(s)` : "There were no live links to revoke", "success");
      setStatus(await api.previewStatus(runId));
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const copy = async () => {
    try { await navigator.clipboard.writeText(`${API_URL}${ticket.path}`); toast("Preview link copied", "success"); }
    catch { toast("Your browser blocked the clipboard", "error"); }
  };

  const build = status?.build;
  const preview = status?.preview;
  const failed = useMemo(() => (build?.failed || []).map((c) => ({
    at: c.viewport, kind: c.severity === "warning" ? "warn" : "error",
    text: `${c.label}${c.detail ? ` — ${clip(c.detail, 160)}` : ""}`,
  })), [build]);
  const runtimeErrors = lines.filter((l) => l.kind === "error").length;

  if (statusErr && !status) return <ErrorState title="Couldn't read the preview" message={statusErr} retry={load} />;
  if (!status) return <div className="card"><AiWorking label="Reading the published page…" /></div>;
  if (!preview.supported) {
    return (
      <div className="card">
        <EmptyState icon={preview.kind === "needs-build" ? "cpu" : "monitor"}
          title={preview.kind === "needs-build" ? "This build cannot run here" : "Nothing to preview yet"}
          text={preview.reason} />
        {!!preview.blocked?.length && (
          <div className="row wrap" style={{ marginTop: 10 }}>
            {preview.blocked.map((f) => <span key={f} className="pill warn mono">{f}</span>)}
          </div>
        )}
        <p className="muted small" style={{ marginTop: 10 }}>No placeholder page is shown for a build this
          environment cannot run. Files: {status.files.map((f) => f.name).join(", ") || "none"}.</p>
      </div>
    );
  }

  return (
    <div className="card stack">
      <div className="row between wrap">
        <h2>Live preview</h2>
        <div className="row wrap">
          <button className={`btn small ${selecting ? "" : "ghost"}`}
            onClick={() => (selecting ? disarm() : onPickingChange?.(true))}
            disabled={!ready || working}
            title={selecting ? "Press Escape to stop selecting"
              : !ready ? "The page has not reported back yet, so a click cannot be captured"
              : working ? "The crew is rebuilding this page right now"
              : "Click any element in the page to edit it"}>
            <Icon name="target" size={15} /> {selecting ? "Click an element…" : "Select element"}
          </button>
          <button className="btn ghost small" onClick={load} disabled={busy === "link"}>
            <Icon name="refresh" size={15} /> Refresh
          </button>
          <button className="btn ghost small" onClick={open} disabled={!!busy}>
            <Icon name="link" size={15} /> {busy === "link" ? "Opening…" : "Open in new tab"}
          </button>
          {!!status.tickets?.active && (
            <button className="btn ghost small" onClick={stop} disabled={!!busy}>
              <Icon name="close" size={15} /> {busy === "stop" ? "Revoking…" : `Stop ${status.tickets.active} link(s)`}
            </button>
          )}
          <div className="seg" role="group" aria-label="Viewport">
            {VIEWPORTS.map((v) => (
              <button key={v.id} className={mode === v.id ? "on" : ""} onClick={() => setMode(v.id)} title={v.note}>
                {v.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="row wrap">
        <span className="pill">page v{status.version}</span>
        <span className={`pill ${status.status === "running" || working ? "warn" : ""}`}>
          {status.status.replace(/_/g, " ")}
        </span>
        <span className="pill">{Math.max(1, Math.round((status.page?.bytes || 0) / 1024))} KB</span>
        <span className="pill">{VIEWPORTS.find((v) => v.id === mode).note}</span>
        <span className={`pill ${build.errors ? "err" : "ok"}`}>{build.errors} build error(s)</span>
        <span className={`pill ${runtimeErrors ? "err" : channel === "silent" ? "warn" : "ok"}`}>
          {channel === "silent" ? "runtime channel silent" : `${runtimeErrors} runtime error(s)`}
        </span>
        {build.warnings > 0 && <span className="pill warn">{build.warnings} warning(s)</span>}
        {typeof build.readiness === "number" && <span className="pill">readiness {build.readiness}</span>}
      </div>

      <p className="muted small">Refresh re-reads the published file — it never restarts the crew or spends
        tokens, so a change you applied is visible the moment it is published. The frame is sandboxed with no
        same-origin access, so this page cannot read your login, cookies or the app's API. “Open in new tab”
        hands out a link that carries its own expiring token{ticket ? ` (live for ${Math.round(ticket.expires_in / 60)} min)` : ""}
        and is served with <code className="inline-code">Content-Security-Policy: sandbox</code>. “Select element”
        arms the same one-way channel: the page posts back the node you clicked and nothing else crosses, so a
        generated page cannot reach this app in either direction.</p>

      <div className="frame-wrap">
        <iframe key={nonce} ref={frame} title="Live preview" sandbox="allow-scripts"
          srcDoc={withProbe(html)} className={`frame ${mode}`} />
      </div>

      <section className="stack">
        <div className="row between wrap">
          <h3>Preview console</h3>
          <span className={`pill ${channel === "live" ? "ok" : channel === "silent" ? "warn" : ""}`}>
            {channel === "live" ? "runtime channel reporting"
              : channel === "silent" ? "no report from the page"
              : channel === "probing" ? "waiting for the page…" : "channel idle"}
          </span>
        </div>
        <ul className="console-list">
          {lines.map((l, i) => (
            <li key={`${l.at}-${i}`} className={`console-line ${l.kind}`}>
              <span className="console-when">{l.at}</span><span>{l.text}</span>
            </li>
          ))}
          {!lines.length && !failed.length && (
            <li className="console-line ok">
              <span className="console-when">build</span>
              <span>{channel === "silent"
                ? "The Chromium pass found nothing and the frame reported nothing back, so treat this as unmeasured rather than clean."
                : `All ${build.checks} automated checks passed and the page reported no runtime errors.`}</span>
            </li>
          )}
          {failed.map((f, i) => (
            <li key={`b-${i}`} className={`console-line ${f.kind === "warn" ? "warn" : "error"}`}>
              <span className="console-when">check · {f.at}</span><span>{f.text}</span>
            </li>
          ))}
        </ul>
        {!!build.sanitizer_violations?.length && (
          <p className="muted small">Removed while building this page: {build.sanitizer_violations.join(" · ")}</p>
        )}
      </section>
    </div>
  );
}
