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


def align(old: str, new: str, context: int = 3) -> dict:
    """Side-by-side rows: one entry per aligned pair, so a change reads in place instead of stacked.

    `rows` pairs the lines that `diff` interleaves. A replace block lines its deletions up with its
    insertions and marks the pair 'chg'; the surplus of the longer side stands alone with the other
    side `None`. Equal runs keep `context` lines either side of a change and fold the rest into one
    'gap' row, so the view stays the size of the edit rather than the size of the file.
    """
    a, b = readable(old), readable(new)
    if a == b:
        return {"rows": [], "added": 0, "removed": 0, "changed": False,
                "left_lines": len(a), "right_lines": len(b)}
    rows: list[dict] = []
    added = removed = 0

    def push(kind: str, lno: int, rno: int) -> None:
        rows.append({"kind": kind,
                     "l": None if not lno else {"n": lno, "text": a[lno - 1]},
                     "r": None if not rno else {"n": rno, "text": b[rno - 1]}})

    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            n = i2 - i1
            hidden = _hidden(n, context)
            if not hidden:
                for k in range(n):
                    push("ctx", i1 + k + 1, j1 + k + 1)
            else:
                for k in list(range(context)) + [None] + list(range(n - context, n)):
                    if k is None:
                        push("gap", 0, 0)
                        rows[-1]["lines"] = hidden
                    else:
                        push("ctx", i1 + k + 1, j1 + k + 1)
        elif op == "insert":
            for k in range(j2 - j1):
                push("add", 0, j1 + k + 1)
                added += 1
        elif op == "delete":
            for k in range(i2 - i1):
                push("del", i1 + k + 1, 0)
                removed += 1
        else:  # replace: a paired line counts as one removed and one added, as in a unified diff
            left, right = i2 - i1, j2 - j1
            for k in range(max(left, right)):
                lno, rno = (i1 + k + 1 if k < left else 0), (j1 + k + 1 if k < right else 0)
                push("chg" if lno and rno else ("del" if lno else "add"), lno, rno)
                added += 1 if rno else 0
                removed += 1 if lno else 0
    return {"rows": rows, "added": added, "removed": removed, "changed": bool(added or removed),
            "left_lines": len(a), "right_lines": len(b)}


def _hidden(n: int, context: int) -> int:
    """How many lines of an equal run are folded away: everything past the context either side."""
    return max(n - 2 * context, 0)


MAX_ROWS = 60


def compare(old: str, new: str, old_label: str, new_label: str, max_rows: int = MAX_ROWS) -> dict:
    """One change, both ways of reading it: the interleaved unified rows and the aligned pair.

    The two views are counted from the same lines, so a reviewer who switches between them sees the
    same additions and deletions - only the shape of the answer changes.
    """
    d, side = diff(old, new, old_label, new_label), align(old, new)
    rows, side_rows = d["rows"][:max_rows], side["rows"][:max_rows]
    return {"added": d["added"], "removed": d["removed"], "changed": d["changed"],
            "rows": rows, "side": side_rows,
            "left_lines": side["left_lines"], "right_lines": side["right_lines"],
            "truncated": len(d["rows"]) > max_rows or len(side["rows"]) > max_rows}
