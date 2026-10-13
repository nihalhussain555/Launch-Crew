import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as monaco from "monaco-editor";
// Workers are bundled from the installed monaco-editor package: no CDN, no network at runtime.
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import CssWorker from "monaco-editor/language/css/css.worker.js?worker";
import HtmlWorker from "monaco-editor/language/html/html.worker.js?worker";
import JsonWorker from "monaco-editor/language/json/json.worker.js?worker";
import TsWorker from "monaco-editor/language/typescript/ts.worker.js?worker";

let workersInstalled = false;
function installWorkers() {
  if (workersInstalled) return;
  workersInstalled = true;
  window.MonacoEnvironment = {
    getWorker(_id, label) {
      if (label === "json") return new JsonWorker();
      if (label === "css" || label === "scss" || label === "less") return new CssWorker();
      if (label === "html" || label === "handlebars" || label === "pug") return new HtmlWorker();
      if (label === "typescript" || label === "javascript") return new TsWorker();
      return new EditorWorker();
    },
  };
}

// The workspace's own language ids, as codebase_index.language_of() reports them.
const LANG = { html: "html", htm: "html", css: "css", js: "javascript", mjs: "javascript",
  md: "markdown", markdown: "markdown", py: "python", json: "json", sql: "sql", text: "plaintext" };
const langOf = (l) => LANG[(l || "").toLowerCase()] || "plaintext";

// Editor colours come from the app palette, so the IDE is the same product in the same theme.
const PALETTE = {
  light: { base: "vs", bg: "#FFFFFF", fg: "#0B1220", line: "#607084", sel: "#0891B222",
    edge: "#DCE6EF", caret: "#0891B2", find: "#6366F122", findMatch: "#0891B233" },
  dark: { base: "vs-dark", bg: "#0E1626", fg: "#F1F7FC", line: "#8FA3B8", sel: "#22D3EE22",
    edge: "#1E3045", caret: "#22D3EE", find: "#818CF822", findMatch: "#22D3EE33" },
};
let themesDefined = false;
function defineThemes() {
  if (themesDefined) return;
  themesDefined = true;
  Object.entries(PALETTE).forEach(([name, p]) => monaco.editor.defineTheme(`launch-crew-${name}`, {
    base: p.base, inherit: true, rules: [], colors: {
      "editor.background": p.bg, "editor.foreground": p.fg, "editorLineNumber.foreground": p.line,
      "editor.selectionBackground": p.sel, "editor.lineHighlightBackground": `${p.edge}55`,
      "editorWidget.background": p.bg, "editorWidget.border": p.edge, "editorSuggestWidget.background": p.bg,
      "editorSuggestWidget.border": p.edge, "editor.findMatchBackground": p.findMatch,
      "editor.findMatchHighlightBackground": p.find, "editorCursor.foreground": p.caret,
    },
  }));
}

const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const uriOf = (name) => monaco.Uri.parse(`inmemory://launch-crew/${encodeURIComponent(name)}`);

/**
 * One Monaco instance holding one model per open tab, exactly like an IDE editor: switching tabs keeps
 * each file's undo stack, cursor and selections, and closing a tab disposes its model.
 *
 * The text lives in the models, not in React state - a keystroke must not re-render the shell. The parent
 * asks for a model's contents when it saves and is told when a tab flips between clean and dirty.
 */
const MonacoEditor = forwardRef(function MonacoEditor({ tabs, active, theme, prefs, onDirty, onSave, onMarkers, onCursor }, ref) {
  const host = useRef(null);
  const editor = useRef(null);
  const views = useRef(new Map());     // name -> {model, saved, viewState}
  const saved = useRef(new Map());     // name -> the text last read from or written to the server
  const dirty = useRef(new Map());     // name -> the flag the parent already has
  const onSaveRef = useRef(onSave);
  const onDirtyRef = useRef(onDirty);
  const onMarkersRef = useRef(onMarkers);
  const onCursorRef = useRef(onCursor);
  onSaveRef.current = onSave; onDirtyRef.current = onDirty;
  onMarkersRef.current = onMarkers; onCursorRef.current = onCursor;

  useImperativeHandle(ref, () => ({
    text: (name) => views.current.get(name)?.model.getValue() ?? "",
    selection: () => {
      const m = editor.current?.getModel();
      const sel = editor.current?.getSelection();
      return m && sel && !sel.isEmpty() ? m.getValueInRange(sel) : "";
    },
    focus: () => editor.current?.focus(),
    find: () => editor.current?.getAction("actions.find")?.run(),
    replace: () => editor.current?.getAction("editor.action.startFindReplaceAction")?.run(),
    reveal: (line, column = 1) => {
      editor.current?.revealLineInCenterIfOutsideViewport(line);
      editor.current?.setPosition({ lineNumber: line, column });
      editor.current?.focus();
    },
    layout: () => editor.current?.layout(),
    /** Re-read after the server moved the file (a crew rebuild, a restore, a patch): a tab the user has
     *  not edited follows the server; an edited one keeps its edits and stays dirty. */
    reset: (name, text) => {
      const v = views.current.get(name);
      if (!v) return false;
      saved.current.set(name, text);
      if (v.model.getValue() !== text) {
        v.model.setValue(text);
        dirty.current.set(name, false);
        onDirtyRef.current?.(name, false);
      }
      return true;
    },
    isDirty: (name) => dirty.current.get(name) === true,
  }));

  useEffect(() => {
    installWorkers(); defineThemes();
    const e = monaco.editor.create(host.current, {
      value: "", theme: `launch-crew-${theme === "dark" ? "dark" : "light"}`,
      automaticLayout: true, fontSize: 13.5, fontFamily: 'ui-monospace,"Cascadia Mono","JetBrains Mono",Menlo,Consolas,monospace',
      minimap: { enabled: false }, glyphMargin: false, smoothScrolling: !reduced(),
      automaticSimplify: false, scrollBeyondLastLine: false, renderWhitespace: "selection",
      bracketPairColorization: { enabled: true }, links: true, contextmenu: true,
      quickSuggestions: { other: true, comments: false, strings: false },
      padding: { top: 10, bottom: 10 }, wordWrap: "off",
    });
    editor.current = e;
    // Ctrl+S inside the editor means "save this workspace file through the API", not "download a page".
    e.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => onSaveRef.current?.());
    e.onDidChangeCursorPosition((ev) => {
      const m = e.getModel();
      if (!m) return;
      onCursorRef.current?.({ name: nameOf(m.uri), line: ev.position.lineNumber, column: ev.position.column });
    });
    const markerSub = monaco.editor.onDidChangeMarkers((uris) => uris.forEach((u) => {
      const name = nameOf(u);
      onMarkersRef.current?.(name, monaco.editor.getModelMarkers({ resource: u }));
    }));
    return () => { markerSub.dispose(); views.current.forEach((v) => v.model.dispose());
      views.current.clear(); e.dispose(); editor.current = null; };
  }, []);                                     // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { monaco.editor.setTheme(`launch-crew-${theme === "dark" ? "dark" : "light"}`); }, [theme]);

  useEffect(() => {
    editor.current?.updateOptions({
      fontSize: prefs?.fontSize || 13.5,
      wordWrap: prefs?.wordWrap ? "on" : "off",
      minimap: { enabled: !!prefs?.minimap },
    });
  }, [prefs]);

  useEffect(() => {
    const e = editor.current;
    if (!e) return;
    const wanted = new Map(tabs.map((t) => [t.name, t]));
    views.current.forEach((v, name) => {
      if (wanted.has(name)) return;
      v.model.dispose(); views.current.delete(name); saved.current.delete(name); dirty.current.delete(name);
    });
    wanted.forEach((t, name) => {
      if (views.current.has(name)) return;
      const uri = uriOf(name);
      const existing = monaco.editor.getModel(uri);
      const model = existing || monaco.editor.createModel(t.text, langOf(t.language), uri);
      if (existing && existing.getValue() !== t.text) { saved.current.set(name, t.text); existing.setValue(t.text); }
      else saved.current.set(name, t.text);
      dirty.current.set(name, false);
      model.onDidChangeContent(() => {
        const is = model.getValue() !== saved.current.get(name);
        if (dirty.current.get(name) !== is) { dirty.current.set(name, is); onDirtyRef.current?.(name, is); }
      });
      views.current.set(name, { model, viewState: null });
    });
    const view = views.current.get(active);
    const spec = wanted.get(active);
    const current = e.getModel();
    if (current && current.uri !== uriOf(active)) {
      const prev = views.current.get(nameOf(current.uri));
      if (prev) prev.viewState = e.saveViewState();
    }
    if (view && (!current || current.uri !== uriOf(active))) {
      e.setModel(view.model);
      if (view.viewState) e.restoreViewState(view.viewState);
    }
    e.updateOptions({ readOnly: !(spec && spec.editable) });
  }, [tabs, active]);

  return <div className="ide-monaco" ref={host} aria-label="Code editor" />;
});

function nameOf(uri) {
  try { return decodeURIComponent(uri.path.replace(/^\//, "")); } catch { return uri.path.replace(/^\//, ""); }
}

export default MonacoEditor;
