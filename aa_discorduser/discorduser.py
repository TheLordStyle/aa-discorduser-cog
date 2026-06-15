"""DiscordUser: flag people in the Discord server who aren't set up for the
Discord service in Alliance Auth.

The single source of truth for "this Discord account has the Discord service
enabled in auth" is the ``DiscordUser`` table (one row per linked account,
keyed on the Discord user id ``uid``). Anyone present in the Discord guild
whose id has **no** ``DiscordUser`` row is therefore in one of three states,
all of which this cog reports:

- never authed at all,
- authed but never enabled the Discord service,
- authed and then removed (or lost) the Discord service.

From the Discord side those three collapse into the same observable fact —
"member, but no active service link" — because the only stored mapping
between a Discord id and an auth account *is* the ``DiscordUser`` row, and it's
gone in all three cases. To be more helpful the cog makes a **best-effort**
attempt to subdivide them by matching the member's Discord nickname against
known EVE character names (see ``_candidate_character_name`` and the README's
Caveats section), but that match is a heuristic, not authoritative.
"""
import logging
import re

from aadiscordbot.app_settings import get_all_servers
from discord import AllowedMentions
from discord.embeds import Embed
from discord.ext import commands

from django.conf import settings
from django.contrib.auth.models import User

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.services.modules.discord.models import DiscordUser

logger = logging.getLogger(__name__)


# ---- Channel allow-list -----------------------------------------------------

def _channel_allowed(channel_id: int) -> bool:
    return channel_id in getattr(
        settings, "DISCORDUSER_DISCORD_BOT_CHANNELS", []
    )


# ---- Discord-side data gathering --------------------------------------------

async def _gather_members(bot):
    """Return a de-duplicated list of ``discord.Member`` across every guild
    the cog is configured for (``get_all_servers()``).

    The members intent must be enabled for the cache to be populated;
    ``guild.chunk()`` forces a full member fetch when the gateway hasn't
    delivered the whole list yet.
    """
    seen, members = set(), []
    for gid in get_all_servers():
        guild = bot.get_guild(gid)
        if guild is None:
            logger.warning("discorduser: configured guild %s not found", gid)
            continue
        if not guild.chunked:
            try:
                await guild.chunk()
            except Exception:
                logger.exception(
                    "discorduser: failed to chunk guild %s; using cache only",
                    gid,
                )
        for m in guild.members:
            if m.id in seen:
                continue
            seen.add(m.id)
            members.append(m)
    return members


_TICKER_PREFIX = re.compile(r"^\s*[\[(][^\])]*[\])]\s*")


def _member_roles(member) -> list:
    """Role names for a member, excluding the implicit ``@everyone`` default,
    ordered highest-position first (the way Discord shows them)."""
    return [
        r.name for r in sorted(member.roles, key=lambda r: r.position, reverse=True)
        if not r.is_default()
    ]


def _candidate_character_name(member) -> str:
    """Best-effort guess of the EVE character name behind a Discord member.

    Alliance Auth's Discord service sets a member's nickname to their main
    character name, optionally prefixed with a corp/alliance ticker like
    ``[TICK] Char Name``. Once the service is removed AA no longer manages
    the nickname, so this is a guess — we strip a single leading bracketed
    ticker and fall back through nick → global name → username.
    """
    raw = member.nick or member.global_name or member.name or ""
    return _TICKER_PREFIX.sub("", raw).strip()


# ---- Auth-side lookups ------------------------------------------------------

def _auth_index():
    """Build the auth-side lookup tables in as few queries as possible.

    Returns a tuple of:
      - ``service_uids``  : set of Discord ids that currently have the
                            Discord service enabled (``DiscordUser.uid``),
      - ``name_to_user``  : lower-cased EVE character name -> auth user id,
      - ``usernames``     : auth user id -> username,
      - ``users_with_svc``: set of auth user ids that have *some* Discord
                            service link (possibly under a different id).
    """
    service_uids = {int(u) for u in DiscordUser.objects.values_list(
        "uid", flat=True
    )}
    users_with_svc = set(DiscordUser.objects.values_list("user_id", flat=True))

    name_to_user = {}
    for name, user_id in CharacterOwnership.objects.values_list(
        "character__character_name", "user_id"
    ):
        if name:
            name_to_user[name.lower()] = user_id

    usernames = dict(User.objects.values_list("id", "username"))
    return service_uids, name_to_user, usernames, users_with_svc


# ---- Classification ---------------------------------------------------------

def _classify(members):
    """Split Discord members into report buckets.

    Bots are ignored. Members with an active ``DiscordUser`` link are
    counted as OK and not listed. Everyone else is bucketed:

      - ``no_service`` : nickname matched a known EVE character whose auth
                         account exists, but that account has no active
                         Discord-service link for this id.
      - ``not_in_auth``: nickname matched no known EVE character — most
                         likely never authed (or the nickname simply isn't
                         their character name).
    """
    service_uids, name_to_user, usernames, users_with_svc = _auth_index()

    no_service, not_in_auth = [], []
    ok_count = bot_count = 0

    for m in members:
        if m.bot:
            bot_count += 1
            continue
        if m.id in service_uids:
            ok_count += 1
            continue

        cand = _candidate_character_name(m)
        user_id = name_to_user.get(cand.lower()) if cand else None
        entry = {
            "discord_id": m.id,
            "display": m.display_name,
            "candidate": cand,
            "roles": _member_roles(m),
        }
        if user_id is None:
            not_in_auth.append(entry)
        else:
            entry["auth_user"] = usernames.get(user_id, f"user#{user_id}")
            # The matched account has the service under a *different* Discord
            # id — flag it so the reader can spot duplicates / re-links.
            entry["other_link"] = user_id in users_with_svc
            no_service.append(entry)

    return {
        "no_service": no_service,
        "not_in_auth": not_in_auth,
        "ok_count": ok_count,
        "bot_count": bot_count,
        "total": len(members),
    }


# ---- Formatting -------------------------------------------------------------

def _fmt_roles(r) -> str:
    roles = r.get("roles") or []
    return f"\n  ↳ roles: {', '.join(roles)}" if roles else "\n  ↳ roles: *none*"


def _fmt_no_service(r) -> str:
    suffix = (
        "  ⚠️ *(service is linked to a different Discord account)*"
        if r.get("other_link") else ""
    )
    return (
        f"• <@{r['discord_id']}> — matches **{r['candidate']}**, "
        f"authed as `{r['auth_user']}`, but no active Discord service{suffix}"
        f"{_fmt_roles(r)}"
    )


def _fmt_not_in_auth(r) -> str:
    return f"• <@{r['discord_id']}>{_fmt_roles(r)}"


# A single message's content hard cap is 2000 chars. We render the report as
# message content (not embeds) so that user mentions reliably resolve to
# clickable pills — mentions inside an embed only render when the viewer's
# client already has the user cached. Keep each block well under the cap so a
# block always fits in one message.
_MSG_LIMIT = 1950
_MAX_BLOCK = 1800


def _chunk_section(header, lines):
    """Split one bucket into <=_MAX_BLOCK-char blocks, each carrying a header
    (follow-ups get a ``(cont.)`` suffix)."""
    chunks, current, size = [], [header], len(header)
    for line in lines:
        addition = len(line) + 1
        if size + addition > _MAX_BLOCK and len(current) > 1:
            chunks.append("\n".join(current))
            cont = f"{header} (cont.)"
            current, size = [cont, line], len(cont) + addition
        else:
            current.append(line)
            size += addition
    chunks.append("\n".join(current))
    return chunks


def _build_summary(report) -> str:
    summary = (
        f"Scanned **{report['total']}** Discord member(s) — "
        f"🟩 {report['ok_count']} with service, "
        f"🟧 {len(report['no_service'])} in auth without service, "
        f"🟥 {len(report['not_in_auth'])} not matched to auth"
    )
    if report["bot_count"]:
        summary += f" ({report['bot_count']} bot(s) ignored)"
    return summary


def _build_member_blocks(report):
    blocks = []
    if report["no_service"]:
        blocks.extend(_chunk_section(
            f"**🟧 In auth, no Discord service ({len(report['no_service'])})** — "
            "nickname matches a known character, but the Discord service "
            "isn't active (never enabled or removed)",
            [_fmt_no_service(r) for r in report["no_service"]],
        ))
    if report["not_in_auth"]:
        blocks.extend(_chunk_section(
            f"**🟥 Not matched to auth ({len(report['not_in_auth'])})** — "
            "on Discord but no character match (likely never authed, or "
            "nickname isn't their character name)",
            [_fmt_not_in_auth(r) for r in report["not_in_auth"]],
        ))
    return blocks


def _build_messages(blocks):
    """Pack pre-formatted text blocks into message-content strings, each kept
    under ``_MSG_LIMIT`` so every message sends in one piece and its mentions
    resolve as clickable pills. Returns an empty list when there are no
    blocks (the summary embed already conveys an all-clear)."""
    pages, buf, size = [], [], 0
    for block in blocks:
        if size + len(block) + 2 > _MSG_LIMIT and buf:
            pages.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(block)
        size += len(block) + 2
    if buf:
        pages.append("\n\n".join(buf))
    return pages


# ---- The cog ----------------------------------------------------------------

_TITLE = "Discord members not set up for Discord in Auth"

# Allow *user* mentions so every listed member resolves to a proper named,
# right-clickable pill regardless of the viewer's member cache — a mention is
# only attached to the message (and thus resolvable by the client) when it's
# allowed. @everyone/@here and role pings stay disabled.
#
# Notifications are still gated by channel visibility: Discord only delivers a
# mention notification to someone who can read the channel. Run the command in
# a private/staff-only channel (that's what DISCORDUSER_DISCORD_BOT_CHANNELS is
# for) and the flagged members — who can't see it — won't be pinged.
_MENTIONS = AllowedMentions(everyone=False, roles=False, users=True)


class DiscordUserCheck(commands.Cog):
    """Flag Discord members who lack an active Alliance Auth Discord service."""

    def __init__(self, bot):
        self.bot = bot

    async def _run_and_reply(self, send):
        members = await _gather_members(self.bot)
        if not members:
            return await send(
                Embed(
                    title=_TITLE,
                    description=(
                        "No guild members are visible. Check that the bot has "
                        "the **Server Members Intent** enabled and the guild "
                        "id is configured."
                    ),
                    colour=0xE74C3C,
                ),
                [],
            )
        report = _classify(members)
        flagged = report["no_service"] or report["not_in_auth"]
        header = Embed(
            title=_TITLE,
            description=_build_summary(report),
            colour=0xE67E22 if flagged else 0x2ECC71,
        )
        messages = _build_messages(_build_member_blocks(report))
        await send(header, messages)

    # ---- prefix --------------------------------------------------------

    @commands.command(pass_context=True)
    async def discordcheck(self, ctx):
        """!discordcheck — list Discord members with no active auth Discord
        service. Only works in a configured channel."""
        if not _channel_allowed(ctx.message.channel.id):
            return await ctx.message.add_reaction(chr(0x1F44E))  # 👎

        async def send(header, messages):
            await ctx.message.reply(embed=header)
            for m in messages:
                await ctx.message.reply(m, allowed_mentions=_MENTIONS)

        try:
            await self._run_and_reply(send)
        except Exception:
            logger.exception("discordcheck prefix command failed")
            await ctx.message.reply(
                "⚠️ DiscordCheck failed — ask an admin to check the "
                "discordbot log for the traceback."
            )

    # ---- slash ---------------------------------------------------------

    @commands.slash_command(name="discordcheck", guild_ids=get_all_servers())
    async def slash_discordcheck(self, ctx):
        if not _channel_allowed(ctx.channel.id):
            return await ctx.respond(
                "This command isn't available in this channel.",
                ephemeral=True,
            )

        await ctx.defer()

        async def send(header, messages):
            await ctx.respond(embed=header)
            for m in messages:
                await ctx.followup.send(m, allowed_mentions=_MENTIONS)

        try:
            await self._run_and_reply(send)
        except Exception as e:
            # aadiscordbot's generic handler swallows the traceback and shows
            # "Something Went Wrong" — log it here and surface a useful hint.
            logger.exception("discordcheck slash command failed")
            msg = (
                f"⚠️ DiscordCheck hit `{type(e).__name__}`. Ask an admin to "
                "check the discordbot log for the traceback."
            )
            try:
                if ctx.response.is_done():
                    await ctx.followup.send(msg, ephemeral=True)
                else:
                    await ctx.respond(msg, ephemeral=True)
            except Exception:
                logger.exception("discordcheck error reply also failed")


def setup(bot):
    bot.add_cog(DiscordUserCheck(bot))
