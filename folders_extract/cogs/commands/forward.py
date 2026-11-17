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

from __future__ import annotations

import json
import os
import re

import discord
from discord.ext import commands

from utils.config import *
from utils.cv2 import CV2
from utils.emoji import CHANNEL, CROSS, DELETE, FORWARD, INFO, MENTION, MESSAGE, PIN, SYSTEM, TICK, ZMODULE, ZWRENCH

STORE_FILE = "db/forward.json"
BRIDGE_FILE = "db/forward_links.json"
ROLE_FILE = "db/forward_roles.json"
MESSAGE_LINK_RE = re.compile(r"(?:https?://)?(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)")
CHANNEL_LINK_RE = re.compile(r"(?:https?://)?(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)")
USER_MENTION_RE = re.compile(r"<@!?(\d+)>")
ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")
ANY_MENTION_RE = re.compile(r"<@!?\d+>|<@&\d+>")
MAX_CHUNK = 2000

EMBED_COLOR = 0x2B2D31


def _load_store():
    if os.path.exists(STORE_FILE):
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_store(data):
    os.makedirs(os.path.dirname(STORE_FILE), exist_ok=True)
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_bridges():
    if os.path.exists(BRIDGE_FILE):
        try:
            with open(BRIDGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_bridges(data):
    os.makedirs(os.path.dirname(BRIDGE_FILE), exist_ok=True)
    with open(BRIDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_roles():
    if os.path.exists(ROLE_FILE):
        try:
            with open(ROLE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_roles(data):
    os.makedirs(os.path.dirname(ROLE_FILE), exist_ok=True)
    with open(ROLE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def has_forward_access():
    async def predicate(ctx):
        if ctx.author.guild_permissions.manage_messages:
            return True
        cog = ctx.cog
        if cog is None:
            return False
        allowed = cog.roles.get(str(ctx.guild.id), [])
        return any(role.id in allowed for role in getattr(ctx.author, "roles", []))
    return commands.check(predicate)


def chunk_text(text, size=MAX_CHUNK):
    if not text:
        return []
    return [text[i:i + size] for i in range(0, len(text), size)]


class ForwardDraft:
    def __init__(self, source=None):
        self.source = source
        self.content = source.content if source else ""
        self.attachments = list(source.attachments) if source else []
        self.embeds = list(source.embeds) if source else []
        self.mode = "bot"
        self.webhook_name = None
        self.webhook_avatar = None
        self.pings = []
        self.keep_embeds = False

    @property
    def author(self):
        return self.source.author if self.source else None


class ForwardEditorView(discord.ui.View):
    def __init__(self, cog, ctx, draft, target, sent_message=None):
        super().__init__(timeout=600)
        self.cog = cog
        self.ctx = ctx
        self.draft = draft
        self.target = target
        self.sent_message = sent_message
        self.message = None
        self._refresh_labels()

    def _refresh_labels(self):
        self.mode_btn.label = f"Mode: {'Webhook' if self.draft.mode == 'webhook' else 'Bot'}"
        self.embed_btn.label = f"Embeds: {'On' if self.draft.keep_embeds else 'Off'}"
        self.save_btn.label = "Save Changes" if self.sent_message else "Send"

    def build_embed(self):
        d = self.draft
        if self.sent_message:
            desc = "Editing an existing forwarded message. Use the buttons to change it, then Save."
        else:
            desc = "Customize the forwarded message, then press Send."
        embed = discord.Embed(title=f"{FORWARD} Forward Editor", description=desc, color=EMBED_COLOR)
        src = d.author.mention if d.author else "*unknown*"
        target_line = f"[#{self.target.name}]({self.target.jump_url}) • {self.target.guild.name}"
        embed.add_field(name=f"{MESSAGE} Source", value=f"{src} in {self.ctx.channel.mention}", inline=False)
        embed.add_field(name=f"{CHANNEL} Target", value=target_line, inline=True)
        identity = "Webhook"
        if d.mode == "webhook":
            who = d.webhook_name or (d.author.display_name if d.author else "Forwarder")
            identity = f"Webhook ({who})"
        embed.add_field(name=f"{SYSTEM} Mode", value=identity, inline=True)
        embed.add_field(name=f"{MENTION} Pings", value=(" ".join(d.pings) if d.pings else "None"), inline=True)
        embed.add_field(name=f"{TICK} Attachments", value=str(len(d.attachments)), inline=True)
        body = d.content if d.content else "*empty*"
        if len(body) > 1024:
            body = body[:1021] + "..."
        embed.add_field(name=f"{ZMODULE} Content", value=body, inline=False)
        embed.set_footer(text=f"Requested by {self.ctx.author}", icon_url=self.ctx.author.display_avatar.url)
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This editor does not belong to you.", ephemeral=True)
            return False
        return True

    async def refresh(self, interaction):
        self._refresh_labels()
        try:
            await self.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

    # -- Modals -------------------------------------------------------
    @discord.ui.button(label="Edit Text", style=discord.ButtonStyle.primary, row=0)
    async def edit_text(self, interaction, button):
        await interaction.response.send_modal(_TextModal(self))

    @discord.ui.button(label="Replace Word", style=discord.ButtonStyle.primary, row=0)
    async def replace_word(self, interaction, button):
        await interaction.response.send_modal(_ReplaceModal(self))

    @discord.ui.button(label="Edit Pings", style=discord.ButtonStyle.primary, row=0)
    async def edit_pings(self, interaction, button):
        await interaction.response.send_modal(_PingModal(self))

    @discord.ui.button(label="Mode: Bot", style=discord.ButtonStyle.secondary, row=1)
    async def mode_btn(self, interaction, button):
        self.draft.mode = "webhook" if self.draft.mode == "bot" else "bot"
        if self.draft.mode == "webhook" and not self.target.permissions_for(self.target.guild.me).manage_webhooks:
            self.draft.mode = "bot"
            await interaction.response.send_message("I need `Manage Webhooks` in the target channel to use webhook mode.", ephemeral=True)
            return await self.refresh(interaction)
        await interaction.response.defer()
        await self.refresh(interaction)

    @discord.ui.button(label="Embeds: Off", style=discord.ButtonStyle.secondary, row=1)
    async def embed_btn(self, interaction, button):
        self.draft.keep_embeds = not self.draft.keep_embeds
        await interaction.response.defer()
        await self.refresh(interaction)

    @discord.ui.button(label="Set Author", style=discord.ButtonStyle.secondary, row=1)
    async def set_author(self, interaction, button):
        await interaction.response.send_modal(_AuthorModal(self))

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.secondary, row=2)
    async def preview(self, interaction, button):
        await interaction.response.send_message(embed=self._preview_embed(), ephemeral=True)

    @discord.ui.button(label="Send", style=discord.ButtonStyle.success, row=2)
    async def save_btn(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            if self.sent_message:
                ok = await self.cog.apply_edit(self.sent_message, self.draft)
                if not ok:
                    return await interaction.followup.send("I could not edit that message (not mine / missing permissions).", ephemeral=True)
                await interaction.followup.send(f"{TICK} Changes saved: {self.sent_message.jump_url}", ephemeral=True)
            else:
                sent = await self.cog.dispatch(self.target, self.draft)
                await interaction.followup.send(f"{TICK} Forwarded to {self.target.mention}: {sent.jump_url}", ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send("I lack permissions to send in that channel.", ephemeral=True)
        except Exception as e:
            return await interaction.followup.send(f"{CROSS} Failed: `{e}`", ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, interaction, button):
        await interaction.response.defer()
        try:
            await self.message.edit(view=None)
        except Exception:
            pass
        self.stop()

    def _preview_embed(self):
        d = self.draft
        content = self.cog.compose_content(d)
        embed = discord.Embed(title=f"{FORWARD} Preview", description=(content[:4000] or "*empty*"), color=EMBED_COLOR)
        if d.attachments:
            embed.add_field(name="Files", value="\n".join(a.filename for a in d.attachments), inline=False)
        embed.add_field(name="As", value=d.webhook_name or (d.author.display_name if d.author else "Bot"), inline=True)
        embed.add_field(name="Pings", value=" ".join(d.pings) or "None", inline=True)
        return embed


class _TextModal(discord.ui.Modal, title="Edit Forwarded Text"):
    body = discord.ui.TextInput(label="Message content", style=discord.TextStyle.paragraph, required=False, max_length=4000)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view
        if view.draft.content:
            self.body.default = view.draft.content[:4000]

    async def on_submit(self, interaction):
        self.view_ref.draft.content = str(self.body.value)
        await interaction.response.defer()
        await self.view_ref.refresh(interaction)


class _ReplaceModal(discord.ui.Modal, title="Find & Replace"):
    find = discord.ui.TextInput(label="Replace this", placeholder="you", max_length=200)
    repl = discord.ui.TextInput(label="With this", placeholder="me", required=False, max_length=200)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction):
        find, repl = str(self.find.value), str(self.repl.value)
        if find:
            self.view_ref.draft.content = self.view_ref.draft.content.replace(find, repl)
            self.view_ref.draft.pings = [p.replace(find, repl) for p in self.view_ref.draft.pings]
        await interaction.response.defer()
        await self.view_ref.refresh(interaction)


class _PingModal(discord.ui.Modal, title="Edit Pings"):
    pings = discord.ui.TextInput(
        label="Pings to send",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
        placeholder="@user @role @everyone | ids | none",
    )

    def __init__(self, view):
        super().__init__()
        self.view_ref = view
        if view.draft.pings:
            self.pings.default = " ".join(view.draft.pings)

    async def on_submit(self, interaction):
        guild = self.view_ref.target.guild
        self.view_ref.draft.pings = self.view_ref.cog.resolve_pings(guild, str(self.pings.value))
        await interaction.response.defer()
        await self.view_ref.refresh(interaction)


class _AuthorModal(discord.ui.Modal, title="Webhook Author"):
    name = discord.ui.TextInput(label="Display name", required=False, max_length=80)
    avatar = discord.ui.TextInput(label="Avatar URL", required=False)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view
        if view.draft.webhook_name:
            self.name.default = view.draft.webhook_name
        if view.draft.webhook_avatar:
            self.avatar.default = view.draft.webhook_avatar

    async def on_submit(self, interaction):
        self.view_ref.draft.mode = "webhook"
        self.view_ref.draft.webhook_name = str(self.name.value) or None
        self.view_ref.draft.webhook_avatar = str(self.avatar.value) or None
        await interaction.response.defer()
        await self.view_ref.refresh(interaction)


class Forward(commands.Cog, name="Forward"):
    def __init__(self, bot):
        self.bot = bot
        self.store = _load_store()
        self.bridges = _load_bridges()
        self.roles = _load_roles()

    def cog_unload(self):
        _save_store(self.store)
        _save_bridges(self.bridges)
        _save_roles(self.roles)

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.NoPrivateMessage):
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send(view=CV2(f"{CROSS} No Permission", "You need `Manage Messages` or the configured forward role to use this command."))

    # -- Helpers ------------------------------------------------------
    async def resolve_channel(self, channel_id):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return channel if hasattr(channel, "send") else None

    async def fetch_forwarded(self, channel_id, message_id):
        channel = await self.resolve_channel(channel_id)
        if channel is None:
            return None
        try:
            return await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    def find_forwarded_for(self, source_channel_id, source_message_id):
        link = self.bridges.get(str(source_channel_id))
        if not link:
            return None
        for item in reversed(link.get("history", [])):
            if item.get("source") == source_message_id:
                return int(link["target_channel_id"]), item["target"]
        return None

    async def find_last_forwarded(self, channel):
        return await self.latest_forwarded_in(channel.id)

    async def latest_forwarded_in(self, channel_id):
        for link in self.bridges.values():
            if int(link["target_channel_id"]) == channel_id and link.get("history"):
                return await self.fetch_forwarded(channel_id, link["history"][-1]["target"])
        link = self.bridges.get(str(channel_id))
        if link and link.get("history"):
            return await self.fetch_forwarded(int(link["target_channel_id"]), link["history"][-1]["target"])
        return None

    async def latest_forwarded_with_role(self, role_id):
        needle = f"<@&{role_id}>"
        for link in self.bridges.values():
            channel_id = int(link["target_channel_id"])
            for item in reversed(link.get("history", [])):
                message = await self.fetch_forwarded(channel_id, item["target"])
                if message and needle in (message.content or ""):
                    return message
        return None

    def bridge_for_channel(self, channel_id):
        key = str(channel_id)
        if key in self.bridges:
            return key, self.bridges[key]
        for source_id, link in self.bridges.items():
            if int(link["target_channel_id"]) == channel_id:
                return source_id, link
        return None, None

    def apply_rules(self, link, content):
        for rule in link.get("replacements", []):
            content = (content or "").replace(rule["find"], rule["replace"])
        return content

    def save_rule(self, link, find, replace):
        rules = link.setdefault("replacements", [])
        for rule in rules:
            if rule.get("find") == find:
                rule["replace"] = replace
                return
        rules.append({"find": find, "replace": replace})

    def _looks_like_target(self, token):
        if not token:
            return False
        if MESSAGE_LINK_RE.search(token) or CHANNEL_LINK_RE.search(token):
            return True
        if re.fullmatch(r"<[#@][!&]?\d+>", token):
            return True
        return token.isdigit() and 15 <= len(token) <= 21

    def resolve_mention_token(self, guild, token):
        if not token:
            return token
        if ANY_MENTION_RE.fullmatch(token) or re.fullmatch(r"<#\d+>", token):
            return token
        if token.startswith("@"):
            name = token[1:]
            if name.lower() in ("everyone", "here"):
                return token
            if name.isdigit():
                return f"<@{name}>" if guild.get_member(int(name)) else f"<@&{name}>"
            member = discord.utils.find(lambda m: m.name.lower() == name.lower() or m.display_name.lower() == name.lower(), guild.members)
            if member:
                return member.mention
            role = discord.utils.find(lambda r: r.name.lower() == name.lower(), guild.roles)
            if role:
                return role.mention
            return token
        if token.startswith("#"):
            name = token[1:]
            if name.isdigit():
                return f"<#{name}>"
            channel = discord.utils.find(lambda c: c.name.lower() == name.lower(), guild.channels)
            if channel:
                return channel.mention
            return token
        return token

    def role_mention(self, guild, token):
        if not token:
            return None
        match = re.search(r"<@&(\d+)>", token)
        if match:
            return f"<@&{match.group(1)}>"
        name = token.strip().lstrip("@").strip()
        if name.isdigit() and 15 <= len(name) <= 21:
            return f"<@&{name}>"
        if guild is not None:
            role = discord.utils.find(lambda r: r.name.lower() == name.lower(), guild.roles)
            if role:
                return role.mention
        return None

    async def resolve_edit_target(self, ctx, token):
        if not token:
            return None
        match = MESSAGE_LINK_RE.search(token)
        if match:
            return await self.fetch_forwarded(int(match.group(2)), int(match.group(3)))
        match = CHANNEL_LINK_RE.search(token)
        if match:
            return await self.latest_forwarded_in(int(match.group(2)))
        match = re.search(r"<#(\d+)>", token)
        if match:
            return await self.latest_forwarded_in(int(match.group(1)))
        match = re.search(r"<@&(\d+)>", token)
        if match:
            return await self.latest_forwarded_with_role(int(match.group(1)))
        if token.startswith("@"):
            resolved = self.resolve_mention_token(ctx.guild, token)
            match = re.search(r"<@&(\d+)>", resolved)
            if match:
                return await self.latest_forwarded_with_role(int(match.group(1)))
        if token.isdigit():
            message = await self.fetch_forwarded(ctx.channel.id, int(token))
            if message is not None:
                return message
            return await self.latest_forwarded_in(int(token))
        return None

    def _is_forward_command(self, message):
        if not message.content:
            return False
        prefixes = self.bot.command_prefix
        if callable(prefixes):
            try:
                prefixes = prefixes(self.bot, message)
            except Exception:
                return False
        if isinstance(prefixes, str):
            prefixes = (prefixes,)
        for prefix in prefixes:
            if message.content.startswith(prefix):
                first = message.content[len(prefix):].strip().split(" ", 1)[0].lower()
                return first in ("forward", "fwd")
        return False

    async def edit_content(self, message, new_content):
        try:
            if message.webhook_id is not None:
                webhook = await self.get_webhook(message.channel)
                if not webhook or webhook.id != message.webhook_id:
                    return False
                await webhook.edit_message(message.id, content=new_content or "", allowed_mentions=discord.AllowedMentions.none())
                return True
            if message.author.id != self.bot.user.id:
                return False
            await message.edit(content=new_content or "", allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException:
            return False

    async def resolve_source(self, ctx, message):
        if message:
            m = MESSAGE_LINK_RE.search(message)
            if m:
                channel = ctx.guild.get_channel(int(m.group(2))) or await self.bot.fetch_channel(int(m.group(2)))
                return await channel.fetch_message(int(m.group(3)))
            if message.isdigit():
                return await ctx.channel.fetch_message(int(message))
            return None
        ref = ctx.message.reference
        if ref and ref.message_id:
            return await ctx.channel.fetch_message(ref.message_id)
        return None

    async def resolve_target(self, ctx, text):
        """Resolve a target channel from a #mention, ID, channel link (any server), or name."""
        text = (text or "").strip()
        cid = None
        m = re.search(r"<#(\d+)>", text)
        if m:
            cid = int(m.group(1))
        else:
            m = CHANNEL_LINK_RE.search(text)
            if m:
                cid = int(m.group(2))
            elif text.isdigit():
                cid = int(text)
        if cid is not None:
            channel = self.bot.get_channel(cid)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(cid)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    return None
            if not hasattr(channel, "send"):
                return None
            return channel
        name = text.lstrip("#").lower()
        found = discord.utils.find(lambda c: c.name.lower() == name, ctx.guild.text_channels)
        return found

    def resolve_pings(self, guild, text):
        found = []
        if not text or text.strip().lower() in ("none", "clear", "off", "-", "null"):
            return found
        found.extend(m.group(0) for m in ANY_MENTION_RE.finditer(text))
        if re.search(r"@everyone", text, re.I):
            found.append("@everyone")
        if re.search(r"@here", text, re.I):
            found.append("@here")
        cleaned = ANY_MENTION_RE.sub(" ", re.sub(r"@(everyone|here)", " ", text, flags=re.I))
        for token in re.findall(r"@([^\s@,]+)", cleaned):
            if token.isdigit():
                if guild.get_member(int(token)):
                    found.append(f"<@{token}>")
                elif guild.get_role(int(token)):
                    found.append(f"<@&{token}>")
                continue
            member = discord.utils.find(lambda m: m.name.lower() == token.lower() or m.display_name.lower() == token.lower(), guild.members)
            if member:
                found.append(f"<@{member.id}>")
                continue
            role = discord.utils.find(lambda r: r.name.lower() == token.lower(), guild.roles)
            if role:
                found.append(f"<@&{role.id}>")
        for token in re.findall(r"(?<![\d<@&])(\d{5,20})(?![\d>])", cleaned):
            if guild.get_member(int(token)):
                found.append(f"<@{token}>")
            elif guild.get_role(int(token)):
                found.append(f"<@&{token}>")
        seen, out = set(), []
        for f in found:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def compose_content(self, draft):
        if draft.pings:
            head = " ".join(draft.pings)
            return f"{head}\n{draft.content}" if draft.content else head
        return draft.content

    def build_allowed(self, pings):
        if "@everyone" in pings or "@here" in pings:
            return discord.AllowedMentions(everyone=True, users=True, roles=True)
        users = [int(m.group(1)) for p in pings for m in [USER_MENTION_RE.fullmatch(p)] if m]
        roles = [int(m.group(1)) for p in pings for m in [ROLE_MENTION_RE.fullmatch(p)] if m]
        return discord.AllowedMentions(everyone=False, users=users, roles=roles)

    async def get_webhook(self, channel):
        guild_store = self.store.setdefault(str(channel.guild.id), {})
        entry = guild_store.get(str(channel.id))
        if entry:
            url = f"https://discord.com/api/webhooks/{entry['id']}/{entry['token']}"
            try:
                return discord.Webhook.from_url(url, client=self.bot)
            except TypeError:
                try:
                    return discord.Webhook.from_url(url, session=self.bot.http._HTTPClient__session, client=self.bot)
                except Exception:
                    pass
            except Exception:
                pass
        try:
            wh = await channel.create_webhook(name="Forwarder")
        except discord.Forbidden:
            return None
        guild_store[str(channel.id)] = {"id": str(wh.id), "token": wh.token}
        _save_store(self.store)
        return wh

    async def dispatch(self, channel, draft):
        content = self.compose_content(draft)
        chunks = chunk_text(content) or [None]
        files = [await a.to_file() for a in draft.attachments] if draft.attachments else []
        embeds = draft.embeds if draft.keep_embeds else []
        allowed = self.build_allowed(draft.pings)

        if draft.mode == "webhook" and channel.permissions_for(channel.guild.me).manage_webhooks:
            wh = await self.get_webhook(channel)
            if wh:
                name = draft.webhook_name or (draft.author.display_name if draft.author else None)
                avatar = draft.webhook_avatar or (draft.author.display_avatar.url if draft.author else None)
                first = await wh.send(content=chunks[0], username=name, avatar_url=avatar, files=files, embeds=embeds, allowed_mentions=allowed, wait=True)
                for c in chunks[1:]:
                    await wh.send(content=c, username=name, avatar_url=avatar)
                return first

        first = await channel.send(content=chunks[0], files=files, embeds=embeds, allowed_mentions=allowed)
        for c in chunks[1:]:
            await channel.send(content=c)
        return first

    async def apply_edit(self, message, draft):
        content = self.compose_content(draft)
        allowed = self.build_allowed(draft.pings)
        if message.webhook_id is not None:
            wh = await self.get_webhook(message.channel)
            if not wh or wh.id != message.webhook_id:
                return False
            await wh.edit_message(message.id, content=content or "", allowed_mentions=allowed)
            return True
        if message.author.id != self.bot.user.id:
            return False
        await message.edit(content=content or "", allowed_mentions=allowed)
        return True

    # -- Auto forward ------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        link = self.bridges.get(str(message.channel.id))
        if not link:
            return
        if not (message.content or message.attachments or message.embeds):
            return
        if self._is_forward_command(message):
            return
        target = await self.resolve_channel(int(link["target_channel_id"]))
        if target is None or target.id == message.channel.id:
            return
        draft = ForwardDraft(message)
        draft.keep_embeds = bool(message.embeds)
        if link.get("replacements"):
            draft.content = self.apply_rules(link, draft.content)
            draft.pings = [self.apply_rules(link, ping) for ping in draft.pings]
        if target.permissions_for(target.guild.me).manage_webhooks:
            draft.mode = "webhook"
        else:
            draft.mode = "bot"
        try:
            sent = await self.dispatch(target, draft)
        except discord.HTTPException:
            return
        history = link.setdefault("history", [])
        history.append({"source": message.id, "target": sent.id})
        del history[:-50]
        _save_bridges(self.bridges)

    async def _create_bridge(self, ctx, source, target):
        if not self._has_manage_access(ctx.author):
            return await ctx.send(view=CV2(f"{CROSS} No Permission", "You need `Manage Messages` or the configured forward role to do this."))
        source_channel = await self.resolve_target(ctx, source)
        target_channel = await self.resolve_target(ctx, target)
        if source_channel is None or target_channel is None:
            return await ctx.send(view=CV2(f"{CROSS} Bad Channel", "I couldn't find one of those channels. Use `#mention`, channel ID, a channel link, or a channel name. The target may be in another server I'm in."))
        if source_channel.id == target_channel.id:
            return await ctx.send(view=CV2(f"{CROSS} Same Channel", "The source and target channels must be different."))
        existing = self.bridges.get(str(source_channel.id), {})
        self.bridges[str(source_channel.id)] = {
            "guild_id": source_channel.guild.id,
            "target_channel_id": target_channel.id,
            "target_guild_id": target_channel.guild.id,
            "history": existing.get("history", []),
            "replacements": existing.get("replacements", []),
        }
        _save_bridges(self.bridges)
        await ctx.send(view=CV2(f"{FORWARD} Forwarding Enabled", f"Every message in {source_channel.mention} will now be forwarded to {target_channel.mention} ({target_channel.guild.name}).\nUse `{ctx.clean_prefix}forward stop {source_channel.mention}` to stop."))

    def _has_manage_access(self, member):
        if member.guild_permissions.manage_messages:
            return True
        return any(role.id in self.roles.get(str(member.guild.id), []) for role in getattr(member, "roles", []))

    async def _edit_role(self, ctx, source_token, target_token):
        if not source_token or not target_token:
            return await ctx.send(view=CV2(f"{CROSS} Missing Roles", "Usage: `forward edit role <@SourceRole|id|name> <@TargetRole|id|name>`."))
        source_key, link = self.bridge_for_channel(ctx.channel.id)
        source_guild = target_guild = ctx.guild
        if link is not None:
            source_guild = self.bot.get_guild(int(link.get("guild_id", 0))) or ctx.guild
            target_guild = self.bot.get_guild(int(link.get("target_guild_id", 0))) or ctx.guild
        find = self.role_mention(source_guild, source_token)
        replace = self.role_mention(target_guild, target_token)
        if find is None:
            return await ctx.send(view=CV2(f"{CROSS} Bad Source Role", "I couldn't read the source role. Mention it, or pass its name or ID."))
        if replace is None:
            return await ctx.send(view=CV2(f"{CROSS} Bad Target Role", "I couldn't read the target role. Mention it, or pass its name or ID."))

        target_message = None
        if link is not None:
            self.save_rule(link, find, replace)
            _save_bridges(self.bridges)
            target_message = await self.latest_forwarded_in(int(link["target_channel_id"]))
        if target_message is None:
            target_message = await self.find_last_forwarded(ctx.channel)

        edited = False
        if target_message is not None:
            old_content = target_message.content or ""
            new_content = old_content.replace(find, replace)
            if new_content != old_content:
                edited = await self.edit_content(target_message, new_content)

        if link is None and not edited:
            return await ctx.send(view=CV2(f"{CROSS} No Forward", "This channel is not part of an active forward. Set one up with `forward <#source> <#target>` first."))
        note = " Saved and applied to future forwards." if link is not None else ""
        if edited:
            note += " Also updated the latest forwarded message."
        await ctx.send(view=CV2(f"{TICK} Role Mapping Saved", f"{find} → {replace}.{note}"))

    # -- Commands -----------------------------------------------------
    def _help_view(self, ctx):
        p = ctx.clean_prefix
        listing = "\n".join([
            f"`{p}forward <#source> <#target>` — auto-forward every message from one channel to another (channel mention, ID, name, or link; works across servers)",
            f"`{p}forward stop <#source>` — stop auto-forwarding that source channel",
            f"`{p}forward edit <find> <replace>` — replace a word now and save it for every future forwarded message",
            f"`{p}forward edit <message link|channel|role> <find> <replace>` — pick which forwarded message to edit",
            f"`{p}forward edit role <@SourceRole> <@TargetRole>` — remap a role ping (fixes `@unknown-role`) now and for future forwards",
            f"`{p}forward role <@role>` — allow a role to use the forward commands (`off` to clear)",
            f"`{p}forward rules [clear]` — list or clear the saved word replacements for this channel",
            f"`{p}forward send <#channel|id|link> [message link/id]` — forward a message with a live editor",
            f"`{p}forward raw <#channel|id|link> <text>` — quickly send/edit text with the editor (no source message)",
            "",
            "Anywhere a `<#channel>` appears you can also use a channel ID, name, or link. `find`/`replace` accept `@role`, `@user`, `#channel` mentions too.",
            "**Editor buttons:** Edit Text, Replace Word (change a word), Edit Pings (change mentions), Mode (Bot/Webhook — webhook uses the original author's name & avatar), Embeds, Set Author, Preview, Send.",
        ])
        return CV2(f"{FORWARD} Forward Commands", listing)

    @commands.group(name="forward", aliases=["fwd"], invoke_without_command=True)
    @commands.guild_only()
    async def forward(self, ctx, source: str = None, target: str = None):
        if ctx.invoked_subcommand is not None:
            return
        if source and target:
            return await self._create_bridge(ctx, source, target)
        await ctx.send(view=self._help_view(ctx))

    @forward.command(name="help", description="Show all forward commands")
    @commands.guild_only()
    async def help(self, ctx):
        await ctx.send(view=self._help_view(ctx))

    @forward.command(name="rules", description="List or clear the saved word replacements")
    @commands.guild_only()
    @has_forward_access()
    async def rules(self, ctx, action: str = None):
        source_key, link = self.bridge_for_channel(ctx.channel.id)
        if link is None:
            return await ctx.send(view=CV2(f"{CROSS} Not Forwarding", "This channel is not part of an active forward."))
        saved = link.get("replacements", [])
        if action and action.lower() in ("clear", "reset", "off"):
            link["replacements"] = []
            _save_bridges(self.bridges)
            return await ctx.send(view=CV2(f"{TICK} Rules Cleared", "All saved word replacements were removed."))
        if not saved:
            return await ctx.send(view=CV2(f"{FORWARD} Forward Rules", "No saved word replacements for this channel."))
        listing = "\n".join(f"`{r['find']}` → `{r['replace'] or '*empty*'}`" for r in saved)
        await ctx.send(view=CV2(f"{FORWARD} Forward Rules", listing))

    @forward.command(name="stop", description="Stop auto-forwarding a source channel")
    @commands.guild_only()
    @has_forward_access()
    async def stop(self, ctx, source: str = None):
        channel = await self.resolve_target(ctx, source) if source else ctx.channel
        if channel is None:
            return await ctx.send(view=CV2(f"{CROSS} Bad Channel", "I couldn't find that channel."))
        if self.bridges.pop(str(channel.id), None) is None:
            return await ctx.send(view=CV2(f"{CROSS} Not Forwarding", f"{channel.mention} is not being auto-forwarded."))
        _save_bridges(self.bridges)
        await ctx.send(view=CV2(f"{FORWARD} Forwarding Disabled", f"Messages in {channel.mention} will no longer be forwarded."))

    @forward.command(name="role", description="Allow a role to use the forward commands")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def role(self, ctx, *, role: str = None):
        key = str(ctx.guild.id)
        current = self.roles.get(key, [])
        if not role or role.strip().lower() in ("off", "clear", "none", "reset"):
            self.roles.pop(key, None)
            _save_roles(self.roles)
            return await ctx.send(view=CV2(f"{TICK} Forward Role Cleared", "Only members with `Manage Messages` can use the forward commands now."))
        target = None
        match = re.search(r"<@&(\d+)>", role)
        if match:
            target = ctx.guild.get_role(int(match.group(1)))
        else:
            name = role.strip().lstrip("@").lower()
            target = discord.utils.find(lambda r: r.name.lower() == name, ctx.guild.roles)
        if target is None:
            return await ctx.send(view=CV2(f"{CROSS} Bad Role", "I couldn't find that role. Mention it or type its exact name."))
        if target.id in current:
            current.remove(target.id)
        else:
            current.append(target.id)
        self.roles[key] = current
        _save_roles(self.roles)
        mentions = " ".join(f"<@&{r}>" for r in current) or "None"
        await ctx.send(view=CV2(f"{FORWARD} Forward Role Updated", f"Roles allowed to use forward commands: {mentions}"))

    @forward.command(name="send", description="Forward a message with a live editor")
    @commands.guild_only()
    @has_forward_access()
    async def send(self, ctx, target: str, message: str = None):
        channel = await self.resolve_target(ctx, target)
        if channel is None:
            return await ctx.send(view=CV2(f"{CROSS} Bad Target", "I couldn't find that channel. Use a `#mention`, channel ID, or channel link — it can be a channel in another server I'm in."))
        source = await self.resolve_source(ctx, message)
        if source is None:
            return await ctx.send(view=CV2(f"{CROSS} No Message", "Reply to the message you want to forward, or pass a message link / ID.\nUsage: `forward send <#channel|id|link> [message link/id]`"))
        draft = ForwardDraft(source)
        if source.author and channel.permissions_for(channel.guild.me).manage_webhooks:
            draft.mode = "webhook"
        view = ForwardEditorView(self, ctx, draft, channel)
        view.message = await ctx.send(embed=view.build_embed(), view=view)

    @forward.command(name="raw", description="Send editable text without a source message")
    @commands.guild_only()
    @has_forward_access()
    async def raw(self, ctx, target: str, *, text: str):
        channel = await self.resolve_target(ctx, target)
        if channel is None:
            return await ctx.send(view=CV2(f"{CROSS} Bad Target", "I couldn't find that channel. Use a `#mention`, channel ID, or channel link — it can be a channel in another server I'm in."))
        draft = ForwardDraft(None)
        draft.content = text
        view = ForwardEditorView(self, ctx, draft, channel)
        view.message = await ctx.send(embed=view.build_embed(), view=view)

    @forward.command(name="edit", description="Quick find & replace edit of a forwarded message")
    @commands.guild_only()
    @has_forward_access()
    async def edit(self, ctx, p1: str = None, p2: str = None, p3: str = None):
        ref = ctx.message.reference
        replied = None
        if ref and ref.message_id and ref.channel_id == ctx.channel.id:
            replied = await self.fetch_forwarded(ctx.channel.id, ref.message_id)
            if replied is not None and replied.webhook_id is None and replied.author.id != self.bot.user.id:
                replied = None

        if p1 is None:
            if replied is None:
                return await ctx.send(view=CV2(f"{CROSS} No Message", "Reply to a forwarded message you want to edit, or use `forward edit <find> <replace>`."))
            draft = ForwardDraft(None)
            draft.content = replied.content
            draft.mode = "webhook" if replied.webhook_id is not None else "bot"
            view = ForwardEditorView(self, ctx, draft, replied.channel, sent_message=replied)
            view.message = await ctx.send(embed=view.build_embed(), view=view)
            return

        if p1.lower() == "role" and p2 is not None and p3 is not None:
            return await self._edit_role(ctx, p2, p3)

        if self._looks_like_target(p1):
            target = await self.resolve_edit_target(ctx, p1)
            find = self.resolve_mention_token(ctx.guild, p2) if p2 is not None else None
            replace = self.resolve_mention_token(ctx.guild, p3) if p3 is not None else None
        elif p3 is not None and re.fullmatch(r"@\S+", p1):
            resolved = self.resolve_mention_token(ctx.guild, p1)
            match = re.search(r"<@&(\d+)>", resolved)
            target = await self.latest_forwarded_with_role(int(match.group(1))) if match else None
            find = self.resolve_mention_token(ctx.guild, p2)
            replace = self.resolve_mention_token(ctx.guild, p3)
        else:
            find, replace = self.resolve_mention_token(ctx.guild, p1), self.resolve_mention_token(ctx.guild, p2)
            target = replied
            if target is None and ref and ref.message_id:
                found = self.find_forwarded_for(ctx.channel.id, ref.message_id)
                if found:
                    target = await self.fetch_forwarded(*found)
            if target is None:
                target = await self.find_last_forwarded(ctx.channel)

        if find is None or replace is None:
            return await ctx.send(view=CV2(f"{CROSS} Missing Text", "Usage: `forward edit [message link|channel|role] <find> <replace>`."))
        if replace.lower() == "none":
            replace = ""

        source_key, link = (None, None)
        if target is not None:
            source_key, link = self.bridge_for_channel(target.channel.id)
        if link is None:
            source_key, link = self.bridge_for_channel(ctx.channel.id)
        if link is not None:
            self.save_rule(link, find, replace)
            _save_bridges(self.bridges)

        if target is None:
            if link is None:
                return await ctx.send(view=CV2(f"{CROSS} No Source", "I couldn't find a forwarded message or an active forward here. Set one up with `forward <#source> <#target>` first."))
            return await ctx.send(view=CV2(f"{TICK} Rule Saved", f"`{find}` → `{replace or '*empty*'}` is now applied to every future forwarded message in that channel."))

        old_content = target.content or ""
        new_content = old_content.replace(find, replace)
        if new_content == old_content:
            if link is not None:
                return await ctx.send(view=CV2(f"{INFO} Rule Saved", f"`{find}` → `{replace or '*empty*'}` was saved and will apply to future forwarded messages."))
            return await ctx.send(view=CV2(f"{INFO} Nothing Changed", f"`{find}` was not found in the forwarded message."))
        if not await self.edit_content(target, new_content):
            return await ctx.send(view=CV2(f"{CROSS} Not Editable", "I can only edit messages I sent or messages sent by my webhook."))
        saved = " Saved for future messages too." if link is not None else ""
        return await ctx.send(view=CV2(f"{TICK} Message Edited", f"Updated {target.jump_url} to:\n{new_content or '*empty*'}{saved}"))


async def setup(bot):
    await bot.add_cog(Forward(bot))
