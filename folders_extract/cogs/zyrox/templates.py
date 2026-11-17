# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█░█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
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

import discord
from utils.emoji import CROSS, TICK, MESSAGE
from discord.ext import commands
from discord.ui import LayoutView, TextDisplay, Separator, ActionRow
from difflib import get_close_matches
import aiosqlite
from utils.Tools import *
from utils.cv2 import build_container
from utils.config import *
from utils.config import OWNER_IDS


REPORT_THRESHOLD = 5


class CV2(LayoutView):
    def __init__(self, title, *sections):
        super().__init__(timeout=None)
        items = [TextDisplay(f"**{title}**")]
        for s in sections:
            if s:
                items.append(Separator(visible=True))
                items.append(TextDisplay(str(s)))
        self.add_item(build_container(*items))


class Templates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.init_db())

    def help_custom(self):
        return MESSAGE, "Templates", "Save, share and report global templates"

    async def is_owner(self, user):
        if user.id in OWNER_IDS:
            return True
        try:
            return await self.bot.is_owner(user)
        except Exception:
            return False

    async def init_db(self):
        async with aiosqlite.connect("db/templates.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS templates (
                    name TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    author_id INTEGER,
                    uses INTEGER DEFAULT 0,
                    reports INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS template_reports (
                    name TEXT,
                    reporter_id INTEGER,
                    reason TEXT,
                    PRIMARY KEY (name, reporter_id)
                )
            """)
            await db.commit()

    async def get_template(self, name):
        async with aiosqlite.connect("db/templates.db") as db:
            cursor = await db.execute(
                "SELECT name, content, author_id, uses, reports FROM templates WHERE name = ?",
                (name,)
            )
            return await cursor.fetchone()

    async def get_templates(self):
        async with aiosqlite.connect("db/templates.db") as db:
            cursor = await db.execute(
                "SELECT name, content, author_id, uses, reports FROM templates ORDER BY name"
            )
            return await cursor.fetchall()

    async def notify_owners(self, guild, name, author_id, reports):
        targets = set(OWNER_IDS)
        if self.bot.owner_id:
            targets.add(self.bot.owner_id)
        embed = discord.Embed(
            title="Template Reported",
            description=f"Template `{name}` has reached **{reports}** reports.",
            color=0xFF0000
        )
        embed.add_field(name="Server", value=f"{guild.name} (`{guild.id}`)", inline=False)
        embed.add_field(name="Author", value=f"<@{author_id}> (`{author_id}`)", inline=False)
        embed.add_field(name="Action", value=f"Use `template delete {name}` to remove it.", inline=False)
        for oid in targets:
            try:
                user = self.bot.get_user(oid) or await self.bot.fetch_user(oid)
            except discord.NotFound:
                continue
            if user is None:
                continue
            try:
                await user.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                continue

    @commands.group(name="template", aliases=["templates", "tpl"], invoke_without_command=True, help="Save, send and manage global templates.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 3, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    async def template(self, ctx, *, name: str = None):
        if name is None or not name.strip():
            await ctx.send_help(ctx.command)
            ctx.command.reset_cooldown(ctx)
            return

        name = " ".join(name.strip().lower().split())
        data = await self.get_template(name)
        if data is None:
            names = [row[0] for row in await self.get_templates()]
            matches = get_close_matches(name, names, n=3)
            hint = ""
            if matches:
                hint = "\n\nDid you mean: " + ", ".join(f"`{m}`" for m in matches)
            await ctx.send(view=CV2(
                f"{CROSS} Template Not Found",
                f"No template named `{name}` exists.{hint}\n\n➜ Use `{ctx.prefix}template show` to view all templates."
            ))
            return

        _name, content, author_id, uses, reports = data
        async with aiosqlite.connect("db/templates.db") as db:
            await db.execute("UPDATE templates SET uses = uses + 1 WHERE name = ?", (name,))
            await db.commit()

        await ctx.reply(content, mention_author=False)

    @template.command(name="save", aliases=["create", "add", "new"], help="Save a new global template.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    async def template_save(self, ctx, *, args: str):
        if "|" not in args:
            await ctx.send(view=CV2(
                f"{CROSS} Invalid Format",
                f"Use: `{ctx.prefix}template save <name> | <content>`\n\nExample: `{ctx.prefix}template save gaming rules | 1. Be respectful...`"
            ))
            return

        raw_name, content = args.split("|", 1)
        name = " ".join(raw_name.strip().lower().split())
        content = content.strip()

        if not name:
            await ctx.send(view=CV2(f"{CROSS} Invalid Name", "You must provide a template name."))
            return
        if len(name) > 50:
            await ctx.send(view=CV2(f"{CROSS} Invalid Name", "Template names must be **50** characters or fewer."))
            return
        if not content:
            await ctx.send(view=CV2(f"{CROSS} Empty Content", "Your template content cannot be empty."))
            return
        if len(content) > 2000:
            await ctx.send(view=CV2(f"{CROSS} Too Long", "Template content must be **2000** characters or fewer."))
            return

        async with aiosqlite.connect("db/templates.db") as db:
            cursor = await db.execute("SELECT 1 FROM templates WHERE name = ?", (name,))
            if await cursor.fetchone() is not None:
                await ctx.send(view=CV2(
                    "__Template Already Exists!__",
                    f"{CROSS} A template named `{name}` already exists.\n\n➜ Use `{ctx.prefix}template delete {name}` to remove it first."
                ))
                return
            await db.execute(
                "INSERT INTO templates (name, content, author_id, uses, reports) VALUES (?, ?, ?, 0, 0)",
                (name, content, ctx.author.id)
            )
            await db.commit()

        await ctx.send(view=CV2(
            f"{TICK} Template Saved",
            f"Template `{name}` is now available in **every server**.\n\n➜ Send it with `{ctx.prefix}template {name}`."
        ))

    @template.command(name="delete", aliases=["remove", "del"], help="Delete a template (author or bot owner only).")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    async def template_delete(self, ctx, *, name: str):
        name = " ".join(name.strip().lower().split())
        data = await self.get_template(name)
        if data is None:
            await ctx.send(view=CV2(f"{CROSS} Template Not Found", f"No template named `{name}` exists."))
            return

        _name, content, author_id, uses, reports = data
        if ctx.author.id != author_id and not await self.is_owner(ctx.author):
            await ctx.send(view=CV2(
                f"{CROSS} Not Allowed",
                "Only the template author or a bot owner can delete this template."
            ))
            return

        async with aiosqlite.connect("db/templates.db") as db:
            await db.execute("DELETE FROM templates WHERE name = ?", (name,))
            await db.execute("DELETE FROM template_reports WHERE name = ?", (name,))
            await db.commit()

        await ctx.send(view=CV2(f"{TICK} Template Deleted", f"Template `{name}` has been deleted globally."))

    @template.command(name="show", aliases=["list", "all"], help="Show all global templates.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    async def template_show(self, ctx):
        rows = await self.get_templates()
        if not rows:
            await ctx.send(view=CV2(
                "Templates",
                f"{CROSS} There are no templates saved yet.\n\n➜ Create one with `{ctx.prefix}template save <name> | <content>`."
            ))
            return

        listed = rows[:40]
        text = "\n".join(f"• `{r[0]}`" for r in listed)
        if len(rows) > 40:
            text += f"\n\n…and **{len(rows) - 40}** more."
        await ctx.send(view=CV2(
            f"Templates ({len(rows)})",
            text,
            f"Use `{ctx.prefix}template <name>` to send one."
        ))

    @template.command(name="info", help="Show details about a template.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    async def template_info(self, ctx, *, name: str):
        name = " ".join(name.strip().lower().split())
        data = await self.get_template(name)
        if data is None:
            await ctx.send(view=CV2(f"{CROSS} Template Not Found", f"No template named `{name}` exists."))
            return

        _name, content, author_id, uses, reports = data
        await ctx.send(view=CV2(
            f"Template: {name}",
            f"**Author:** <@{author_id}>\n"
            f"**Uses:** `{uses}`\n"
            f"**Reports:** `{reports}`"
        ))

    @template.command(name="report", help="Report a template. Include a reason after a |.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 10, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    async def template_report(self, ctx, *, args: str):
        if "|" in args:
            raw_name, reason = args.split("|", 1)
            reason = reason.strip()
        else:
            raw_name, reason = args, None

        name = " ".join(raw_name.strip().lower().split())
        data = await self.get_template(name)
        if data is None:
            await ctx.send(view=CV2(f"{CROSS} Template Not Found", f"No template named `{name}` exists."))
            return

        if data[2] == ctx.author.id:
            await ctx.send(view=CV2(f"{CROSS} Not Allowed", "You cannot report your own template."))
            return

        async with aiosqlite.connect("db/templates.db") as db:
            cursor = await db.execute(
                "SELECT 1 FROM template_reports WHERE name = ? AND reporter_id = ?",
                (name, ctx.author.id)
            )
            if await cursor.fetchone() is not None:
                await ctx.send(view=CV2(f"{CROSS} Already Reported", "You have already reported this template."))
                return

            await db.execute(
                "INSERT INTO template_reports (name, reporter_id, reason) VALUES (?, ?, ?)",
                (name, ctx.author.id, reason)
            )
            await db.execute("UPDATE templates SET reports = reports + 1 WHERE name = ?", (name,))
            await db.commit()

            cursor = await db.execute("SELECT reports FROM templates WHERE name = ?", (name,))
            count = (await cursor.fetchone())[0]

        await ctx.send(view=CV2(
            f"{TICK} Template Reported",
            f"Thanks! `{name}` now has **{count}** report(s)."
        ))

        if count == REPORT_THRESHOLD:
            await self.notify_owners(ctx.guild, name, data[2], count)

    @template.command(name="reports", help="List reported templates (bot owner only).")
    @blacklist_check()
    @ignore_check()
    @commands.guild_only()
    async def template_reports(self, ctx):
        if not await self.is_owner(ctx.author):
            await ctx.send(view=CV2(f"{CROSS} Not Allowed", "Only bot owners can view reported templates."))
            return

        async with aiosqlite.connect("db/templates.db") as db:
            cursor = await db.execute(
                "SELECT name, reports, author_id FROM templates WHERE reports > 0 ORDER BY reports DESC"
            )
            rows = await cursor.fetchall()

        if not rows:
            await ctx.send(view=CV2("Reported Templates", "There are no reported templates."))
            return

        text = "\n".join(f"• `{r[0]}` — **{r[1]}** report(s) — <@{r[2]}>" for r in rows[:40])
        await ctx.send(view=CV2(
            f"Reported Templates ({len(rows)})",
            text,
            f"Delete any with `{ctx.prefix}template delete <name>`."
        ))

    @template.command(name="clearreports", help="Clear the reports on a template (bot owner only).")
    @blacklist_check()
    @ignore_check()
    @commands.guild_only()
    async def template_clearreports(self, ctx, *, name: str):
        if not await self.is_owner(ctx.author):
            await ctx.send(view=CV2(f"{CROSS} Not Allowed", "Only bot owners can clear reports."))
            return

        name = " ".join(name.strip().lower().split())
        data = await self.get_template(name)
        if data is None:
            await ctx.send(view=CV2(f"{CROSS} Template Not Found", f"No template named `{name}` exists."))
            return

        async with aiosqlite.connect("db/templates.db") as db:
            await db.execute("DELETE FROM template_reports WHERE name = ?", (name,))
            await db.execute("UPDATE templates SET reports = 0 WHERE name = ?", (name,))
            await db.commit()

        await ctx.send(view=CV2(f"{TICK} Reports Cleared", f"All reports for `{name}` have been cleared."))


async def setup(bot):
    await bot.add_cog(Templates(bot))
