"""Sample photography for the template gallery, carried inside the page as a `data:` URI.

The pages this product builds are single, self-contained HTML files: they are previewed in a sandboxed
`srcDoc` frame, downloaded, and deployed as one document. That has two consequences for imagery, and both
are deliberate rather than incidental:

* the shipped page's CSP is `img-src data:` and `app/tools/sanitizer.py` deletes any remote `<img src>`, so
  a hotlinked stock photo is stripped on the way through. Inlining is the only way a picture survives to the
  browser, and this module is where that decision is made once;
* inlined bytes are page weight. `app/tools/audit_perf.py` measures a page's markup and CSS separately
  from its photography and fails anything over 600 kB as one file, so `BUDGET_B` is the ceiling on how much
  photography one page may carry before the art falls back to the CSS treatment that was here first. The
  pages this builder writes measure 21-25 kB of text and CSS, and a fully illustrated template page lands
  around 125 kB.

What the art is allowed to depict is a separate question from what it is allowed to cost. Every file here is
generic subject matter - a device on a workbench, a plated dish, a concrete facade, a shelf of bottles - and
stands in for the owner's own photography, which is why the builder labels it. It is never a portrait: a
generated face on a "meet our surgeons" or "what our clients say" block would put an invented person forward
as a real one, which is the claim this product does not make about anyone's business. People slots are drawn
in CSS from the run's palette instead.

Files live in `app/assets/art/<template key>/<slot>-<width>x<height>.<ext>`. The dimensions are part of the
name on purpose: the builder needs them for the `width`/`height` attributes that keep the layout from
jumping, and reading them from the filename keeps Pillow out of the runtime dependencies.
"""
from __future__ import annotations

import base64
import functools
import re
from pathlib import Path

ART_DIR = Path(__file__).resolve().parent.parent / "assets" / "art"

# Base64 bytes of photography one page may carry in total, counted at its worst case, and per slot. The
# hero is the picture the demos are judged on, so it gets the budget; tiles are crops that fill a grid and
# are handed out round-robin, so the ceiling multiplies the largest one by the number of times it can
# appear. Pages measure 21-25 kB of text and CSS, which puts a fully illustrated template around 125 kB -
# under the workspace's own file ceiling and well under the point where one file stops being sensible.
BUDGET_B = 104 * 1024
HERO_MAX_B = 46 * 1024
TILE_MAX_B = 10 * 1024
MAX_TILES = 3
MAX_SHOTS = 6

_MIME = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_NAME = re.compile(r"^(?P<slot>[a-z0-9-]+)-(?P<w>\d{2,4})x(?P<h>\d{2,4})\.(?P<ext>webp|png|jpe?g)$")


def _slot(name: str) -> str:
    """`tile-2` sorts after `tile-1` and both after `hero`, which is the order the page fills them."""
    return name


@functools.lru_cache(maxsize=64)
def files_for(key: str) -> tuple[dict, ...]:
    """Every art file a template ships, in slot order, with its dimensions and encoded size.

    Missing directory, unreadable file or an unrecognised extension means no art for that slot - which is a
    normal state (the CSS treatment is the design, not a fallback error) and never an exception.
    """
    root = ART_DIR / key
    if not root.is_dir():
        return ()
    out = []
    for path in sorted(root.iterdir(), key=lambda p: _slot(p.stem)):
        m = _NAME.match(path.name)
        if not m or path.suffix.lower() not in _MIME:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        out.append({"slot": m["slot"], "w": int(m["w"]), "h": int(m["h"]),
                    "bytes": len(raw), "uri_len": ((len(raw) + 2) // 3) * 4,
                    "mime": _MIME[path.suffix.lower()], "path": path})
    return tuple(out)


def _shot_cost(tiles: list[dict]) -> int:
    """What the cards cost when the page fills `MAX_SHOTS` of them, tiles reused round-robin."""
    if not tiles:
        return 0
    return sum(tiles[i % len(tiles)]["uri_len"] for i in range(MAX_SHOTS))


@functools.lru_cache(maxsize=64)
def art_for(key: str) -> dict:
    """The pictures this page may carry, already cut to the budget.

    `hero` is the first file for the template, `tiles` the next few. A slot over its own ceiling is dropped
    rather than downscaled - silently shipping a worse picture than the file on disk would make the budget
    impossible to reason about, so the fix belongs in the file, not in the page.
    """
    found = files_for(key)
    hero = None
    tiles: list[dict] = []
    for entry in found:
        if entry["slot"] == "hero" and hero is None and entry["uri_len"] <= HERO_MAX_B:
            hero = entry
        elif entry["slot"].startswith("tile") and len(tiles) < MAX_TILES and entry["uri_len"] <= TILE_MAX_B:
            tiles.append(entry)
    hero_b = hero["uri_len"] if hero else 0
    while tiles and hero_b + _shot_cost(tiles) > BUDGET_B:
        tiles.pop()
    if hero_b + _shot_cost(tiles) > BUDGET_B:          # the hero on its own is over the page ceiling
        hero, hero_b = None, 0
    return {"hero": hero, "tiles": tiles, "shots": MAX_SHOTS,
            "bytes": hero_b + sum(e["uri_len"] for e in tiles)}


def data_uri(entry: dict | None) -> str:
    if not entry:
        return ""
    return f"data:{entry['mime']};base64," + base64.b64encode(entry["path"].read_bytes()).decode("ascii")


def has_art(key: str) -> bool:
    return bool(art_for(key)["hero"] or art_for(key)["tiles"])


def summary(key: str) -> dict:
    """What the gallery and the tests ask about: is there art, how much, and how many slots."""
    a = art_for(key)
    return {"art": bool(a["hero"] or a["tiles"]), "slots": len(a["tiles"]) + bool(a["hero"]),
            "bytes": a["bytes"]}


def reset_cache() -> None:
    """The tests write throwaway art into a temp directory; this stops one run seeing the last one's files."""
    files_for.cache_clear()
    art_for.cache_clear()
