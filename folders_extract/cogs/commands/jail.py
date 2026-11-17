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

import discord
from discord.ext import commands, tasks
import sqlite3
from datetime import datetime, timedelta
import re
from utils.cv2 import CV2

DB_FILE = "db/jail.db"

class Jail(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS jailed (
                guild_id TEXT,
                user_id TEXT,
                mod_id TEXT,
                reason TEXT,
                jailed_at TEXT,
                duration INTEGER,
                roles TEXT,
                PRIMARY KEY (guild_id, user_id)
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS jail_settings (
                guild_id TEXT PRIMARY KEY,
                jail_role TEXT,
                jail_channel TEXT,
                mod_role TEXT,
                log_channel TEXT
            );
        """)
        # Ensure roles column exists (safe migration)
        try:
            self.conn.execute("SELECT roles FROM jailed LIMIT 1;")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE jailed ADD COLUMN roles TEXT;")
        self.conn.commit()

        self.jail_check_loop.start()

    def cog_unload(self):
        self.jail_check_loop.cancel()
        self.conn.close()

    def get_setting(self, guild_id, field):
        cursor = self.conn.execute(f"SELECT {field} FROM jail_settings WHERE guild_id = ?", (str(guild_id),))
        row = cursor.fetchone()
        return row[0] if row else None

    def set_setting(self, guild_id, field, value):
        self.conn.execute(f"""
            INSERT INTO jail_settings (guild_id, {field})
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET {field} = excluded.{field}
        """, (str(guild_id), str(value)))
        self.conn.commit()

    def clear_setting(self, guild_id, field):
        self.conn.execute(f"UPDATE jail_settings SET {field} = NULL WHERE guild_id = ?", (str(guild_id),))
        self.conn.commit()

    def parse_duration(self, duration_str: str):
        pattern = re.compile(r'((?P<hours>\d+)h)?((?P<minutes>\d+)m)?')
        match = pattern.fullmatch(duration_str.lower())
        if not match:
            return None
        hours = int(match.group('hours') or 0)
        minutes = int(match.group('minutes') or 0)
        return (hours * 60 + minutes) * 60 if (hours or minutes) else None

    @tasks.loop(minutes=1)
    async def jail_check_loop(self):
        now = datetime.utcnow()
        cursor = self.conn.execute("SELECT guild_id, user_id, duration, jailed_at, roles FROM jailed")
        for guild_id, user_id, duration, jailed_at, roles in cursor.fetchall():
            if not duration:
                continue
            jailed_time = datetime.fromisoformat(jailed_at)
            if (now - jailed_time).total_seconds() >= duration:
                guild = self.bot.get_guild(int(guild_id))
                if guild:
                    member = guild.get_member(int(user_id))
                    if member:
                        await self.unjail_member(guild, member)

    async def unjail_member(self, guild, member):
        jail_role_id = self.get_setting(guild.id, "jail_role")
        if jail_role_id:
            jail_role = guild.get_role(int(jail_role_id))
            if jail_role in member.roles:
                await member.remove_roles(jail_role, reason="Unjailed")

        # Restore old roles
        cursor = self.conn.execute("SELECT roles FROM jailed WHERE guild_id = ? AND user_id = ?", (str(guild.id), str(member.id)))
        row = cursor.fetchone()
        if row and row[0]:
            role_ids = map(int, row[0].split(","))
            roles = [guild.get_role(rid) for rid in role_ids if guild.get_role(rid)]
            await member.add_roles(*roles, reason="Restored previous roles after jail")

        self.conn.execute("DELETE FROM jailed WHERE guild_id = ? AND user_id = ?", (str(guild.id), str(member.id)))
        self.conn.commit()

        try:
            await member.send(f"🔓 You have been unjailed in **{guild.name}**.")
        except:
            pass

        log_channel_id = self.get_setting(guild.id, "log_channel")
        if log_channel_id:
            log_channel = guild.get_channel(int(log_channel_id))
            if log_channel:
                desc = (
                    f"**User:** {member.mention}\n"
                    f"**Time:** <t:{int(datetime.utcnow().timestamp())}:f>"
                )
                await log_channel.send(view=CV2("🔓 Member Unjailed", desc))

    @commands.group(name="jail", invoke_without_command=True, description="Jail a member or configure the jail system")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def jail(self, ctx, member: discord.Member = None, duration: str = None, *, reason="No reason provided"):
        if ctx.invoked_subcommand is not None:
            return
        if member is None:
            p = ctx.clean_prefix
            commands_list = "\n".join([
                f"`{p}jail <member> [duration] [reason]` — jail a member (e.g. `{p}jail @user 1h Spam`)",
                f"`{p}jail role <@role>` — set the jail role",
                f"`{p}jail channel <#channel>` — set the jail channel",
                f"`{p}jail log [#channel]` — set or clear the jail log channel",
                f"`{p}jail mod [@role]` — set or clear the jail moderator role",
                f"`{p}jail settings` — show the current configuration",
                f"`{p}unjail <member>` — remove a member from jail",
                f"`{p}jailhistory <member>` — view a member's jail record",
            ])
            return await ctx.send(view=CV2("🔒 Jail Commands", commands_list))

        jail_role_id = self.get_setting(ctx.guild.id, "jail_role")
        jail_channel_id = self.get_setting(ctx.guild.id, "jail_channel")
        log_channel_id = self.get_setting(ctx.guild.id, "log_channel")

        if not jail_role_id or not jail_channel_id:
            return await ctx.send(view=CV2("⚠️ Configuration Error", "Jail system not fully configured."))

        jail_role = ctx.guild.get_role(int(jail_role_id))
        if not jail_role:
            return await ctx.send(view=CV2("⚠️ Configuration Error", "Jail role does not exist."))

        duration_secs = self.parse_duration(duration) if duration else None
        jailed_at = datetime.utcnow().isoformat()
        roles_str = ",".join(str(r.id) for r in member.roles if r != ctx.guild.default_role)

        self.conn.execute("DELETE FROM jailed WHERE guild_id = ? AND user_id = ?", (str(ctx.guild.id), str(member.id)))
        self.conn.execute("""
            INSERT INTO jailed (guild_id, user_id, mod_id, reason, jailed_at, duration, roles)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (str(ctx.guild.id), str(member.id), str(ctx.author.id), reason, jailed_at, duration_secs, roles_str))
        self.conn.commit()

        try:
            await member.edit(roles=[jail_role], reason="Jailed")
        except discord.Forbidden:
            return await ctx.send(view=CV2("❌ Permission Error", "I don't have permission to change roles."))

        jail_channel = ctx.guild.get_channel(int(jail_channel_id))
        if jail_channel:
            await jail_channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)

        try:
            await member.send(f"🔒 You were jailed in **{ctx.guild.name}**.\n📝 Reason: {reason}\n⏰ Duration: {duration or 'Permanent'}")
        except:
            pass

        await ctx.send(view=CV2("✅ Success", f"🔒 {member.mention} has been jailed {'for ' + duration if duration else 'permanently'}."))

        if log_channel_id:
            log_channel = ctx.guild.get_channel(int(log_channel_id))
            if log_channel:
                desc = (
                    f"**User:** {member.mention}\n"
                    f"**Moderator:** {ctx.author.mention}\n"
                    f"**Reason:** {reason}\n"
                    f"**Duration:** {duration or 'Permanent'}\n"
                    f"**Time:** <t:{int(datetime.utcnow().timestamp())}:f>"
                )
                await log_channel.send(view=CV2("🔒 Member Jailed", desc))

    @jail.command(name="role", aliases=["jailrole"], description="Set the jail role")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def jail_role(self, ctx, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            return await ctx.send(view=CV2("❌ Error", "That role is higher than or equal to my top role, so I can't manage it."))
        self.set_setting(ctx.guild.id, "jail_role", role.id)
        await ctx.send(view=CV2("✅ Jail Role Set", f"Jail role set to {role.mention}."))

    @jail.command(name="channel", aliases=["jailchannel"], description="Set the jail channel")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def jail_channel(self, ctx, channel: discord.TextChannel):
        self.set_setting(ctx.guild.id, "jail_channel", channel.id)
        await ctx.send(view=CV2("✅ Jail Channel Set", f"Jail channel set to {channel.mention}."))

    @jail.command(name="log", aliases=["logchannel", "logs"], description="Set or clear the jail log channel")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def jail_log(self, ctx, channel: discord.TextChannel = None):
        if channel is None:
            self.clear_setting(ctx.guild.id, "log_channel")
            return await ctx.send(view=CV2("✅ Log Channel Cleared", "Jail logging is now disabled."))
        self.set_setting(ctx.guild.id, "log_channel", channel.id)
        await ctx.send(view=CV2("✅ Log Channel Set", f"Jail logs will be sent to {channel.mention}."))

    @jail.command(name="mod", aliases=["modrole"], description="Set or clear the jail moderator role")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def jail_mod(self, ctx, role: discord.Role = None):
        if role is None:
            self.clear_setting(ctx.guild.id, "mod_role")
            return await ctx.send(view=CV2("✅ Mod Role Cleared", "The jail moderator role has been removed."))
        self.set_setting(ctx.guild.id, "mod_role", role.id)
        await ctx.send(view=CV2("✅ Mod Role Set", f"Jail moderator role set to {role.mention}."))

    @jail.command(name="settings", aliases=["config"], description="Show the current jail configuration")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def jail_settings(self, ctx):
        role = self.get_setting(ctx.guild.id, "jail_role")
        channel = self.get_setting(ctx.guild.id, "jail_channel")
        log = self.get_setting(ctx.guild.id, "log_channel")
        mod = self.get_setting(ctx.guild.id, "mod_role")
        desc = (
            f"**Jail Role:** {f'<@&{role}>' if role else '❌ Not set'}\n"
            f"**Jail Channel:** {f'<#{channel}>' if channel else '❌ Not set'}\n"
            f"**Log Channel:** {f'<#{log}>' if log else '❌ Not set'}\n"
            f"**Mod Role:** {f'<@&{mod}>' if mod else '❌ Not set'}\n\n"
            f"`{ctx.clean_prefix}jail role <@role>` • `{ctx.clean_prefix}jail channel <#channel>` • "
            f"`{ctx.clean_prefix}jail log <#channel>`"
        )
        await ctx.send(view=CV2("⚙️ Jail Settings", desc))

    @commands.command(name="unjail")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def unjail(self, ctx, member: discord.Member):
        await self.unjail_member(ctx.guild, member)
        await ctx.send(view=CV2("✅ Success", f"{member.mention} has been unjailed."))

    @commands.command(name="jailhistory")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def jailhistory(self, ctx, member: discord.Member):
        cursor = self.conn.execute("""
            SELECT reason, jailed_at, duration, mod_id FROM jailed
            WHERE guild_id = ? AND user_id = ?
        """, (str(ctx.guild.id), str(member.id)))
        row = cursor.fetchone()
        if row:
            reason, jailed_at, duration, mod_id = row
            mod = ctx.guild.get_member(int(mod_id))
            jailed_time = datetime.fromisoformat(jailed_at)
            
            desc = (
                f"**User:** {member.mention}\n"
                f"**Reason:** {reason}\n"
                f"**Jailed At:** <t:{int(jailed_time.timestamp())}:f>\n"
                f"**Duration:** {f'{duration // 60} minutes' if duration else 'Permanent'}\n"
                f"**Jailed By:** {mod.mention if mod else 'Unknown'}"
            )
            await ctx.send(view=CV2("📄 Jail Record", desc))
        else:
            await ctx.send(view=CV2("❌ Error", f"No jail record found for {member.mention}"))

async def setup(bot):
    await bot.add_cog(Jail(bot))
