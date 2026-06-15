# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-15

### Added
- Initial release.
- `!discordcheck` prefix command and `/discordcheck` slash command.
- Walks every member of the configured Discord guild(s) and lists those
  who have **no active Alliance Auth Discord service** — i.e. people who
  are still in the server but either never authed, never enabled the
  Discord service, or removed it.
- Best-effort subdivision of the flagged members into **In auth, no
  Discord service** (Discord nickname matched a known EVE character) and
  **Not matched to auth** (no character match), with a per-account note
  when the matched auth account has the Discord service linked to a
  different Discord id.
- Each listed member shows their current Discord roles (excluding the
  implicit `@everyone`), highest-position first, so you can see what access
  they still hold.
- Each member is rendered as a real Discord mention (`<@id>`) so you can
  right-click them directly from the report to take action. The report is sent
  as plain message content (not an embed) so the mentions resolve reliably for
  every listed member — mentions inside an embed only render as pills when the
  viewer's client already has the user cached. Pings are suppressed via
  `allowed_mentions`, so the report doesn't notify everyone it lists.
- Channel allow-list via `DISCORDUSER_DISCORD_BOT_CHANNELS`; the command
  silently refuses everywhere else (slash: ephemeral notice; prefix: 👎).
