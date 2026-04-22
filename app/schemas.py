from __future__ import annotations

from pydantic import BaseModel, Field


class VideoOut(BaseModel):
    url: str | None = None
    sha256: str | None = None


class CommentaryOut(BaseModel):
    commentary_id: str
    type: str
    language: str | None = None
    source: str | None = None
    has_audio: bool = False
    sync_offset_ms: int = 0
    text: str | list[dict] | None = None
    text_url: str | None = None
    audio_url: str | None = None


class MatchOut(BaseModel):
    match_id: str
    title: str | None = None
    league: str | None = None
    date: str | None = None
    length_sec: int | None = None
    prompt_label: str | None = None
    prompt_text: str | list[dict] | dict | None = None
    video: VideoOut
    commentaries: list[CommentaryOut]


class NextTaskResponse(BaseModel):
    user_id: str
    mode: str
    task_type: str = "video_compare"
    match: MatchOut


class JudgmentIn(BaseModel):
    match_id: str
    commentary_ids: list[str] = Field(min_length=2)
    user_id: str | None = None
    mode: str | None = None
    latency_ms: int | None = None
    reason: str | None = None
    flags: dict | None = None


class JudgmentOut(BaseModel):
    judgment_id: int


class StatsCounts(BaseModel):
    audio: int = 0
    text: int = 0
    both: int = 0
    total: int = 0


class StatsMatchItem(BaseModel):
    match_id: str
    title: str | None = None
    league: str | None = None
    date: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    counts: StatsCounts


class StatsMatchesResponse(BaseModel):
    matches: list[StatsMatchItem]


class RankingItemOut(BaseModel):
    rank: int
    id: str
    source: str | None = None
    language: str | None = None
    type: str | None = None
    text_snapshot: str | None = None
    audio_url_or_path: str | None = None


class StatsJudgmentOut(BaseModel):
    judgment_id: int
    created_at: str
    user_id: str
    mode: str
    ranking: list[RankingItemOut]
    ranking_ids: list[str]
    latency_ms: int | None = None
    reason: str | None = None
    flags: dict | None = None


class CommentaryWinStats(BaseModel):
    id: str
    source: str | None = None
    top1_pct: float | None = None
    avg_rank: float | None = None
    pairwise_win_rate: float | None = None


class StatsMatchDetailResponse(BaseModel):
    match: StatsMatchItem
    by_mode: dict[str, list[StatsJudgmentOut]]
    win_stats_by_mode: dict[str, list[CommentaryWinStats]]


class AuthMeOut(BaseModel):
    username: str
    nickname: str
    role: str
    status: str
    needs_password_reset: bool


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    ok: bool = True
    needs_password_reset: bool
    role: str


class RegisterIn(BaseModel):
    nickname: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str | None = None
    new_password: str


class PendingUserOut(BaseModel):
    username: str
    nickname: str
    created_at: str


class PendingUsersOut(BaseModel):
    users: list[PendingUserOut]


class ApproveIn(BaseModel):
    username: str


class RejectIn(BaseModel):
    username: str
    reason: str | None = None


class AdminMessageOut(BaseModel):
    id: int
    actor_username: str | None = None
    action: str
    target: str | None = None
    created_at: str
    meta: dict | None = None


class AdminMessagesOut(BaseModel):
    pending_count: int
    messages: list[AdminMessageOut]


class UserInboxOut(BaseModel):
    pending_count: int
    last_manifest_updated_at: str | None = None
    last_seen_at: str | None = None
    new_since_last_seen: int = 0
