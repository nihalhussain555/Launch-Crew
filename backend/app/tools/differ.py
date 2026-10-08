"""Git-style diffs between saved page versions.

Uses stdlib `difflib` only - no git binary and no dependency - and breaks markup onto lines
before comparing, because generated pages are dense: comparing them as raw single lines would
report "1 line changed" for a whole rewrite and be useless to read.
"""
import difflib
import re

_BREAK_AFTER_RE = re.compile(r">\s*<")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def readable(text: str) -> list[str]:
    """Split markup between tags so a change shows up as a handful of lines, not one giant one."""
    spaced = _BREAK_AFTER_RE.sub(">\n<", text or "")
    spaced = spaced.replace("\r\n", "\n").replace("\r", "\n")
    return [line for line in _BLANK_RUN_RE.sub("\n\n", spaced).split("\n") if line.strip()]


def diff(old: str, new: str, old_label: str, new_label: str, context: int = 3) -> dict:
    """Unified diff, ready to render: each line carries a kind of 'add', 'del', 'hunk' or 'ctx'."""
    a, b = readable(old), readable(new)
    rows, added, removed = [], 0, 0
    for line in difflib.unified_diff(a, b, fromfile=old_label, tofile=new_label, lineterm="", n=context):
        if line.startswith("@@"):
            rows.append({"kind": "hunk", "text": line})
        elif line.startswith("+++") or line.startswith("---"):
            continue                                   # labels live in the modal header
        elif line.startswith("+"):
            rows.append({"kind": "add", "text": line[1:]})
            added += 1
        elif line.startswith("-"):
            rows.append({"kind": "del", "text": line[1:]})
            removed += 1
        else:
            rows.append({"kind": "ctx", "text": line[1:] if line.startswith(" ") else line})
    return {"rows": rows, "added": added, "removed": removed, "changed": bool(added or removed)}


def stats(old: str, new: str) -> dict:
    a, b = readable(old), readable(new)
    matched = sum(block.size for block in difflib.SequenceMatcher(None, a, b).get_matching_blocks())
    return {"lines_added": max(len(b) - matched, 0), "lines_removed": max(len(a) - matched, 0),
            "same": a == b}
