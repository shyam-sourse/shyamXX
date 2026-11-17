"""
Platform-level (bot-owner) endpoints used by the ShyamX /admin panel.

Everything here is real data read from the live bot process / SQLite files, or
stored in db/platform.db (audit log, announcements, maintenance metadata,
guild join/leave events). Nothing is fabricated. All routes sit behind the
app-wide verify_api_key dependency; the dashboard additionally enforces that
only OWNER/ADMIN Discord IDs can reach them.
"""
import os
import sys
import time
import platform as _platform
from typing import TYPE_CHECKING, List, Optional

import aiosqlite
import psutil
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_bot

if TYPE_CHECKING:
    from core.zyrox import zyrox

admin_router = APIRouter()      # mounted at /api/v1/admin
public_router = APIRouter()     # mounted at /api/v1/platform

PLATFORM_DB = "db/platform.db"
CONFIG_DB = "db/admin_config.db"
_PROCESS_START = time.time()


# ───────────────────────── schema / helpers ─────────────────────────

async def _init():
    os.makedirs("db", exist_ok=True)
    async with aiosqlite.connect(PLATFORM_DB) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor_id TEXT, "
            "actor_name TEXT, action TEXT, target TEXT, result TEXT)"
        )
        await db.execute(
            "CREATE TABLE IF NOT EXISTS announcements (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, message TEXT, "
            "type TEXT, active INTEGER, starts_at REAL, expires_at REAL, created_by TEXT, created_at REAL)"
        )
        await db.execute(
            "CREATE TABLE IF NOT EXISTS guild_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, "
            "guild_id TEXT, guild_name TEXT, member_count INTEGER)"
        )
        await db.commit()


async def record_guild_event(kind: str, guild) -> None:
    """Called from CodeX.py on_guild_join / on_guild_remove."""
    try:
        await _init()
        async with aiosqlite.connect(PLATFORM_DB) as db:
            await db.execute(
                "INSERT INTO guild_events (ts, kind, guild_id, guild_name, member_count) VALUES (?,?,?,?,?)",
                (time.time(), kind, str(guild.id), guild.name, guild.member_count or 0),
            )
            await db.commit()
    except Exception:
        pass


# Maintenance state cache used by the Discord-side check (avoids a DB hit per command).
_maint_cache = {"ts": 0.0, "enabled": False, "message": ""}


async def _read_config_keys() -> dict:
    os.makedirs("db", exist_ok=True)
    async with aiosqlite.connect(CONFIG_DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        await db.commit()
        async with db.execute("SELECT key, value FROM config") as cur:
            return {k: v for k, v in await cur.fetchall()}


async def _set_config(pairs: dict) -> None:
    async with aiosqlite.connect(CONFIG_DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        for k, v in pairs.items():
            await db.execute("INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        await db.commit()
    _maint_cache["ts"] = 0.0


async def maintenance_check(ctx) -> bool:
    """
    discord.py global check: while maintenance is ON, only bot owners can run
    commands. Register with `client.add_check(maintenance_check)`.
    Fails open on any error so a broken config DB can never brick the bot.
    """
    from utils.config import OWNER_IDS
    from discord.ext import commands as _commands

    try:
        if time.time() - _maint_cache["ts"] > 10:
            cfg = await _read_config_keys()
            _maint_cache["enabled"] = cfg.get("maintenance_mode", "false").lower() == "true"
            _maint_cache["message"] = cfg.get("maintenance_message", "") or "The bot is currently under maintenance."
            _maint_cache["ts"] = time.time()
    except Exception:
        return True

    if not _maint_cache["enabled"] or ctx.author.id in OWNER_IDS:
        return True
    raise _commands.CheckFailure(f"🛠️ {_maint_cache['message']}")


# ───────────────────────── models ─────────────────────────

class SystemInfo(BaseModel):
    python_version: str
    discord_py_version: str
    platform: str
    pid: int
    process_uptime_seconds: int
    memory_mb: float
    cpu_percent: float
    threads: int
    shard_count: Optional[int] = None
    guild_count: int
    ready: bool
    latency_ms: float


class ModuleInfo(BaseModel):
    name: str
    loaded: bool
    commands: int
    listeners: int


class ExtensionInfo(BaseModel):
    name: str
    loaded: bool


class ModulesResponse(BaseModel):
    cogs: List[ModuleInfo]
    extensions: List[ExtensionInfo]


class DbFile(BaseModel):
    name: str
    size_bytes: int
    healthy: bool
    error: Optional[str] = None
    modified: float


class DatabaseResponse(BaseModel):
    directory: str
    total_bytes: int
    files: List[DbFile]


class ApiStats(BaseModel):
    window_size: int
    total_requests: int
    error_requests: int
    server_errors: int
    avg_latency_ms: float
    max_latency_ms: float
    recent_errors: List[dict]
    slowest_endpoints: List[dict]
    api_key_configured: bool


class AuditIn(BaseModel):
    actor_id: str = Field(..., max_length=32)
    actor_name: str = Field("", max_length=64)
    action: str = Field(..., max_length=120)
    target: str = Field("", max_length=200)
    result: str = Field("success", max_length=20)


class AuditOut(BaseModel):
    id: int
    ts: float
    actor_id: str
    actor_name: str
    action: str
    target: str
    result: str


class AnnouncementIn(BaseModel):
    title: str = Field(..., max_length=120)
    message: str = Field(..., max_length=2000)
    type: str = Field("info", pattern="^(info|update|maintenance|outage|feature)$")
    active: bool = True
    starts_at: Optional[float] = None
    expires_at: Optional[float] = None
    created_by: str = Field("", max_length=32)


class AnnouncementOut(BaseModel):
    id: int
    title: str
    message: str
    type: str
    active: bool
    starts_at: Optional[float]
    expires_at: Optional[float]
    created_by: str
    created_at: float


class MaintenanceIn(BaseModel):
    enabled: bool
    message: Optional[str] = Field(None, max_length=500)
    actor_id: str = ""
    actor_name: str = ""


class MaintenanceState(BaseModel):
    enabled: bool
    message: str
    enabled_by: Optional[str] = None
    enabled_at: Optional[float] = None


class GuildEvent(BaseModel):
    ts: float
    kind: str
    guild_id: str
    guild_name: str
    member_count: int


class PublicState(BaseModel):
    maintenance: MaintenanceState
    announcements: List[AnnouncementOut]
    bot_online: bool
    guild_count: int
    user_count: int
    command_count: int


# ───────────────────────── admin endpoints ─────────────────────────

@admin_router.get("/system", response_model=SystemInfo)
async def system_info(bot: "zyrox" = Depends(get_bot)):
    import discord
    proc = psutil.Process(os.getpid())
    return SystemInfo(
        python_version=sys.version.split()[0],
        discord_py_version=discord.__version__,
        platform=f"{_platform.system()} {_platform.release()}",
        pid=os.getpid(),
        process_uptime_seconds=int(time.time() - _PROCESS_START),
        memory_mb=round(proc.memory_info().rss / (1024 * 1024), 1),
        cpu_percent=psutil.cpu_percent(interval=None),
        threads=proc.num_threads(),
        shard_count=bot.shard_count,
        guild_count=len(bot.guilds),
        ready=bot.is_ready(),
        latency_ms=round(bot.latency * 1000, 1) if bot.latency == bot.latency else 0.0,
    )


@admin_router.get("/modules", response_model=ModulesResponse)
async def modules(bot: "zyrox" = Depends(get_bot)):
    cogs = [
        ModuleInfo(
            name=name,
            loaded=True,
            commands=len(cog.get_commands()),
            listeners=len(cog.get_listeners()),
        )
        for name, cog in sorted((bot.cogs or {}).items())
    ]
    exts = [ExtensionInfo(name=e, loaded=True) for e in sorted(bot.extensions.keys())]
    return ModulesResponse(cogs=cogs, extensions=exts)


@admin_router.get("/database", response_model=DatabaseResponse)
async def database_info():
    files: List[DbFile] = []
    total = 0
    for root in ("db",):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if not name.endswith(".db"):
                continue
            path = os.path.join(root, name)
            size = os.path.getsize(path)
            total += size
            healthy, err = True, None
            try:
                # Read-only quick_check; never writes, never modifies the file.
                async with aiosqlite.connect(f"file:{path}?mode=ro", uri=True) as db:
                    async with db.execute("PRAGMA quick_check(1)") as cur:
                        row = await cur.fetchone()
                        if not row or row[0] != "ok":
                            healthy, err = False, str(row[0] if row else "no result")
            except Exception as e:
                healthy, err = False, type(e).__name__
            files.append(DbFile(name=name, size_bytes=size, healthy=healthy, error=err, modified=os.path.getmtime(path)))
    return DatabaseResponse(directory="db/", total_bytes=total, files=files)


@admin_router.get("/api-stats", response_model=ApiStats)
async def api_stats():
    from api.server import request_logs
    logs = list(request_logs)
    total = len(logs)
    errors = [l for l in logs if int(l["status_code"]) >= 400]
    server_errors = [l for l in logs if int(l["status_code"]) >= 500]
    durations = [float(l["duration_ms"]) for l in logs] or [0.0]

    by_path: dict = {}
    for l in logs:
        by_path.setdefault(l["path"], []).append(float(l["duration_ms"]))
    slowest = sorted(
        ({"path": p, "avg_ms": round(sum(v) / len(v), 2), "count": len(v)} for p, v in by_path.items()),
        key=lambda x: x["avg_ms"],
        reverse=True,
    )[:8]

    return ApiStats(
        window_size=200,
        total_requests=total,
        error_requests=len(errors),
        server_errors=len(server_errors),
        avg_latency_ms=round(sum(durations) / len(durations), 2),
        max_latency_ms=round(max(durations), 2),
        recent_errors=[
            {k: l[k] for k in ("timestamp", "method", "path", "status_code", "duration_ms")} for l in errors[:15]
        ],
        slowest_endpoints=slowest,
        # Only whether a key is configured — never the key itself.
        api_key_configured=bool(os.getenv("DASHBOARD_API_KEY")),
    )


@admin_router.post("/audit", status_code=201)
async def audit_write(entry: AuditIn):
    await _init()
    async with aiosqlite.connect(PLATFORM_DB) as db:
        await db.execute(
            "INSERT INTO audit (ts, actor_id, actor_name, action, target, result) VALUES (?,?,?,?,?,?)",
            (time.time(), entry.actor_id, entry.actor_name, entry.action, entry.target, entry.result),
        )
        await db.commit()
    return {"status": "recorded"}


@admin_router.get("/audit", response_model=List[AuditOut])
async def audit_read(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), q: str = ""):
    await _init()
    async with aiosqlite.connect(PLATFORM_DB) as db:
        like = f"%{q}%"
        async with db.execute(
            "SELECT id, ts, actor_id, actor_name, action, target, result FROM audit "
            "WHERE action LIKE ? OR target LIKE ? OR actor_name LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (like, like, like, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
    return [AuditOut(id=r[0], ts=r[1], actor_id=r[2], actor_name=r[3], action=r[4], target=r[5], result=r[6]) for r in rows]


def _ann(r) -> AnnouncementOut:
    return AnnouncementOut(
        id=r[0], title=r[1], message=r[2], type=r[3], active=bool(r[4]),
        starts_at=r[5], expires_at=r[6], created_by=r[7], created_at=r[8],
    )


@admin_router.get("/announcements", response_model=List[AnnouncementOut])
async def announcements_list():
    await _init()
    async with aiosqlite.connect(PLATFORM_DB) as db:
        async with db.execute(
            "SELECT id,title,message,type,active,starts_at,expires_at,created_by,created_at FROM announcements ORDER BY id DESC LIMIT 100"
        ) as cur:
            return [_ann(r) for r in await cur.fetchall()]


@admin_router.post("/announcements", response_model=AnnouncementOut, status_code=201)
async def announcements_create(data: AnnouncementIn):
    await _init()
    now = time.time()
    async with aiosqlite.connect(PLATFORM_DB) as db:
        cur = await db.execute(
            "INSERT INTO announcements (title,message,type,active,starts_at,expires_at,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (data.title, data.message, data.type, int(data.active), data.starts_at, data.expires_at, data.created_by, now),
        )
        await db.commit()
        new_id = cur.lastrowid
    return AnnouncementOut(id=new_id, created_at=now, **data.model_dump())


@admin_router.patch("/announcements/{ann_id}")
async def announcements_toggle(ann_id: int, active: bool):
    await _init()
    async with aiosqlite.connect(PLATFORM_DB) as db:
        cur = await db.execute("UPDATE announcements SET active=? WHERE id=?", (int(active), ann_id))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Announcement not found")
    return {"status": "success"}


@admin_router.delete("/announcements/{ann_id}")
async def announcements_delete(ann_id: int):
    await _init()
    async with aiosqlite.connect(PLATFORM_DB) as db:
        cur = await db.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Announcement not found")
    return {"status": "success"}


async def _maintenance_state() -> MaintenanceState:
    cfg = await _read_config_keys()
    at = cfg.get("maintenance_enabled_at")
    return MaintenanceState(
        enabled=cfg.get("maintenance_mode", "false").lower() == "true",
        message=cfg.get("maintenance_message", "") or "",
        enabled_by=cfg.get("maintenance_enabled_by") or None,
        enabled_at=float(at) if at else None,
    )


@admin_router.get("/maintenance", response_model=MaintenanceState)
async def maintenance_get():
    return await _maintenance_state()


@admin_router.put("/maintenance", response_model=MaintenanceState)
async def maintenance_put(data: MaintenanceIn):
    pairs = {"maintenance_mode": str(data.enabled).lower()}
    if data.message is not None:
        pairs["maintenance_message"] = data.message
    if data.enabled:
        pairs["maintenance_enabled_by"] = f"{data.actor_name} ({data.actor_id})".strip()
        pairs["maintenance_enabled_at"] = str(time.time())
    await _set_config(pairs)
    return await _maintenance_state()


@admin_router.get("/guild-events", response_model=List[GuildEvent])
async def guild_events(limit: int = Query(20, ge=1, le=100)):
    await _init()
    async with aiosqlite.connect(PLATFORM_DB) as db:
        async with db.execute(
            "SELECT ts, kind, guild_id, guild_name, member_count FROM guild_events ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return [GuildEvent(ts=r[0], kind=r[1], guild_id=r[2], guild_name=r[3], member_count=r[4]) for r in await cur.fetchall()]


# ───────────────────────── platform-wide (non-owner) state ─────────────────────────

@public_router.get("/public-state", response_model=PublicState)
async def public_state(bot: "zyrox" = Depends(get_bot)):
    """Non-sensitive state safe to show on the public site and in every dashboard."""
    await _init()
    now = time.time()
    async with aiosqlite.connect(PLATFORM_DB) as db:
        async with db.execute(
            "SELECT id,title,message,type,active,starts_at,expires_at,created_by,created_at FROM announcements "
            "WHERE active=1 AND (starts_at IS NULL OR starts_at<=?) AND (expires_at IS NULL OR expires_at>=?) "
            "ORDER BY id DESC LIMIT 5",
            (now, now),
        ) as cur:
            anns = [_ann(r) for r in await cur.fetchall()]
    state = await _maintenance_state()
    # created_by is an admin identifier — strip it from the public payload.
    for a in anns:
        a.created_by = ""
    state.enabled_by = None
    return PublicState(
        maintenance=state,
        announcements=anns,
        bot_online=bot.is_ready(),
        guild_count=len(bot.guilds),
        user_count=sum(g.member_count or 0 for g in bot.guilds),
        command_count=len(bot.commands),
    )
