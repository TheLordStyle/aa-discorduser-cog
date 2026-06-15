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
- Channel allow-list via `DISCORDUSER_DISCORD_BOT_CHANNELS`; the command
  silently refuses everywhere else (slash: ephemeral notice; prefix: 👎).
