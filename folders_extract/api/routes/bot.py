# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 CodeX Devs — All Rights Reserved              ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/34thSTQ2Sp                      ║
# ║   youtube  ──  https://youtube.com/@CodeXDevs                   ║
# ║   github   ──  https://github.com/RayExo                        ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

from fastapi import APIRouter, Depends
from api.dependencies import get_bot
from api.schemas import BotInfo, BotStatus, CommandInfo
from typing import TYPE_CHECKING, List
import time
from utils.config import *


if TYPE_CHECKING:
    from core.zyrox import zyrox

router = APIRouter()


def _is_owner_only(command) -> bool:
    """Best-effort detection of commands.is_owner()/is_owner_or_staff-style checks,
    so owner/dev-only commands never get exposed as server-admin functionality."""
    for check in getattr(command, "checks", []):
        qualname = getattr(check, "__qualname__", "") or getattr(check, "__name__", "")
        if "is_owner" in qualname:
            return True
    return False

@router.get("/status", response_model=BotStatus, summary="Get bot status", description="Returns real-time health metrics, latency, and scale information.")
async def get_status(bot: "zyrox" = Depends(get_bot)):
    """
    Returns the live status of the bot.
    """
    start = getattr(bot, "start_time", None)
    uptime = int(time.time() - start) if start else None
    return BotStatus(
        user=str(bot.user),
        id=str(bot.user.id) if bot.user else None,
        latency=bot.latency * 1000,
        guild_count=len(bot.guilds),
        user_count=sum(g.member_count or 0 for g in bot.guilds),
        shards=bot.shard_count,
        uptime=uptime
    )

@router.get("/info", response_model=BotInfo, summary="Get bot info", description="Returns general information about the bot including command count and user reach.")
async def get_bot_info(bot: "zyrox" = Depends(get_bot)):
    """
    Get general information about the Discord bot.
    """
    return BotInfo(
        name=bot.user.name if bot.user else BRAND_NAME,
        id=str(bot.user.id) if bot.user else None,
        guilds=len(bot.guilds),
        users=sum(g.member_count or 0 for g in bot.guilds),
        commands=len(bot.commands),
        latency=f"{round(bot.latency * 1000, 2)}ms"
    )

@router.get("/commands", response_model=List[CommandInfo], summary="List bot commands", description="Returns command metadata for the dashboard's command browser. Owner-only commands are excluded.")
async def list_commands(bot: "zyrox" = Depends(get_bot)):
    """
    Builds command metadata from the live command tree rather than a hardcoded
    frontend list, so the dashboard always reflects what's actually loaded.
    """
    seen_prefix = set()
    results: List[CommandInfo] = []

    for command in bot.walk_commands():
        if command.hidden or _is_owner_only(command):
            continue
        qualified = command.qualified_name
        if qualified in seen_prefix:
            continue
        seen_prefix.add(qualified)
        cog_name = command.cog.qualified_name if command.cog else "Uncategorized"
        results.append(CommandInfo(
            name=qualified,
            aliases=list(getattr(command, "aliases", []) or []),
            description=(command.help or command.short_doc or "").strip() or None,
            category=cog_name,
            usage=f"{qualified} {command.signature}".strip() if getattr(command, "signature", None) else qualified,
            is_prefix=True,
            is_slash=False,
        ))

    try:
        for app_cmd in bot.tree.walk_commands():
            name = app_cmd.qualified_name
            existing = next((r for r in results if r.name == name), None)
            if existing:
                existing.is_slash = True
                continue
            results.append(CommandInfo(
                name=name,
                aliases=[],
                description=(getattr(app_cmd, "description", "") or "").strip() or None,
                category=getattr(getattr(app_cmd, "binding", None), "qualified_name", None) or "Uncategorized",
                usage=f"/{name}",
                is_prefix=False,
                is_slash=True,
            ))
    except Exception:
        # bot.tree may not be populated (e.g. slash sync not run yet) — prefix commands still return.
        pass

    return results
