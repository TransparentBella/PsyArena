from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal
import json
import mimetypes
import random
import time
import uuid

from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, load_settings
from app.db import (
    approve_user,
    audit,
    change_password,
    cleanup_expired_assignments,
    count_pending_users,
    connect,
    create_pending_user,
    create_session,
    delete_session,
    get_active_assignment,
    get_manifest_synced_at,
    get_user,
    get_user_by_session,
    get_user_inbox_state,
    init_db,
    insert_judgment,
    list_judged_match_ids,
    list_admin_messages,
    list_pending_users,
    mark_user_inbox_seen,
    reject_user,
    seed_admins,
    set_manifest_synced_at,
    sync_manifest,
    try_lock_assignment,
    verify_password,
)
from app.manifest import Manifest, Match, load_manifest
from app.schemas import (
    AdminMessageOut,
    AdminMessagesOut,
    ApproveIn,
    AuthMeOut,
    CommentaryOut,
    CommentaryWinStats,
    LoginIn,
    LoginOut,
    JudgmentIn,
    JudgmentOut,
    MatchOut,
    NextTaskResponse,
    PendingUserOut,
    PendingUsersOut,
    RankingItemOut,
    RegisterIn,
    RejectIn,
    ChangePasswordIn,
    StatsCounts,
    StatsMatchDetailResponse,
    StatsMatchItem,
    StatsMatchesResponse,
    StatsJudgmentOut,
    UserInboxOut,
    VideoOut,
)

ASSIGNMENT_TTL_SECONDS = 15 * 60  # soft lock window for an in-progress task


def _static_url(path: str) -> str:
    return f"/static/{path.lstrip('/')}"


def _read_text_payload(data_dir: Path, text_path: str) -> str | list[dict[str, Any]] | None:
    p = (data_dir / text_path).resolve()
    try:
        raw = p.read_text(encoding="utf-8")
    except Exception:
        return None
    stripped = raw.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            parsed = json.loads(raw)
            return parsed
        except Exception:
            return raw
    return raw


def _text_snapshot(data_dir: Path, text_path: str | None) -> str | None:
    if text_path is None or text_path.strip() == "":
        return None
    payload = _read_text_payload(data_dir, text_path)
    if payload is None:
        return None
    if isinstance(payload, str):
        s = payload.strip()
        return s[:300] if len(s) > 300 else s
    if isinstance(payload, list):
        parts: list[str] = []
        for seg in payload[:8]:
            if not isinstance(seg, dict):
                continue
            t_ms = seg.get("t_ms", seg.get("t", seg.get("time_ms", None)))
            text = seg.get("text", "")
            if t_ms is not None:
                parts.append(f"[{int(t_ms)}] {str(text)}")
            else:
                parts.append(str(text))
        s = "\n".join(parts).strip()
        return s[:600] if len(s) > 600 else s
    try:
        s = json.dumps(payload, ensure_ascii=False)
        return s[:300] if len(s) > 300 else s
    except Exception:
        return None


def _cover_url(settings: Settings, match: Match) -> str | None:
    cover = settings.data_dir / "matches" / match.match_id / "cover.jpg"
    if cover.exists():
        return _static_url(f"matches/{match.match_id}/cover.jpg")
    cover_png = settings.data_dir / "matches" / match.match_id / "cover.png"
    if cover_png.exists():
        return _static_url(f"matches/{match.match_id}/cover.png")
    return match.video.url or (_static_url(match.video.path) if match.video.path else None)


def _ranking_items(settings: Settings, manifest: Manifest, ranking_ids: list[str]) -> list[RankingItemOut]:
    items: list[RankingItemOut] = []
    for idx, cid in enumerate(ranking_ids):
        c = manifest.commentary_by_id.get(cid)
        items.append(
            RankingItemOut(
                rank=idx + 1,
                id=cid,
                source=(c.source if c else None),
                language=(c.language if c else None),
                type=(c.type if c else None),
                text_snapshot=_text_snapshot(settings.data_dir, (c.text.path if c and c.text else None)),
                audio_url_or_path=(
                    (c.audio.url if c and c.audio and c.audio.url else None)
                    or (c.audio.path if c and c.audio and c.audio.path else None)
                ),
            )
        )
    return items


def _compute_win_stats(judgments: list[list[str]], manifest: Manifest) -> list[dict[str, float | str | None]]:
    if not judgments:
        return []
    top1: dict[str, int] = {}
    rank_sum: dict[str, int] = {}
    appear: dict[str, int] = {}
    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    total_j = len(judgments)
    for ranking in judgments:
        for i, cid in enumerate(ranking):
            appear[cid] = appear.get(cid, 0) + 1
            rank_sum[cid] = rank_sum.get(cid, 0) + (i + 1)
            if i == 0:
                top1[cid] = top1.get(cid, 0) + 1
            for j in range(i + 1, len(ranking)):
                loser = ranking[j]
                wins[cid] = wins.get(cid, 0) + 1
                losses[loser] = losses.get(loser, 0) + 1
    rows: list[dict[str, float | str | None]] = []
    for cid, cnt in appear.items():
        denom = wins.get(cid, 0) + losses.get(cid, 0)
        c = manifest.commentary_by_id.get(cid)
        rows.append(
            {
                "id": cid,
                "source": (c.source if c else None),
                "top1_pct": (top1.get(cid, 0) / total_j * 100.0),
                "avg_rank": (rank_sum.get(cid, 0) / cnt),
                "pairwise_win_rate": (wins.get(cid, 0) / denom if denom > 0 else None),
            }
        )
    rows.sort(key=lambda r: (r["avg_rank"] if isinstance(r.get("avg_rank"), (int, float)) else 1e9))
    return rows


def _filter_commentaries(match: Match, mode: str) -> list:
    if mode == "both":
        return [c for c in match.commentaries if c.text and c.text.path]
    filtered = []
    for c in match.commentaries:
        if mode == "text" and c.text and c.text.path:
            filtered.append(c)
        elif mode == "audio" and c.audio and (c.audio.path or c.audio.url):
            filtered.append(c)
    return filtered


def create_app() -> FastAPI:
    app = FastAPI(title="CommentRanking API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        mimetypes.add_type("text/javascript", ".js")
        mimetypes.add_type("text/javascript", ".mjs")
        mimetypes.add_type("text/css", ".css")
        mimetypes.add_type("application/json", ".json")
        mimetypes.add_type("image/jpeg", ".jpg")
        mimetypes.add_type("image/png", ".png")
        mimetypes.add_type("video/mp4", ".mp4")
        mimetypes.add_type("audio/mp4", ".m4a")
        mimetypes.add_type("audio/wav", ".wav")
        mimetypes.add_type("audio/mpeg", ".mp3")

        settings = load_settings()
        app.state.settings = settings
        if not settings.manifest_path.exists():
            raise RuntimeError(f"manifest not found: {settings.manifest_path}")
        manifest = load_manifest(settings.manifest_path, settings.data_dir)
        app.state.manifest = manifest
        init_db(settings.db_path)
        with connect(settings.db_path) as conn:
            sync_manifest(conn, manifest)
            set_manifest_synced_at(conn, ts=int(time.time()))
            seed_admins(conn)
        if settings.data_dir.exists():
            app.mount("/static", StaticFiles(directory=str(settings.data_dir)), name="static")
        ui_dir = (Path(__file__).resolve().parents[1] / "ui").resolve()
        if ui_dir.exists():
            app.mount("/ui", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    def _require_loaded() -> tuple[Settings, Manifest]:
        settings: Settings | None = getattr(app.state, "settings", None)
        manifest: Manifest | None = getattr(app.state, "manifest", None)
        if settings is None or manifest is None:
            raise HTTPException(status_code=503, detail="service_not_ready")
        return settings, manifest

    def _current_user(session_token: str | None) -> dict[str, Any] | None:
        if session_token is None or session_token.strip() == "":
            return None
        settings, _ = _require_loaded()
        with connect(settings.db_path) as conn:
            row = get_user_by_session(conn, session_token)
        if row is None:
            return None
        return {
            "username": str(row["username"]),
            "nickname": str(row["nickname"]),
            "role": str(row["role"]),
            "status": str(row["status"]),
            "needs_password_reset": bool(int(row["needs_password_reset"])),
        }

    def _require_user(user: dict[str, Any] | None) -> dict[str, Any]:
        if user is None:
            raise HTTPException(status_code=401, detail="not_authenticated")
        if user["status"] != "active":
            raise HTTPException(status_code=403, detail="user_not_active")
        if user["needs_password_reset"]:
            raise HTTPException(status_code=403, detail="password_reset_required")
        return user

    def _require_labeler(user: dict[str, Any] | None) -> dict[str, Any]:
        u = _require_user(user)
        if u["role"] != "user":
            raise HTTPException(status_code=403, detail="labeler_only")
        return u

    def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
        u = _require_user(user)
        if u["role"] != "admin":
            raise HTTPException(status_code=403, detail="admin_only")
        return u

    @app.middleware("http")
    async def ui_auth_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path.startswith("/ui/"):
            is_asset = path.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".map"))
            is_public = path.startswith("/ui/login") or path.startswith("/ui/register")
            if not is_asset and not is_public:
                user = _current_user(request.cookies.get("cr_session"))
                if user is None:
                    return RedirectResponse(url="/ui/login/")
                if (path.startswith("/ui/stats") or path.startswith("/ui/admin")) and user.get("role") != "admin":
                    return RedirectResponse(url="/ui/")

            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            return response
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/auth/me", response_model=AuthMeOut)
    def auth_me(cr_session: str | None = Cookie(default=None)) -> AuthMeOut:
        user = _current_user(cr_session)
        if user is None:
            raise HTTPException(status_code=401, detail="not_authenticated")
        return AuthMeOut(
            username=user["username"],
            nickname=user["nickname"],
            role=user["role"],
            status=user["status"],
            needs_password_reset=bool(user["needs_password_reset"]),
        )

    @app.post("/api/auth/login", response_model=LoginOut)
    def auth_login(payload: LoginIn, response: Response) -> LoginOut:
        settings, _ = _require_loaded()
        username = payload.username.strip()
        password = payload.password
        if username == "" or password.strip() == "":
            time.sleep(0.6)
            raise HTTPException(status_code=400, detail="missing_credentials")
        with connect(settings.db_path) as conn:
            row = get_user(conn, username)
            if row is None:
                time.sleep(1.0)
                raise HTTPException(status_code=401, detail="invalid_credentials")
            if str(row["status"]) == "pending":
                raise HTTPException(status_code=403, detail="pending_approval")
            if str(row["status"]) != "active":
                raise HTTPException(status_code=403, detail="user_not_active")
            if not verify_password(password, str(row["password_hash"])):
                time.sleep(1.0)
                raise HTTPException(status_code=401, detail="invalid_credentials")

            token = create_session(conn, str(row["username"]))
        response.set_cookie(
            key="cr_session",
            value=token,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )
        return LoginOut(needs_password_reset=bool(int(row["needs_password_reset"])), role=str(row["role"]))

    @app.post("/api/auth/logout")
    def auth_logout(response: Response, cr_session: str | None = Cookie(default=None)) -> dict[str, bool]:
        settings, _ = _require_loaded()
        if cr_session:
            with connect(settings.db_path) as conn:
                delete_session(conn, cr_session)
        response.delete_cookie("cr_session", path="/")
        return {"ok": True}

    @app.post("/api/auth/register")
    def auth_register(payload: RegisterIn) -> dict[str, bool]:
        settings, _ = _require_loaded()
        nickname = payload.nickname.strip()
        if nickname == "" or payload.password.strip() == "":
            raise HTTPException(status_code=400, detail="missing_fields")
        with connect(settings.db_path) as conn:
            try:
                create_pending_user(conn, nickname, payload.password)
            except ValueError as e:
                raise HTTPException(status_code=409, detail=str(e))
        return {"ok": True}

    @app.post("/api/auth/change_password")
    def auth_change_password(payload: ChangePasswordIn, cr_session: str | None = Cookie(default=None)) -> dict[str, bool]:
        settings, _ = _require_loaded()
        user = _current_user(cr_session)
        if user is None:
            raise HTTPException(status_code=401, detail="not_authenticated")
        username = str(user["username"])
        with connect(settings.db_path) as conn:
            row = get_user(conn, username)
            if row is None:
                raise HTTPException(status_code=401, detail="not_authenticated")
            if not user["needs_password_reset"]:
                if payload.old_password is None or not verify_password(payload.old_password, str(row["password_hash"])):
                    raise HTTPException(status_code=401, detail="invalid_credentials")
            if payload.new_password.strip() == "":
                raise HTTPException(status_code=400, detail="invalid_password")
            change_password(conn, username=username, new_password=payload.new_password)
            audit(conn, actor_username=username, action="change_password", target=username, meta={})
        return {"ok": True}

    @app.get("/api/admin/pending_users", response_model=PendingUsersOut)
    def admin_pending_users(cr_session: str | None = Cookie(default=None)) -> PendingUsersOut:
        settings, _ = _require_loaded()
        admin = _require_admin(_current_user(cr_session))
        with connect(settings.db_path) as conn:
            rows = list_pending_users(conn)
        return PendingUsersOut(
            users=[PendingUserOut(username=str(r["username"]), nickname=str(r["nickname"]), created_at=str(r["created_at"])) for r in rows]
        )

    @app.post("/api/admin/approve")
    def admin_approve(payload: ApproveIn, cr_session: str | None = Cookie(default=None)) -> dict[str, bool]:
        settings, _ = _require_loaded()
        admin = _require_admin(_current_user(cr_session))
        username = payload.username.strip()
        with connect(settings.db_path) as conn:
            try:
                approve_user(conn, username=username, approved_by=str(admin["username"]))
            except ValueError:
                raise HTTPException(status_code=409, detail="already_handled")
        return {"ok": True}

    @app.post("/api/admin/reject")
    def admin_reject(payload: RejectIn, cr_session: str | None = Cookie(default=None)) -> dict[str, bool]:
        settings, _ = _require_loaded()
        admin = _require_admin(_current_user(cr_session))
        username = payload.username.strip()
        with connect(settings.db_path) as conn:
            try:
                reject_user(conn, username=username, approved_by=str(admin["username"]), reason=payload.reason)
            except ValueError:
                raise HTTPException(status_code=409, detail="already_handled")
        return {"ok": True}

    @app.get("/api/admin/messages", response_model=AdminMessagesOut)
    def admin_messages(after_id: int = Query(default=0, ge=0), cr_session: str | None = Cookie(default=None)) -> AdminMessagesOut:
        settings, _ = _require_loaded()
        _require_admin(_current_user(cr_session))
        with connect(settings.db_path) as conn:
            pending_count = count_pending_users(conn)
            rows = list_admin_messages(conn, after_id=after_id)
        messages: list[AdminMessageOut] = []
        for r in rows:
            meta = None
            if r["meta_json"] is not None:
                try:
                    meta = json.loads(str(r["meta_json"]))
                except Exception:
                    meta = None
            messages.append(
                AdminMessageOut(
                    id=int(r["id"]),
                    actor_username=(str(r["actor_username"]) if r["actor_username"] is not None else None),
                    action=str(r["action"]),
                    target=(str(r["target"]) if r["target"] is not None else None),
                    created_at=str(r["created_at"]),
                    meta=meta,
                )
            )
        return AdminMessagesOut(pending_count=pending_count, messages=messages)

    def _fmt_ts(ts: int | None) -> str | None:
        if ts is None or ts <= 0:
            return None
        return datetime.fromtimestamp(int(ts)).isoformat(timespec="seconds")

    @app.get("/api/user/inbox", response_model=UserInboxOut)
    def user_inbox(cr_session: str | None = Cookie(default=None)) -> UserInboxOut:
        settings, manifest = _require_loaded()
        user = _require_labeler(_current_user(cr_session))
        with connect(settings.db_path) as conn:
            manifest_at = get_manifest_synced_at(conn)
            judged = list_judged_match_ids(conn, str(user["username"]))
            pending_count = max(0, len(manifest.matches) - len(judged))
            last_seen_at, last_seen_pending_count, last_seen_manifest_at = get_user_inbox_state(conn, username=str(user["username"]))
        new_since = 0
        if manifest_at > last_seen_manifest_at:
            new_since = max(0, pending_count - int(last_seen_pending_count))
        return UserInboxOut(
            pending_count=pending_count,
            last_manifest_updated_at=_fmt_ts(manifest_at),
            last_seen_at=_fmt_ts(last_seen_at),
            new_since_last_seen=int(new_since),
        )

    @app.post("/api/user/inbox/seen")
    def user_inbox_seen(cr_session: str | None = Cookie(default=None)) -> dict[str, bool]:
        settings, manifest = _require_loaded()
        user = _require_labeler(_current_user(cr_session))
        with connect(settings.db_path) as conn:
            manifest_at = get_manifest_synced_at(conn)
            judged = list_judged_match_ids(conn, str(user["username"]))
            pending_count = max(0, len(manifest.matches) - len(judged))
            mark_user_inbox_seen(
                conn,
                username=str(user["username"]),
                pending_count=pending_count,
                manifest_at=manifest_at,
                seen_at=int(time.time()),
            )
        return {"ok": True}

    @app.get("/api/tasks/next", response_model=NextTaskResponse)
    def get_next_task(
        mode: Literal["text", "audio", "both"] | None = Query(default=None),
        inline_text: bool = Query(default=True),
        cr_session: str | None = Cookie(default=None),
    ) -> NextTaskResponse:
        settings, manifest = _require_loaded()
        user = _require_labeler(_current_user(cr_session))
        effective_mode = (mode or settings.mode).strip().lower()
        if effective_mode not in {"text", "audio", "both"}:
            raise HTTPException(status_code=400, detail="invalid_mode")

        match: Match | None = None
        eligible_commentaries: list[Any] = []

        with connect(settings.db_path) as conn:
            now = int(time.time())
            cleanup_expired_assignments(conn, now=now)

            judged = list_judged_match_ids(conn, str(user["username"]))

            active_match_id = get_active_assignment(conn, user_id=str(user["username"]), now=now)
            if active_match_id and active_match_id not in judged:
                maybe_match = manifest.match_by_id.get(active_match_id)
                if maybe_match:
                    candidate_commentaries = _filter_commentaries(maybe_match, effective_mode)
                    if len(candidate_commentaries) >= 2:
                        match = maybe_match
                        eligible_commentaries = candidate_commentaries

            if match is None:
                candidates = [m for m in manifest.matches if m.match_id not in judged]
                random.shuffle(candidates)
                if not candidates:
                    raise HTTPException(status_code=404, detail="no_tasks")

                expires_at = now + ASSIGNMENT_TTL_SECONDS
                unavailable_for_mode: list[str] = []

                for candidate in candidates:
                    if not try_lock_assignment(
                        conn,
                        match_id=candidate.match_id,
                        user_id=str(user["username"]),
                        expires_at=expires_at,
                    ):
                        continue

                    candidate_commentaries = _filter_commentaries(candidate, effective_mode)
                    if len(candidate_commentaries) < 2:
                        # immediately release the lock so others can pick it up
                        conn.execute(
                            """
                            UPDATE assignments
                            SET status = 'expired'
                            WHERE match_id = ? AND user_id = ? AND status = 'assigning'
                            """,
                            (candidate.match_id, str(user["username"])),
                        )
                        conn.commit()
                        unavailable_for_mode.append(candidate.match_id)
                        continue

                    match = candidate
                    eligible_commentaries = candidate_commentaries
                    break

                if match is None:
                    detail = "no_tasks_for_mode" if unavailable_for_mode else "no_tasks"
                    raise HTTPException(status_code=404, detail=detail)

        video_url = match.video.url or (_static_url(match.video.path) if match.video.path else None)
        match_out = MatchOut(
            match_id=match.match_id,
            title=match.title,
            league=match.league,
            date=match.date,
            length_sec=match.length_sec,
            video=VideoOut(url=video_url, sha256=match.video.sha256),
            commentaries=[],
        )

        for c in eligible_commentaries:
            text_url = _static_url(c.text.path) if c.text and c.text.path else None
            audio_url = c.audio.url if c.audio and c.audio.url else (_static_url(c.audio.path) if c.audio and c.audio.path else None)
            text_payload: str | list[dict[str, Any]] | None = None
            sync_offset_ms = 0
            if isinstance(c.alignment, dict):
                raw_offset = c.alignment.get("sync_offset_ms")
                if isinstance(raw_offset, int):
                    sync_offset_ms = raw_offset
            if inline_text and c.text and c.text.path:
                text_payload = _read_text_payload(settings.data_dir, c.text.path)
            match_out.commentaries.append(
                CommentaryOut(
                    commentary_id=c.commentary_id,
                    type=c.type,
                    language=c.language,
                    source=c.source,
                    has_audio=bool(audio_url),
                    sync_offset_ms=sync_offset_ms,
                    text=text_payload,
                    text_url=text_url,
                    audio_url=audio_url,
                )
            )

        return NextTaskResponse(user_id=str(user["username"]), mode=effective_mode, match=match_out)

    @app.post("/api/judgments", response_model=JudgmentOut)
    def post_judgment(
        payload: JudgmentIn,
        cr_session: str | None = Cookie(default=None),
    ) -> JudgmentOut:
        settings, manifest = _require_loaded()
        user = _require_labeler(_current_user(cr_session))

        effective_mode = ((payload.mode or settings.mode) or "both").strip().lower()
        if effective_mode not in {"text", "audio", "both"}:
            raise HTTPException(status_code=400, detail="invalid_mode")

        match = manifest.match_by_id.get(payload.match_id)
        if match is None:
            raise HTTPException(status_code=404, detail="unknown_match")

        ranking = [x.strip() for x in payload.commentary_ids if isinstance(x, str) and x.strip() != ""]
        if len(ranking) < 2:
            raise HTTPException(status_code=400, detail="invalid_ranking")
        if len(set(ranking)) != len(ranking):
            raise HTTPException(status_code=400, detail="duplicate_commentary_id")

        by_id = {c.commentary_id: c for c in match.commentaries}
        missing = [cid for cid in ranking if cid not in by_id]
        if missing:
            raise HTTPException(status_code=400, detail={"unknown_commentary_ids": missing})

        judgment_id: int
        with connect(settings.db_path) as conn:
            judgment_id = insert_judgment(
                conn,
                match_id=match.match_id,
                user_id=str(user["username"]),
                ranking=ranking,
                mode=effective_mode,
                latency_ms=payload.latency_ms,
                reason=payload.reason,
                flags=payload.flags,
            )
        return JudgmentOut(judgment_id=judgment_id)

    @app.get("/api/stats/matches", response_model=StatsMatchesResponse)
    def stats_matches(cr_session: str | None = Cookie(default=None)) -> StatsMatchesResponse:
        settings, manifest = _require_loaded()
        _require_admin(_current_user(cr_session))
        counts_by_match: dict[str, dict[str, int]] = {}
        with connect(settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT match_id, mode, COUNT(*) AS c
                FROM judgments
                GROUP BY match_id, mode
                """
            ).fetchall()
        for r in rows:
            mid = str(r["match_id"])
            mode = str(r["mode"])
            counts_by_match.setdefault(mid, {})
            counts_by_match[mid][mode] = int(r["c"])

        items: list[StatsMatchItem] = []
        for match in manifest.matches:
            mode_counts = counts_by_match.get(match.match_id, {})
            audio_c = int(mode_counts.get("audio", 0))
            text_c = int(mode_counts.get("text", 0))
            both_c = int(mode_counts.get("both", 0))
            total_c = audio_c + text_c + both_c
            video_url = match.video.url or (_static_url(match.video.path) if match.video.path else None)
            items.append(
                StatsMatchItem(
                    match_id=match.match_id,
                    title=match.title,
                    league=match.league,
                    date=match.date,
                    video_url=video_url,
                    cover_url=_cover_url(settings, match),
                    counts=StatsCounts(audio=audio_c, text=text_c, both=both_c, total=total_c),
                )
            )
        return StatsMatchesResponse(matches=items)

    @app.get("/api/stats/match", response_model=StatsMatchDetailResponse)
    def stats_match(match_id: str = Query(..., min_length=1), cr_session: str | None = Cookie(default=None)) -> StatsMatchDetailResponse:
        settings, manifest = _require_loaded()
        _require_admin(_current_user(cr_session))
        match = manifest.match_by_id.get(match_id)
        if match is None:
            raise HTTPException(status_code=404, detail="unknown_match")

        with connect(settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, match_id, user_id, ranking_json, mode, latency_ms, reason, flags_json, created_at
                FROM judgments
                WHERE match_id = ?
                ORDER BY id ASC
                """,
                (match_id,),
            ).fetchall()

        by_mode: dict[str, list[StatsJudgmentOut]] = {"audio": [], "text": [], "both": []}
        raw_rankings_by_mode: dict[str, list[list[str]]] = {"audio": [], "text": [], "both": []}
        for r in rows:
            mode = str(r["mode"])
            ranking_ids = json.loads(str(r["ranking_json"]))
            if not isinstance(ranking_ids, list):
                continue
            ranking_ids = [str(x) for x in ranking_ids]
            if mode not in by_mode:
                by_mode[mode] = []
                raw_rankings_by_mode[mode] = []
            raw_rankings_by_mode[mode].append(ranking_ids)
            by_mode[mode].append(
                StatsJudgmentOut(
                    judgment_id=int(r["id"]),
                    created_at=str(r["created_at"]),
                    user_id=str(r["user_id"]),
                    mode=mode,
                    ranking=_ranking_items(settings, manifest, ranking_ids),
                    ranking_ids=ranking_ids,
                    latency_ms=(int(r["latency_ms"]) if r["latency_ms"] is not None else None),
                    reason=(str(r["reason"]) if r["reason"] is not None else None),
                    flags=(json.loads(str(r["flags_json"])) if r["flags_json"] is not None else None),
                )
            )

        win_stats_by_mode: dict[str, list[CommentaryWinStats]] = {}
        for mode, rankings in raw_rankings_by_mode.items():
            computed = _compute_win_stats(rankings, manifest)
            win_stats_by_mode[mode] = [
                CommentaryWinStats(
                    id=str(x["id"]),
                    source=(str(x["source"]) if x.get("source") is not None else None),
                    top1_pct=(float(x["top1_pct"]) if x.get("top1_pct") is not None else None),
                    avg_rank=(float(x["avg_rank"]) if x.get("avg_rank") is not None else None),
                    pairwise_win_rate=(float(x["pairwise_win_rate"]) if x.get("pairwise_win_rate") is not None else None),
                )
                for x in computed
            ]

        video_url = match.video.url or (_static_url(match.video.path) if match.video.path else None)
        detail_match = StatsMatchItem(
            match_id=match.match_id,
            title=match.title,
            league=match.league,
            date=match.date,
            video_url=video_url,
            cover_url=_cover_url(settings, match),
            counts=StatsCounts(
                audio=len(by_mode.get("audio", [])),
                text=len(by_mode.get("text", [])),
                both=len(by_mode.get("both", [])),
                total=len(rows),
            ),
        )
        return StatsMatchDetailResponse(match=detail_match, by_mode=by_mode, win_stats_by_mode=win_stats_by_mode)

    @app.get("/api/export")
    def export(
        format: Literal["jsonl", "csv"] = Query(default="jsonl"),
        match_id: str | None = Query(default=None),
        mode: Literal["audio", "text", "both"] | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1),
        cr_session: str | None = Cookie(default=None),
    ) -> StreamingResponse:
        settings, manifest = _require_loaded()
        admin = _require_admin(_current_user(cr_session))
        with connect(settings.db_path) as conn:
            sql = "SELECT id, match_id, user_id, ranking_json, mode, latency_ms, reason, flags_json, created_at FROM judgments"
            args: list[Any] = []
            where: list[str] = []
            if match_id is not None and match_id.strip() != "":
                where.append("match_id = ?")
                args.append(match_id.strip())
            if mode is not None:
                where.append("mode = ?")
                args.append(mode)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY id ASC"
            if limit is not None:
                sql += " LIMIT ?"
                args.append(limit)
            rows = conn.execute(sql, tuple(args)).fetchall()
            audit(conn, actor_username=str(admin["username"]), action="export", target=None, meta={"match_id": match_id, "mode": mode, "format": format, "limit": limit})

        if format == "jsonl":
            def iter_lines() -> Any:
                for r in rows:
                    match = manifest.match_by_id.get(str(r["match_id"]))
                    ranking_ids = json.loads(str(r["ranking_json"]))
                    if not isinstance(ranking_ids, list):
                        continue
                    ranking_ids = [str(x) for x in ranking_ids]
                    ranking = [x.model_dump() for x in _ranking_items(settings, manifest, ranking_ids)]
                    obj = {
                        "judgment_id": int(r["id"]),
                        "match_id": str(r["match_id"]),
                        "labeler_id": str(r["user_id"]),
                        "created_at": str(r["created_at"]),
                        "mode": str(r["mode"]),
                        "latency_ms": (int(r["latency_ms"]) if r["latency_ms"] is not None else None),
                        "reason": (str(r["reason"]) if r["reason"] is not None else None),
                        "flags": (json.loads(str(r["flags_json"])) if r["flags_json"] is not None else None),
                        "ranking": ranking,
                        "ranking_ids": ranking_ids,
                        "match": {
                            "title": (match.title if match else None),
                            "league": (match.league if match else None),
                            "date": (match.date if match else None),
                            "length_sec": (match.length_sec if match else None),
                            "video": {
                                "path": (match.video.path if match else None),
                                "url": (match.video.url if match else None),
                                "sha256": (match.video.sha256 if match else None),
                            },
                        },
                    }
                    yield (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

            return StreamingResponse(
                iter_lines(),
                media_type="application/jsonl; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="export.jsonl"'},
            )

        def iter_csv() -> Any:
            header = "judgment_id,match_id,user_id,created_at,mode,latency_ms,ranking_json\n"
            yield header.encode("utf-8")
            for r in rows:
                fields = [
                    str(int(r["id"])),
                    str(r["match_id"]),
                    str(r["user_id"]),
                    str(r["created_at"]),
                    str(r["mode"]),
                    "" if r["latency_ms"] is None else str(int(r["latency_ms"])),
                    json.dumps(json.loads(str(r["ranking_json"])), ensure_ascii=False).replace('"', '""'),
                ]
                line = ",".join([
                    fields[0],
                    fields[1],
                    fields[2],
                    fields[3],
                    fields[4],
                    fields[5],
                    f"\"{fields[6]}\"",
                ]) + "\n"
                yield line.encode("utf-8")

        return StreamingResponse(
            iter_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="export.csv"'},
        )

    return app


app = create_app()
