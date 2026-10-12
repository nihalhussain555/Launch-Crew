"""Theme editing on a live run: pick a theme, read the token patch it means, apply it through the crew's pipeline.

Three routes and no model call. `/preview` is free: it answers "what would this theme draw on this page?"
without recording anything. `/propose` plans the one `:root` edit, proves it still matches the page,
measures its impact and diffs it - and writes nothing. `/apply` hands that same verified patch to the
workspace pipeline, so a theme change gets the checkpoint before it, the sanitizer and the Chromium checks
after it, and history that records it as a theme edit attributed to the proposal.

The patch is a token edit, not an element edit: changing `--radius` or `--bg` reaches every component that
reads them, which is why the whole site can move with one small diff. When the page's CSS does not read
the tokens this theme changes, the route says so and refuses rather than writing declarations nothing
looks at - a change that does nothing is the worst kind of success message.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents import theme as design_theme, variants
from app.api.routes_runs import own_run
from app.api.routes_themes import _validate_colors, _validate_controls
from app.api.routes_workspace import BUSY, _ctx, _diff_pair, _fail
from app.core.deps import get_current_user, get_db, get_settings_dep
from app.db.models import RunOut, oid, run_out
from app.orchestrator import runner
from app.services import change_impact, theme_edit, workspace_manager
from app.services.workspace_manager import WorkspaceError

router = APIRouter(prefix="/api/runs/{run_id}/theme", tags=["theme editor"])

MAX_REQUEST_CHARS = 300


class ThemeProposeIn(BaseModel):
    """The controls to draw the page in, plus the version the customizer was looking at.

    `theme` is a theme's control set (family, mode, colours, pairing, scale, density, width, radius,
    shadow, button, card) - the same shape `POST /api/themes` takes, so a saved theme's controls can be
    sent straight back here.
    """
    theme: dict = Field(default_factory=dict)
    request: str = Field(default="", max_length=MAX_REQUEST_CHARS)
    base_version: int | None = None


class ProposalIn(BaseModel):
    """Which proposal, and the version the reviewer was looking at when they read it."""
    id: str = Field(min_length=1, max_length=12)
    reason: str = Field(default="", max_length=200)
    base_version: int | None = None


class RequestIn(BaseModel):
    """A whole-site appearance ask in the user's own words."""
    request: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)
    base_version: int | None = None


def _settled(controls: dict) -> dict:
    """Validate what the client sent, then resolve it into a complete theme.

    Validation runs on the input rather than the outcome: a slot holding `sea blue` is the user's
    mistake and has to be a 422, while a colour that resolves had to move for contrast is a note - and
    a control name the registry has never heard of is a 422 too, because the patch must say which
    corners, shadows and density the reviewer actually chose.
    """
    _validate_colors(controls)
    _validate_controls(controls)
    return design_theme.resolve(controls)


def _redrawn(ctx, resolved: dict) -> dict:
    """This run's design in the new theme - the direction a theme edit both patches and stores.

    Raises the reason a themed rebuild is impossible (a legacy run with no registry style behind it) as
    the HTTP-shaped error the routes already know how to report.
    """
    try:
        return variants.retheme(variants.from_dict(ctx.state.style), design_theme.as_stored(resolved),
                                color=(ctx.state.spec or {}).get("color", ""))
    except ValueError as exc:
        raise WorkspaceError(str(exc), 409) from exc


async def _texts(ctx) -> dict:
    texts = await workspace_manager.load_texts(ctx)
    texts.setdefault("index.html", ctx.state.html)
    return texts


@router.get("")
async def theme_status(run_id: str, db=Depends(get_db), settings=Depends(get_settings_dep),
                       user=Depends(get_current_user)):
    """The run's theme, the proposals made against it, and what the customizer is allowed to do."""
    run = await own_run(db, run_id, user)
    state = run.get("state", {})
    entries = state.get("theme_edits") or []
    return {"status": run["status"], "proposals": entries[::-1], **theme_edit.status_of(state),
            "busy": run["status"] in BUSY,
            "limits": {"max_proposals": theme_edit.MAX_THEME_PROPOSALS,
                       "revisions_left": max(settings.max_revisions - state.get("revisions", 0), 0)}}


@router.post("/preview")
async def preview(run_id: str, body: ThemeProposeIn, request: Request, db=Depends(get_db),
                  user=Depends(get_current_user)):
    """What these controls would write on this page: the values, the properties reached, the ones left out.

    Free and side-effectless. It is the call the swatches make while the user drags them, so the panel
    can say "this theme moves 34 properties here" before anything is offered for review.
    """
    ctx = await _ctx(request, db, run_id, user)
    try:
        workspace_manager.check_base(ctx.state, body.base_version)
        resolved = _settled(body.theme)
        direction = _redrawn(ctx, resolved)
        texts = await _texts(ctx)
        measured = theme_edit.coverage(texts, direction)
    except WorkspaceError as exc:
        _fail(exc)
    return {"theme": resolved, "tokens": resolved["tokens"], "fonts": resolved["fonts"],
            "palette": resolved["palette"], "scale": resolved["scale"], "width": resolved["width"],
            "radius": resolved["radius"], "summary": design_theme.describe(resolved),
            "has_token_block": measured["has_block"], "variables": measured["wants"],
            "declared": measured["declared"], "reached": measured["reached"],
            "unreached": measured["unreached"][:theme_edit.MAX_UNREACHED_SHOWN],
            "contrast": resolved["contrast"], "notes": resolved["notes"]}


@router.post("/from-request")
async def from_request(run_id: str, body: RequestIn, request: Request, db=Depends(get_db),
                       user=Depends(get_current_user)):
    """What the user's own words mean as a theme: words -> controls -> what they would reach here.

    The bridge the visual editor needs for a site-wide ask ("make the entire site look more premium"), and
    it costs no model call: `theme.request_to_controls` reads a fixed vocabulary of appearance words and
    returns the controls they name, which are then merged onto the theme this run already carries so an ask
    about corners does not reset its colours. Nothing is invented to answer a sentence - a request the
    vocabulary does not know is refused with the words that do work, because picking a theme at random and
    calling it "premium" is exactly the kind of success message this system is not allowed to print.
    """
    ctx = await _ctx(request, db, run_id, user)
    try:
        workspace_manager.check_base(ctx.state, body.base_version)
    except WorkspaceError as exc:
        _fail(exc)
    ask = design_theme.request_to_controls(body.request)
    if not ask["matched"]:
        declined = " ".join(d["reason"] for d in ask["declined"])
        raise HTTPException(422, (declined + " " if declined else "") +
                            f"Nothing in “{body.request[:120]}” names an appearance this customizer can change. "
                            f"Try one of: {', '.join(design_theme.REQUEST_WORD_HINTS)}.")
    merged = {**(theme_edit.status_of(ctx.state)["theme"] or design_theme.as_stored(design_theme.resolve({}))),
              **ask["controls"]}
    try:
        resolved = _settled(merged)
        direction = _redrawn(ctx, resolved)
        texts = await _texts(ctx)
        measured = theme_edit.coverage(texts, direction)
    except WorkspaceError as exc:
        _fail(exc)
    return {"request": body.request, "controls": design_theme.as_stored(resolved),
            "matched": ask["mapping"], "resets": ask["resets"], "conflicts": ask["conflicts"],
            "declined": ask["declined"],
            "theme": resolved, "tokens": resolved["tokens"], "palette": resolved["palette"],
            "summary": design_theme.describe(resolved), "has_token_block": measured["has_block"],
            "variables": measured["wants"], "declared": measured["declared"],
            "reached": measured["reached"], "unreached": measured["unreached"][:theme_edit.MAX_UNREACHED_SHOWN],
            "contrast": resolved["contrast"], "notes": resolved["notes"]}


@router.post("/propose")
async def propose(run_id: str, body: ThemeProposeIn, request: Request, db=Depends(get_db),
                  settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """One token patch for the whole page, reviewed before anything is written.

    Costs no tokens - the patch is computed from the theme, not asked of a model - and changes nothing:
    the edit is verified against the file it names, measured for impact, diffed and recorded as a
    proposal. The revision cap is checked here too, because a run that cannot apply a change should not
    fill its history with proposals it cannot honour.
    """
    ctx = await _ctx(request, db, run_id, user)
    if ctx.state.revisions >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve "
                                 f"this version or start a new run before asking for another theme.")
    try:
        workspace_manager.check_base(ctx.state, body.base_version)
        resolved = _settled(body.theme)
        direction = _redrawn(ctx, resolved)
        texts = await _texts(ctx)
        planned = theme_edit.plan(texts, direction)
        ask = (body.request or design_theme.describe(resolved))[:MAX_REQUEST_CHARS]
        index = workspace_manager.index_texts(texts, version=ctx.state.html_version)
        report = change_impact.analyze(index, ask, version=ctx.state.html_version)
        ctx.state.impact = report
        before, after, _page = await workspace_manager.prepare_changes(ctx, planned["changes"])
    except WorkspaceError as exc:
        _fail(exc)

    projection = workspace_manager.stats(before, after)
    diffs = {name: _diff_pair(before.get(name, ""), after.get(name, ""), f"before/{name}", f"after/{name}")
             for name in projection["changed"]}
    entry = theme_edit.record_proposal(ctx, request=ask, resolved=resolved, planned=planned, report=report)
    entry["lines_added"] = projection["lines_added"]
    entry["lines_removed"] = projection["lines_removed"]
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.theme_edits": ctx.state.theme_edits,
                                       "state.impact": ctx.state.impact, "updated_at": runner.now()}})
    return {"proposal": entry, "theme": resolved, "summary": design_theme.describe(resolved),
            "patch": planned["changes"][0], "diffs": diffs, "projection": projection,
            "replaced": planned["replaced"], "added": planned["added"], "kept": planned["kept"],
            "unreached": planned["unreached"], "reaches": planned["reaches"],
            "contrast": resolved["contrast"], "notes": resolved["notes"],
            "impact": report, "headline": change_impact.headline(report),
            "base_version": ctx.state.html_version, "undo": workspace_manager.undo_status(ctx.state),
            "safe_to_apply": not report["counts"]["errors"],
            "limits": {"max_proposals": theme_edit.MAX_THEME_PROPOSALS,
                       "revisions_left": max(settings.max_revisions - ctx.state.revisions, 0)}}


@router.post("/apply", response_model=RunOut, status_code=202)
async def apply_proposal(run_id: str, body: ProposalIn, request: Request, background: BackgroundTasks,
                         db=Depends(get_db), settings=Depends(get_settings_dep),
                         user=Depends(get_current_user)):
    """Apply a theme patch the user has read. Re-measured here: the block must still be the one proposed.

    The version guard and the token-block lookup both run again, because a proposal reviewed at v4 must
    not be applied over a page that has moved to v5, and a patch whose block has been rewritten is a
    different change than the one that was approved.
    """
    run = await own_run(db, run_id, user)
    if run.get("state", {}).get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve "
                                 f"this version or start a new run.")
    ctx = await _ctx(request, db, run_id, user)
    try:
        entry = theme_edit.find_proposal(ctx.state, body.id)
        if entry.get("status") != "proposed":
            raise WorkspaceError(f"Theme proposal {entry['id']} was already {entry.get('status')}. Ask "
                                 f"for a new one to change this page's theme again.", 409)
        workspace_manager.check_base(ctx.state, body.base_version)
        if entry.get("version") != ctx.state.html_version:
            raise WorkspaceError(f"Conflict: proposal {entry['id']} was read at v{entry.get('version')} "
                                 f"but the workspace is at v{ctx.state.html_version}. Preview the theme "
                                 f"again and re-request the change.", 409)
        theme_edit.recheck(entry["changes"], await _texts(ctx))
    except WorkspaceError as exc:
        _fail(exc)

    theme_edit.mark_proposal(entry, "applying")
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.theme_edits": ctx.state.theme_edits,
                                       "updated_at": runner.now()}})
    if not await runner.claim_for_revision(db, run_id, str(user["_id"])):
        theme_edit.mark_proposal(entry, "proposed")
        await db.runs.update_one({"_id": oid(run_id)},
                                 {"$set": {"state.theme_edits": ctx.state.theme_edits}})
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(runner.theme_apply_pipeline, request.app.state, run_id, entry["id"])
    return run_out(await own_run(db, run_id, user))


@router.post("/reject")
async def reject_proposal(run_id: str, body: ProposalIn, request: Request, db=Depends(get_db),
                          user=Depends(get_current_user)):
    """Turn a theme proposal down. Nothing is written to the workspace; the record says it was rejected."""
    run = await own_run(db, run_id, user)
    if run["status"] in BUSY:
        raise HTTPException(409, f"The crew is {run['status']} on this run right now. Reject the "
                                 f"proposal once it is back at the approval gate.")
    ctx = await _ctx(request, db, run_id, user)
    try:
        entry = theme_edit.find_proposal(ctx.state, body.id)
        if entry.get("status") != "proposed":
            raise WorkspaceError(f"Theme proposal {entry['id']} is already {entry.get('status')}.", 409)
        theme_edit.mark_proposal(entry, "rejected", reason=body.reason[:200])
    except WorkspaceError as exc:
        _fail(exc)
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.theme_edits": ctx.state.theme_edits,
                                       "updated_at": runner.now()}})
    return {"proposal": entry, "undo": workspace_manager.undo_status(ctx.state)}
