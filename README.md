# aa-discorduser-cog

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Alliance Auth](https://img.shields.io/badge/Alliance%20Auth-5.x-green.svg)](https://gitlab.com/allianceauth/allianceauth)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) Discord cog
that produces a list of who is **on Discord but not set up for the Discord
service in auth**. It walks the live Discord guild membership and flags every
member who has no active Alliance Auth **Discord service** link — that is,
people who are still in the server but:

- **never authed** at all,
- **authed but never enabled** the Discord service, or
- **removed** (or lost) the Discord service.

Built on top of
[aadiscordbot](https://github.com/pvyParts/allianceauth-discordbot).

## What it does

The single source of truth for "this Discord account has the service enabled
in auth" is Alliance Auth's `DiscordUser` table (one row per linked account,
keyed on the Discord user id). The cog fetches the full Discord guild member
list and reports everyone whose id has **no** `DiscordUser` row.

Because the only stored link between a Discord id and an auth account *is*
that row — and it's gone in all three states above — those states look
identical from the Discord side. To be more useful, the cog makes a
**best-effort** guess at which bucket each member belongs to by matching their
Discord nickname against known EVE character names:

- **🟧 In auth, no Discord service** — the nickname matched a known character
  whose auth account exists, but there's no active service link for this id.
- **🟥 Not matched to auth** — the nickname matched no known character, so the
  member most likely never authed (or simply isn't using their character name
  as a nickname).

Bots are ignored. Members who *do* have the service are counted in the summary
but not listed.

Outside the allow-list the command silently refuses (slash: ephemeral *"not
available in this channel"*; prefix: 👎 reaction).

### Example output

> **Scanned 412 Discord member(s)** — 🟩 389 with service, 🟧 4 in auth without service, 🟥 6 not matched to auth (13 bot(s) ignored)
>
> **🟧 In auth, no Discord service (4)** — nickname matches a known character, but the Discord service isn't active (never enabled or removed)
> • [TICK] Bob McAuthed (`123456789012345678`) — matches **Bob McAuthed**, authed as `bob`, but no active Discord service
> &nbsp;&nbsp;↳ roles: Member, Fleet Commander
> • Carol Quit (`223456789012345678`) — matches **Carol Quit**, authed as `carol`, but no active Discord service  ⚠️ *(service is linked to a different Discord account)*
> &nbsp;&nbsp;↳ roles: Member
>
> **🟥 Not matched to auth (6)** — on Discord but no character match (likely never authed, or nickname isn't their character name)
> • randomuser99 (`323456789012345678`)
> &nbsp;&nbsp;↳ roles: *none*
> • Some Friend (`423456789012345678`)
> &nbsp;&nbsp;↳ roles: Guest

## Requirements

| Component | Version |
|---|---|
| Alliance Auth | ≥ 5.0 |
| [allianceauth-discordbot](https://github.com/pvyParts/allianceauth-discordbot) | recent |

The bot must have the **Server Members Intent** enabled (Discord Developer
Portal → your application → Bot → Privileged Gateway Intents). Without it the
guild member list is empty and the cog has nothing to scan. aadiscordbot
enables this intent by default.

## Install

### Production (pinned)

Add to your AA `requirements.txt`:

```text
git+https://github.com/TheLordStyle/aa-discorduser-cog.git@v0.1.0
```

Then in `local.py`:

```python
# ============================================================
#  aa-discorduser-cog  -  who's on Discord but not in auth's Discord service
#  https://github.com/TheLordStyle/aa-discorduser-cog
# ============================================================
DISCORD_BOT_COGS += ["aa_discorduser.discorduser"]

# Channels where the command is allowed. Empty / unset = blocked everywhere.
DISCORDUSER_DISCORD_BOT_CHANNELS = [
    111111111111111111,   # #leadership
]
```

Rebuild and restart auth.

### Development

For iteration without rebuilding the whole stack, bind-mount a checkout into
the discordbot container and install it editable:

```bash
docker compose exec allianceauth_discordbot \
    pip install -e /opt/cogs/aa-discorduser-cog

docker compose restart allianceauth_discordbot
```

Editable installs don't survive a `docker compose down` and rebuild —
production state always returns to whatever's pinned in `requirements.txt`.

## Settings

| Setting | Default | Description |
|---|---|---|
| `DISCORDUSER_DISCORD_BOT_CHANNELS` | `[]` | Channel allow-list (list of channel ids). The command only runs in these channels; empty/unset blocks it everywhere. |

## Usage

```text
!discordcheck
/discordcheck
```

Both forms post the report in the channel (paginated into multiple embeds when
long). The report runs against every guild configured for the bot
(`get_all_servers()`), de-duplicating members who share more than one.

## How it works

1. **Gather** — fetch the full member list for each configured guild
   (`guild.chunk()` forces a complete fetch when the gateway cache is partial).
2. **Index auth** — load the set of Discord ids that currently have the
   service (`DiscordUser.uid`), a map of EVE character name → auth user from
   `authentication_characterownership`, and the set of auth users that have
   *any* service link.
3. **Classify** — every non-bot member without a `DiscordUser` row is flagged;
   a nickname match against the character-name map decides whether it lands in
   *In auth, no Discord service* or *Not matched to auth*.

## Caveats

- **The nickname match is a heuristic.** Subdivision into the 🟧 / 🟥 buckets
  relies on the member's Discord nickname matching a known EVE character name
  (after stripping a single leading `[TICKER]`/`(TICKER)` prefix). A member who
  authed but uses a Discord nickname that isn't their character name will be
  reported as *Not matched to auth* even though they have an account — and,
  conversely, someone who set their nickname to a corpmate's character name
  could be mis-attributed. The reliable fact is always "this member has no
  active Discord service"; the bucket is a best-effort guess.
- **Members intent required.** If the bot lacks the Server Members Intent the
  guild member list is empty and the cog reports that it can't see anyone.
- **Discord-side only.** The cog answers "who's in the server without the
  service", not the inverse ("who has the service but already left the
  server").

## Contributing

Bug reports and PRs welcome. Please open an issue first for anything beyond
trivial fixes so we can talk about it.

## License

MIT — see [LICENSE](LICENSE).
