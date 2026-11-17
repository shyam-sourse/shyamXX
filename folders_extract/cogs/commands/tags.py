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
from utils.emoji import CROSS, TICK, ZSAFE, ZWARNING
from discord.ext import commands
from discord.ui import LayoutView, TextDisplay, Separator, ActionRow
from difflib import get_close_matches
import aiosqlite
from utils.Tools import *
from utils.cv2 import build_container
from utils.config import *


class CV2(LayoutView):
    def __init__(self, title, *sections):
        super().__init__(timeout=None)
        items = [TextDisplay(f"**{title}**")]
        for s in sections:
            if s:
                items.append(Separator(visible=True))
                items.append(TextDisplay(str(s)))
        self.add_item(build_container(*items))


class Tags(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.init_db())

    async def init_db(self):
        async with aiosqlite.connect("db/tags.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    guild_id INTEGER,
                    name TEXT,
                    content TEXT,
                    author_id INTEGER,
                    uses INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, name)
                )
            """)
            await db.commit()

    async def get_tag(self, guild_id, name):
        async with aiosqlite.connect("db/tags.db") as db:
            cursor = await db.execute(
                "SELECT content, author_id, uses FROM tags WHERE guild_id = ? AND name = ?",
                (guild_id, name)
            )
            return await cursor.fetchone()

    async def get_tag_names(self, guild_id):
        async with aiosqlite.connect("db/tags.db") as db:
            cursor = await db.execute(
                "SELECT name FROM tags WHERE guild_id = ? ORDER BY name",
                (guild_id,)
            )
            return [row[0] for row in await cursor.fetchall()]

    @commands.group(name="tag", aliases=["tags"], invoke_without_command=True, help="Send, create and manage custom tags.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 3, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    async def tag(self, ctx, *, name: str = None):
        if name is None or not name.strip():
            await ctx.send_help(ctx.command)
            ctx.command.reset_cooldown(ctx)
            return

        name = name.strip().lower()
        data = await self.get_tag(ctx.guild.id, name)
        if data is None:
            names = await self.get_tag_names(ctx.guild.id)
            matches = get_close_matches(name, names, n=3)
            hint = ""
            if matches:
                hint = "\n\nDid you mean: " + ", ".join(f"`{m}`" for m in matches)
            await ctx.send(view=CV2(
                f"{CROSS} Tag Not Found",
                f"No tag named `{name}` exists in this server.{hint}\n\n➜ Use `{ctx.prefix}tag show` to view all tags."
            ))
            return

        content, author_id, uses = data
        async with aiosqlite.connect("db/tags.db") as db:
            await db.execute("UPDATE tags SET uses = uses + 1 WHERE guild_id = ? AND name = ?", (ctx.guild.id, name))
            await db.commit()

        await ctx.reply(content, mention_author=False)

    @tag.command(name="create", aliases=["add"], help="Create a new tag.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def tag_create(self, ctx, name: str, *, content: str):
        name = name.strip().lower()
        if len(name) > 50:
            await ctx.send(view=CV2(f"{CROSS} Invalid Name", "Tag names must be **50** characters or fewer."))
            return
        if len(content) > 2000:
            await ctx.send(view=CV2(f"{CROSS} Too Long", "Tag content must be **2000** characters or fewer."))
            return

        async with aiosqlite.connect("db/tags.db") as db:
            cursor = await db.execute("SELECT 1 FROM tags WHERE guild_id = ? AND name = ?", (ctx.guild.id, name))
            if await cursor.fetchone() is not None:
                await ctx.send(view=CV2(
                    "__Tag Already Exists!__",
                    f"{CROSS} A tag named `{name}` already exists.\n\n➜ Use `{ctx.prefix}tag delete {name}` to remove it first."
                ))
                return
            await db.execute(
                "INSERT INTO tags (guild_id, name, content, author_id, uses) VALUES (?, ?, ?, ?, 0)",
                (ctx.guild.id, name, content, ctx.author.id)
            )
            await db.commit()

        await ctx.send(view=CV2(
            f"{TICK} Tag Created",
            f"Tag `{name}` has been created.\n\n➜ Send it with `{ctx.prefix}tag {name}`."
        ))

    @tag.command(name="delete", aliases=["remove", "del"], help="Delete an existing tag.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def tag_delete(self, ctx, *, name: str):
        name = name.strip().lower()
        async with aiosqlite.connect("db/tags.db") as db:
            cursor = await db.execute("SELECT 1 FROM tags WHERE guild_id = ? AND name = ?", (ctx.guild.id, name))
            if await cursor.fetchone() is None:
                await ctx.send(view=CV2(f"{CROSS} Tag Not Found", f"No tag named `{name}` exists in this server."))
                return
            await db.execute("DELETE FROM tags WHERE guild_id = ? AND name = ?", (ctx.guild.id, name))
            await db.commit()

        await ctx.send(view=CV2(f"{TICK} Tag Deleted", f"Tag `{name}` has been deleted."))

    @tag.command(name="show", aliases=["list", "all"], help="Show all tags in the server.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.guild_only()
    async def tag_show(self, ctx):
        names = await self.get_tag_names(ctx.guild.id)
        if not names:
            await ctx.send(view=CV2(
                "Tags",
                f"{CROSS} There are no tags in this server yet.\n\n➜ Create one with `{ctx.prefix}tag create <name> <message>`."
            ))
            return

        listed = names[:40]
        text = "\n".join(f"• `{n}`" for n in listed)
        if len(names) > 40:
            text += f"\n\n…and **{len(names) - 40}** more."
        await ctx.send(view=CV2(f"Tags ({len(names)})", text, f"Use `{ctx.prefix}tag <name>` to send a tag."))

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        async with aiosqlite.connect("db/tags.db") as db:
            await db.execute("DELETE FROM tags WHERE guild_id = ?", (guild.id,))
            await db.commit()
