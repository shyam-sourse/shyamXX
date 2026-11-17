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
from utils.emoji import SWORD
from discord.ext import commands


class _moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    """Moderation commands"""

    def help_custom(self):
        emoji = f'{SWORD} '
        label = "Moderation Commands"
        description = "Punish, clean and manage your members."
        return emoji, label, description

    def help_commands(self):
        return [
            ("audit", "View recent moderation actions in the server."),
            ("warn <member> [reason]", "Warn a member and log the reason."),
            ("clearwarns <member>", "Clear every warning for a member."),
            ("ban <member> [reason]", "Ban a member from the server."),
            ("clone", "Clone the current channel."),
            ("snipe", "Show the most recently deleted message."),
            ("hide", "Hide a channel from @everyone."),
            ("hideall", "Hide every channel in the server."),
            ("kick <member> [reason]", "Kick a member from the server."),
            ("lock", "Lock the current channel."),
            ("mute <member> [duration]", "Timeout a member for a duration."),
            ("nick <member> [nickname]", "Change or reset a member's nickname."),
            ("nuke", "Clone and delete the current channel to reset it."),
            ("role <member> <role>", "Add or remove a role from a member."),
            ("roleicon <role> [icon]", "View or set a role's icon."),
            ("role all <role>", "Give a role to every member."),
            ("role bots <role>", "Give a role to every bot."),
            ("role create <name>", "Create a new role."),
            ("role delete <role>", "Delete a role."),
            ("role humans <role>", "Give a role to every human member."),
            ("role rename <role> <name>", "Rename a role."),
            ("role temp <member> <role> <duration>", "Give a member a temporary role."),
            ("role unverified <role>", "Give a role to every unverified member."),
            ("slowmode <seconds>", "Set slowmode for the current channel."),
            ("lockall", "Lock every channel in the server."),
            ("unlockall", "Unlock every channel in the server."),
            ("steal <emoji>", "Steal an emoji into the server."),
            ("unban <user> [reason]", "Unban a user from the server."),
            ("unhide", "Unhide a channel from @everyone."),
            ("unhideall", "Unhide every channel in the server."),
            ("unlock", "Unlock the current channel."),
            ("unslowmode", "Disable slowmode for the current channel."),
            ("removerole all <role>", "Remove a role from every member."),
            ("removerole bots <role>", "Remove a role from every bot."),
            ("removerole humans <role>", "Remove a role from every human member."),
            ("removerole unverified <role>", "Remove a role from every unverified member."),
            ("clear [amount]", "Delete a number of recent messages."),
            ("clear all [amount]", "Delete messages from every member."),
            ("clear bots [amount]", "Delete messages sent by bots."),
            ("clear contains <text> [amount]", "Delete messages containing specific text."),
            ("clear embeds [amount]", "Delete messages that contain embeds."),
            ("clear files [amount]", "Delete messages that contain files."),
            ("clear images [amount]", "Delete messages that contain images."),
            ("clear mentions [amount]", "Delete messages that mention users."),
            ("clear reactions [amount]", "Delete messages that have reactions."),
            ("clear user <member> [amount]", "Delete messages from a specific member."),
            ("deleteemoji <emoji>", "Delete an emoji from the server."),
            ("deletesticker <sticker>", "Delete a sticker from the server."),
            ("enlarge <emoji>", "Get a larger version of an emoji."),
            ("topcheck", "View the moderation action leaderboard."),
            ("topcheck enable", "Enable the moderation leaderboard."),
            ("topcheck disable", "Disable the moderation leaderboard."),
        ]

    @commands.group()
    async def __Moderation__(self, ctx: commands.Context):
        """`audit` , `warn` , `clearwarns` , `ban` , `clone` , `snipe` , `hide` , `hideall` , `kick` , `lock` , `mute` , `nick` , `nuke` , `role` , `roleicon` , `role all` , `role bots` , `role create` , `role delete` , `role humans` , `role rename` , `role temp` , `role unverified` , `slowmode` , `lockall` `unlockall` , `steal` , `unban` , `unhide` , `unhideall` , `unlock` , `unslowmode` , `removerole all` , `removerole bots` , `removerole humans` , `removerole unverified` , `clear` , `clear all` , `clear bots` , `clear contains` , `clear embeds` , `clear files` , `clear images` , `clear mentions` , `clear reactions` , `clear user` , `deleteemoji` , `deletesticker` , `enlarge`\n\n`topcheck` , `topcheck enable` , `topcheck disable`"""
