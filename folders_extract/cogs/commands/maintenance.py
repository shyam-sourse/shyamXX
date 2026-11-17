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

"""
Maintenance mode for Zyrox.

Locks the whole bot down while the developers push updates. While maintenance
mode is active every command is blocked (through a global check) except for:

    * the bot owners
    * users added to the bypass list
    * guilds added to the bypass list
    * roles (per guild) added to the bypass list
    * the ``maintenance`` command group itself

Extra features
--------------
* **Timer** — ``enable`` accepts a duration (``30m``, ``2h``, ``1d12h`` ...).
  When it elapses the bot automatically comes back online and announces it.
* **Popup** — anyone who tries to use the bot while it is down, in any guild
  or DM, gets a Component-v2 "maintenance in progress" popup with the live
  time remaining. A short per-user cooldown stops message spam.
* **Staff log** — optionally mirror every blocked attempt (who, where,
  which command) to a log channel so you can watch usage everywhere.

Settings are persisted to ``data/maintenance.json`` so state survives restarts.
"""

from __future__ import annotations

import json
import os
import re
import time

import discord
from discord.ext import commands, tasks
from discord.ui import Button, ActionRow, LayoutView, Separator, TextDisplay

from core import zyrox
from utils.config import *
from utils.cv2 import build_container
from utils.emoji import (
    CROSS,
    DISABLE,
    ENABLE,
    ICONLOAD,
    INFO,
    MENTION,
    SYSTEM,
    TICK,
    TIME,
    WARNING,
    ZMODULE,
    ZPEOPLE,
    ZROCKET,
    ZSAFE,
    ZSETTINGS,
    ZWRENCH,
)

DEFAULT_REASON = "The bot is currently under maintenance. Please try again later."
POPUP_COOLDOWN = 30  # seconds between popups for the same user
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


class MaintenanceActive(commands.CheckFailure):
    """Raised when a command is used while maintenance mode is enabled."""

    def __init__(self, reason: str = DEFAULT_REASON):
        self.reason = reason or DEFAULT_REASON
        super().__init__(self.reason)


class MaintenanceView(LayoutView):
    """Small helper that renders a title plus optional text sections in CV2."""

    def __init__(self, title: str, *sections: str):
        super().__init__(timeout=None)
        items = [TextDisplay(f"**{title}**")]
        for section in sections:
            items.append(Separator(visible=True))
            items.append(TextDisplay(str(section)))
        self.add_item(build_container(*items))


class Maintenance(commands.Cog):
    """Controls the bot-wide maintenance mode, its timer and its bypass lists."""

    def __init__(self, bot: zyrox):
        self.bot = bot
        self.file = os.path.join("data", "maintenance.json")
        os.makedirs(os.path.dirname(self.file), exist_ok=True)
        self.data = self._load()
        self._check_added = False
        self._popup_cooldown: dict[int, float] = {}

        # app-command hooks (slash commands) — chained with whatever exists
        self._tree = None
        self._orig_interaction_check = None
        self._orig_tree_error = None

        # background loop that watches the timer
        self._timer = tasks.loop(seconds=30)(self._auto_disable)
        self._timer.before_loop(self._before_timer)

    async def cog_load(self) -> None:
        if not self._check_added:
            self.bot.add_check(self.maintenance_check)
            self._check_added = True

        # cover slash / app commands too
        self._tree = self.bot.tree
        self._orig_interaction_check = self._tree.interaction_check
        self._orig_tree_error = self._tree.on_error
        self._tree.interaction_check = self._tree_interaction_check
        self._tree.on_error = self._tree_on_error

        if not self._timer.is_running():
            self._timer.start()

    def cog_unload(self) -> None:
        if self._check_added:
            self.bot.remove_check(self.maintenance_check)
            self._check_added = False
        if self._tree is not None:
            self._tree.interaction_check = self._orig_interaction_check
            self._tree.on_error = self._orig_tree_error
            self._tree = None
        self._timer.cancel()

    async def _before_timer(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    # Storage
    # ------------------------------------------------------------------ #
    def _load(self) -> dict:
        data = {
            "enabled": False,
            "reason": None,
            "ends_at": None,
            "popup": True,
            "log_channel": None,
            "users": [],
            "roles": {},
            "guilds": [],
        }
        try:
            if os.path.exists(self.file):
                with open(self.file, "r", encoding="utf-8") as fp:
                    stored = json.load(fp)
                if isinstance(stored, dict):
                    data.update(stored)
        except (OSError, ValueError):
            pass
        return data

    def _save(self) -> None:
        try:
            with open(self.file, "w", encoding="utf-8") as fp:
                json.dump(self.data, fp, indent=4)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Time helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_duration(text: str | None) -> int | None:
        """Parse '1h30m' / '45m' / '90' (plain = minutes) into seconds."""
        if not text:
            return None
        text = text.strip().lower()
        if text.isdigit():
            return int(text) * 60
        matches = re.findall(r"(\d+)\s*([smhdw])", text)
        if matches and re.sub(r"(\d+)\s*([smhdw])", "", text).strip() == "":
            return sum(int(value) * DURATION_UNITS[unit] for value, unit in matches)
        return None

    @staticmethod
    def _format_seconds(total: int) -> str:
        total = max(0, int(total))
        parts = []
        for label, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
            if total >= size or (label == "s" and not parts):
                value, total = divmod(total, size)
                if value or label == "s":
                    parts.append(f"{value}{label}")
        return " ".join(parts) or "0s"

    def _remaining(self) -> int | None:
        ends = self.data.get("ends_at")
        if not ends:
            return None
        return max(0, int(ends - time.time()))

    def _remaining_text(self) -> str:
        left = self._remaining()
        if left is None:
            return "Permanent (until disabled manually)"
        if left <= 0:
            return "Ending now..."
        return f"{self._format_seconds(left)} remaining"

    def _expiry_text(self) -> str:
        ends = self.data.get("ends_at")
        if not ends:
            return "No timer set"
        return f"<t:{int(ends)}:f> (<t:{int(ends)}:R>)"

    # ------------------------------------------------------------------ #
    # Global check + popup
    # ------------------------------------------------------------------ #
    async def _is_bypassed(self, user: discord.abc.User, guild) -> bool:
        if await self.bot.is_owner(user):
            return True
        if user.id in self.data.get("users", []):
            return True
        if guild is not None:
            if guild.id in self.data.get("guilds", []):
                return True
            role_ids = self.data.get("roles", {}).get(str(guild.id), [])
            if any(role.id in role_ids for role in getattr(user, "roles", [])):
                return True
        return False

    async def maintenance_check(self, ctx: commands.Context) -> bool:
        if not self.data.get("enabled"):
            return True

        root = ctx.command.qualified_name.split()[0] if ctx.command else ""
        if root in ("maintenance", "maint"):
            return True

        if await self._is_bypassed(ctx.author, ctx.guild):
            return True

        await self._show_popup(ctx)
        raise MaintenanceActive(self.data.get("reason") or DEFAULT_REASON)

    def _popup_view(self, author: discord.abc.User) -> MaintenanceView:
        reason = self.data.get("reason") or DEFAULT_REASON
        sections = [reason]
        if self.data.get("ends_at"):
            sections.append(f"{TIME} **Time remaining:** {self._remaining_text()}")
            sections.append(f"**Back online:** {self._expiry_text()}")
        sections.append(f"{ZSAFE} {author.mention}, please try again soon.")
        return MaintenanceView(f"{ZWRENCH} Maintenance In Progress", *sections)

    async def _show_popup(self, ctx: commands.Context) -> None:
        # throttled popup shown to the user who tried to use the bot
        if self.data.get("popup", True):
            now = time.time()
            if now - self._popup_cooldown.get(ctx.author.id, 0) >= POPUP_COOLDOWN:
                self._popup_cooldown[ctx.author.id] = now
                view = self._popup_view(ctx.author)
                sent = False
                try:
                    if ctx.guild is not None and ctx.channel is not None:
                        if ctx.channel.permissions_for(ctx.me).send_messages:
                            await ctx.send(view=view)
                            sent = True
                    else:
                        await ctx.author.send(view=view)
                        sent = True
                except discord.HTTPException:
                    sent = False
                if not sent:
                    try:
                        await ctx.author.send(view=view)
                    except discord.HTTPException:
                        pass

        await self._log_attempt(ctx)

    async def _log_attempt(self, ctx: commands.Context) -> None:
        channel_id = self.data.get("log_channel")
        if not channel_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None or getattr(channel, "id", None) == getattr(ctx.channel, "id", None):
            return

        if ctx.guild is not None:
            location = f"{ctx.guild.name} ({ctx.guild.id}) / <#{ctx.channel.id}>"
        else:
            location = "Direct Messages"
        command = ctx.command.qualified_name if ctx.command else "unknown"
        button = Button(label="Support", style=discord.ButtonStyle.link, url="https://discord.gg/34thSTQ2Sp")
        view = MaintenanceView(
            f"{INFO} Maintenance Attempt",
            f"{MENTION} **User:** {ctx.author} (`{ctx.author.id}`)",
            f"{SYSTEM} **Location:** {location}",
            f"{ZSETTINGS} **Command:** `{command}`",
            f"{TIME} **When:** <t:{int(time.time())}:T>",
        )
        view.add_item(ActionRow(button))
        try:
            await channel.send(view=view)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ #
    # App command (slash) hooks
    # ------------------------------------------------------------------ #
    async def _tree_interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._orig_interaction_check is not None:
            if not await self._orig_interaction_check(interaction):
                return False

        if not self.data.get("enabled"):
            return True

        command = getattr(interaction, "command", None)
        root = command.qualified_name.split()[0] if command is not None else ""
        if root in ("maintenance", "maint"):
            return True

        if await self._is_bypassed(interaction.user, interaction.guild):
            return True

        await self._show_interaction_popup(interaction)
        raise MaintenanceActive(self.data.get("reason") or DEFAULT_REASON)

    async def _tree_on_error(self, interaction: discord.Interaction, error: Exception) -> bool:
        # our popup was already sent from the interaction check — swallow it
        if isinstance(error, MaintenanceActive):
            return True
        if self._orig_tree_error is not None:
            return bool(await self._orig_tree_error(interaction, error))
        return False

    async def _show_interaction_popup(self, interaction: discord.Interaction) -> None:
        if self.data.get("popup", True):
            now = time.time()
            if now - self._popup_cooldown.get(interaction.user.id, 0) >= POPUP_COOLDOWN:
                self._popup_cooldown[interaction.user.id] = now
                view = self._popup_view(interaction.user)
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(view=view, ephemeral=True)
                    else:
                        await interaction.response.send_message(view=view, ephemeral=True)
                except discord.HTTPException:
                    pass

        await self._log_interaction(interaction)

    async def _log_interaction(self, interaction: discord.Interaction) -> None:
        channel_id = self.data.get("log_channel")
        if not channel_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            return

        if interaction.guild is not None:
            location = f"{interaction.guild.name} ({interaction.guild.id}) / <#{interaction.channel_id}>"
        else:
            location = "Direct Messages"
        command = interaction.command.qualified_name if interaction.command else "unknown"
        button = Button(label="Support", style=discord.ButtonStyle.link, url="https://discord.gg/34thSTQ2Sp")
        view = MaintenanceView(
            f"{INFO} Maintenance Attempt",
            f"{MENTION} **User:** {interaction.user} (`{interaction.user.id}`)",
            f"{SYSTEM} **Location:** {location}",
            f"{ZSETTINGS} **Command:** `/{command}`",
            f"{TIME} **When:** <t:{int(time.time())}:T>",
        )
        view.add_item(ActionRow(button))
        try:
            await channel.send(view=view)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ #
    # Bypass helpers / views
    # ------------------------------------------------------------------ #
    def _bypass_lines(self) -> list[str]:
        users = self.data.get("users", [])
        guilds = self.data.get("guilds", [])
        roles = self.data.get("roles", {})

        user_text = ", ".join(f"<@{uid}>" for uid in users) or "*none*"
        guild_text = ", ".join(f"`{gid}`" for gid in guilds) or "*none*"

        role_lines = []
        for gid, ids in roles.items():
            if not ids:
                continue
            guild = self.bot.get_guild(int(gid))
            label = guild.name if guild else gid
            role_lines.append(f"**{label}** — " + ", ".join(f"<@&{rid}>" for rid in ids))
        role_text = "\n".join(role_lines) or "*none*"

        return [
            f"{ZPEOPLE} **Users**\n{user_text}",
            f"{SYSTEM} **Guilds**\n{guild_text}",
            f"{ZMODULE} **Roles**\n{role_text}",
        ]

    def _status_view(self) -> MaintenanceView:
        enabled = bool(self.data.get("enabled"))
        reason = self.data.get("reason") or DEFAULT_REASON
        state = f"{ENABLE} Enabled" if enabled else f"{DISABLE} Disabled"
        popup = f"{ENABLE} On" if self.data.get("popup", True) else f"{DISABLE} Off"
        log_channel = self.data.get("log_channel")
        log_text = f"<#{log_channel}>" if log_channel else "*off*"
        return MaintenanceView(
            f"{ZWRENCH} Maintenance Status",
            f"**State:** {state}",
            f"**Reason:** {reason}",
            f"{TIME} **Timer:** {self._remaining_text()}",
            f"**Ends at:** {self._expiry_text()}",
            f"**Popup:** {popup}",
            f"{INFO} **Staff log:** {log_text}",
        )

    def _bypass_view(self) -> MaintenanceView:
        sections = [f"{ZSAFE} The following are allowed through maintenance mode:"]
        sections.extend(self._bypass_lines())
        return MaintenanceView(f"{ZSAFE} Maintenance Bypass", *sections)

    # ------------------------------------------------------------------ #
    # Help / permission helpers
    # ------------------------------------------------------------------ #
    def _is_admin(self, ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return False
        perms = ctx.author.guild_permissions
        return perms.administrator or perms.manage_guild

    def _help_view(self, ctx: commands.Context) -> MaintenanceView:
        p = ctx.clean_prefix
        enabled = bool(self.data.get("enabled"))
        state = f"{ENABLE} Enabled" if enabled else f"{DISABLE} Disabled"
        commands = "\n".join(
            [
                f"`{p}maintenance` — show this menu",
                f"`{p}maintenance status` — live status, timer and bypass summary",
                f"`{p}maintenance enable [duration] [reason]` — turn maintenance on (e.g. `enable 1h Updating`)",
                f"`{p}maintenance disable` — turn maintenance off",
                f"`{p}maintenance timer <duration|off>` — set or clear the auto-disable timer",
                f"`{p}maintenance reason <text>` — change the maintenance message",
                f"`{p}maintenance popup <on|off>` — toggle the user popup",
                f"`{p}maintenance logchannel [#channel]` — mirror blocked attempts (omit to disable)",
                f"`{p}maintenance bypass list` — show all bypass entries",
                f"`{p}maintenance bypass add-user|remove-user <@user>`",
                f"`{p}maintenance bypass add-role|remove-role <@role>`",
                f"`{p}maintenance bypass add-guild|remove-guild <id>`",
                f"`{p}maintenance bypass clear`",
            ]
        )
        return MaintenanceView(
            f"{ZWRENCH} Maintenance Commands",
            f"**Current state:** {state}",
            f"{TIME} **Timer:** {self._remaining_text()}",
            commands,
            f"*Only the bot owner can run these commands.*",
        )

    # ------------------------------------------------------------------ #
    # Group
    # ------------------------------------------------------------------ #
    @commands.group(
        name="maintenance",
        aliases=["maint"],
        invoke_without_command=True,
        description="Enable, disable and inspect bot maintenance mode",
    )
    async def maintenance(self, ctx: commands.Context):
        if ctx.invoked_subcommand is not None:
            return
        if not (await self.bot.is_owner(ctx.author) or self._is_admin(ctx)):
            return await ctx.send(
                view=MaintenanceView(
                    f"{CROSS} No Permission",
                    "Only the bot owner or server administrators can view this menu.",
                )
            )
        await ctx.send(view=self._help_view(ctx))

    @maintenance.command(name="enable", description="Enable maintenance mode (optional timer)")
    @commands.is_owner()
    async def maintenance_enable(self, ctx: commands.Context, duration: str = None, *, reason: str = None):
        """``maintenance enable [duration] [reason]`` — duration like 30m, 2h, 1d12h."""
        reason = reason or DEFAULT_REASON
        seconds = None
        if duration:
            if duration.lower() in ("off", "none", "permanent", "forever"):
                seconds = None
            else:
                seconds = self._parse_duration(duration)
                if seconds is None:
                    reason = f"{duration} {reason}".strip()

        self.data["enabled"] = True
        self.data["reason"] = reason
        self.data["ends_at"] = (time.time() + seconds) if seconds else None
        self._save()

        sections = [reason]
        if seconds:
            sections.append(f"{TIME} **Auto-disable in:** {self._format_seconds(seconds)}")
            sections.append(f"**Back online:** {self._expiry_text()}")
        else:
            sections.append(f"{TIME} No timer set — maintenance runs until manually disabled.")
        sections.append(f"Use `{ctx.clean_prefix}maintenance disable` to stop early.")
        await ctx.send(view=MaintenanceView(f"{ZWRENCH} Maintenance Enabled", *sections))

    @maintenance.command(name="disable", description="Disable maintenance mode")
    @commands.is_owner()
    async def maintenance_disable(self, ctx: commands.Context):
        if not self.data.get("enabled"):
            return await ctx.send(
                view=MaintenanceView(f"{INFO} Not Enabled", "Maintenance mode is already disabled.")
            )

        self.data["enabled"] = False
        self.data["ends_at"] = None
        self._save()
        await ctx.send(
            view=MaintenanceView(
                f"{ZROCKET} Maintenance Disabled",
                "The bot is now accepting commands from everyone again.",
            )
        )

    @maintenance.command(name="timer", description="Set, update or clear the maintenance timer")
    @commands.is_owner()
    async def maintenance_timer(self, ctx: commands.Context, duration: str = None):
        if not self.data.get("enabled"):
            return await ctx.send(
                view=MaintenanceView(f"{INFO} Not Enabled", "Enable maintenance mode first.")
            )

        if duration is None or duration.lower() in ("off", "none", "clear", "permanent", "forever"):
            self.data["ends_at"] = None
            self._save()
            return await ctx.send(
                view=MaintenanceView(
                    f"{ZSETTINGS} Timer Cleared",
                    "Maintenance will now run until it is manually disabled.",
                )
            )

        seconds = self._parse_duration(duration)
        if not seconds:
            return await ctx.send(
                view=MaintenanceView(
                    f"{CROSS} Invalid Duration",
                    "Use formats like `30m`, `2h`, `1d12h`.",
                )
            )

        self.data["ends_at"] = time.time() + seconds
        self._save()
        await ctx.send(
            view=MaintenanceView(
                f"{TICK} Timer Set",
                f"{TIME} Auto-disable in **{self._format_seconds(seconds)}**.",
                f"**Back online:** {self._expiry_text()}",
            )
        )

    @maintenance.command(name="reason", description="Change the maintenance message")
    @commands.is_owner()
    async def maintenance_reason(self, ctx: commands.Context, *, reason: str):
        self.data["reason"] = reason
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{ZSETTINGS} Reason Updated", f"New maintenance message:\n{reason}")
        )

    @maintenance.command(name="popup", description="Toggle the popup shown to users during maintenance")
    @commands.is_owner()
    async def maintenance_popup(self, ctx: commands.Context, state: str = None):
        if state is None:
            new = not self.data.get("popup", True)
        elif state.lower() in ("on", "enable", "enabled", "true", "yes"):
            new = True
        elif state.lower() in ("off", "disable", "disabled", "false", "no"):
            new = False
        else:
            return await ctx.send(
                view=MaintenanceView(f"{CROSS} Invalid Option", "Use `on` or `off`.")
            )
        self.data["popup"] = new
        self._save()
        icon = ENABLE if new else DISABLE
        await ctx.send(
            view=MaintenanceView(f"{icon} Popup {'Enabled' if new else 'Disabled'}",
                                 f"Users will {'now' if new else 'no longer'} see the maintenance popup.")
        )

    @maintenance.command(name="logchannel", description="Mirror blocked attempts to a channel (omit to disable)")
    @commands.guild_only()
    @commands.is_owner()
    async def maintenance_logchannel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        if channel is None:
            self.data["log_channel"] = None
            self._save()
            return await ctx.send(
                view=MaintenanceView(f"{DISABLE} Log Channel Disabled", "Blocked attempts will no longer be logged.")
            )
        self.data["log_channel"] = channel.id
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{ENABLE} Log Channel Set", f"Blocked attempts will be sent to {channel.mention}.")
        )

    @maintenance.command(name="status", description="Show the current maintenance status")
    @commands.is_owner()
    async def maintenance_status(self, ctx: commands.Context):
        await ctx.send(view=self._status_view())

    # ------------------------------------------------------------------ #
    # Bypass management
    # ------------------------------------------------------------------ #
    @maintenance.group(
        name="bypass",
        invoke_without_command=True,
        description="Manage who can use the bot while maintenance is active",
    )
    @commands.is_owner()
    async def maintenance_bypass(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send(view=self._bypass_view())

    @maintenance_bypass.command(name="list", description="List all bypassed users, roles and guilds")
    @commands.is_owner()
    async def bypass_list(self, ctx: commands.Context):
        await ctx.send(view=self._bypass_view())

    @maintenance_bypass.command(name="add-user", description="Allow a user through maintenance")
    @commands.is_owner()
    async def bypass_add_user(self, ctx: commands.Context, user: discord.User):
        if user.id in self.data["users"]:
            return await ctx.send(
                view=MaintenanceView(f"{WARNING} Already Bypassed", f"{MENTION} {user.mention} is already allowed.")
            )
        self.data["users"].append(user.id)
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{TICK} User Bypassed", f"{MENTION} {user.mention} (`{user.id}`) can now use the bot.")
        )

    @maintenance_bypass.command(name="remove-user", description="Remove a user's bypass")
    @commands.is_owner()
    async def bypass_remove_user(self, ctx: commands.Context, user: discord.User):
        if user.id not in self.data["users"]:
            return await ctx.send(
                view=MaintenanceView(f"{CROSS} Not Bypassed", f"{MENTION} {user.mention} is not on the bypass list.")
            )
        self.data["users"].remove(user.id)
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{TICK} Bypass Removed", f"{user.mention} can no longer bypass maintenance.")
        )

    @maintenance_bypass.command(name="add-role", description="Allow a role through maintenance (this guild)")
    @commands.guild_only()
    @commands.is_owner()
    async def bypass_add_role(self, ctx: commands.Context, role: discord.Role):
        ids = self.data["roles"].setdefault(str(ctx.guild.id), [])
        if role.id in ids:
            return await ctx.send(
                view=MaintenanceView(f"{WARNING} Already Bypassed", f"{role.mention} is already allowed.")
            )
        ids.append(role.id)
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{TICK} Role Bypassed", f"{role.mention} can now use the bot in this guild.")
        )

    @maintenance_bypass.command(name="remove-role", description="Remove a role's bypass")
    @commands.guild_only()
    @commands.is_owner()
    async def bypass_remove_role(self, ctx: commands.Context, role: discord.Role):
        ids = self.data["roles"].get(str(ctx.guild.id), [])
        if role.id not in ids:
            return await ctx.send(
                view=MaintenanceView(f"{CROSS} Not Bypassed", f"{role.mention} is not on the bypass list.")
            )
        ids.remove(role.id)
        if not ids:
            self.data["roles"].pop(str(ctx.guild.id), None)
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{TICK} Bypass Removed", f"{role.mention} can no longer bypass maintenance.")
        )

    @maintenance_bypass.command(name="add-guild", description="Allow an entire guild through maintenance")
    @commands.is_owner()
    async def bypass_add_guild(self, ctx: commands.Context, guild_id: int):
        if guild_id in self.data["guilds"]:
            return await ctx.send(
                view=MaintenanceView(f"{WARNING} Already Bypassed", f"Guild `{guild_id}` is already allowed.")
            )
        self.data["guilds"].append(guild_id)
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{TICK} Guild Bypassed", f"Guild `{guild_id}` can now use the bot.")
        )

    @maintenance_bypass.command(name="remove-guild", description="Remove a guild's bypass")
    @commands.is_owner()
    async def bypass_remove_guild(self, ctx: commands.Context, guild_id: int):
        if guild_id not in self.data["guilds"]:
            return await ctx.send(
                view=MaintenanceView(f"{CROSS} Not Bypassed", f"Guild `{guild_id}` is not on the bypass list.")
            )
        self.data["guilds"].remove(guild_id)
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{TICK} Bypass Removed", f"Guild `{guild_id}` can no longer bypass maintenance.")
        )

    @maintenance_bypass.command(name="clear", description="Clear every bypass entry")
    @commands.is_owner()
    async def bypass_clear(self, ctx: commands.Context):
        self.data["users"] = []
        self.data["roles"] = {}
        self.data["guilds"] = []
        self._save()
        await ctx.send(
            view=MaintenanceView(f"{ICONLOAD} Bypass Cleared", "All users, roles and guilds were removed from the bypass list.")
        )

    # ------------------------------------------------------------------ #
    # Background timer
    # ------------------------------------------------------------------ #
    async def _auto_disable(self) -> None:
        if not self.data.get("enabled"):
            return
        ends = self.data.get("ends_at")
        if not ends or time.time() < ends:
            return

        self.data["enabled"] = False
        self.data["ends_at"] = None
        self._save()
        await self._announce_end()

    async def _announce_end(self) -> None:
        channel_id = self.data.get("log_channel")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            return
        try:
            await channel.send(
                view=MaintenanceView(
                    f"{ZROCKET} Maintenance Finished",
                    "The timer elapsed and the bot is back online automatically.",
                    f"{TICK} Everyone can use commands again.",
                )
            )
        except discord.HTTPException:
            pass


async def setup(bot: zyrox):
    await bot.add_cog(Maintenance(bot))
