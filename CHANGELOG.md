# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- The retired `asla_studio` naming is gone: eight xmlids (the bot partner and user, four menus, two
  actions) and the settings keys `asla_studio.api_key`, `asla_studio.api_url` and
  `asla_studio.operation_mode` are now `asla_client.*`. A pre-migration renames the existing
  `ir_model_data` rows in place, so a database keeps its records instead of gaining a second bot
  partner and duplicate menus, and a post-migration copies the settings. The old keys are still read
  as a fallback for one release.

### Fixed
- `asla_client.mcp.plan.action_validate_dry_run` wrote "Schema validation passed" without inspecting
  anything, and `action_execute` wrote `state = 'executed'` without executing anything. Both now
  refuse: an approval granted on the strength of a dry run that never ran is worse than no dry run.

### Security
- `/asla/bot/rpc` compares the bearer token in constant time (`hmac.compare_digest`) instead
  of `==`, which leaked how much of a guess was correct.
- The endpoint caps request bodies at 1 MB before parsing JSON, and no longer returns
  internal exception text to the caller; the detail stays in the server log.

### Added
- Packaging for publication: author, website, category, support address, declared Python
  dependency (`requests`), application flag, module icon and description page.
- Contributor documentation: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  issue and pull-request templates.
- Continuous integration: the module is installed into a clean Odoo 18 and its tests are run
  on every push and pull request.
- A first test suite covering endpoint authentication and offline/online routing.

### Fixed
- The `AslaBot` menu pointed its icon at `asla_studio`, a module that does not exist, so the
  app had no icon.

## [18.0.1.0.0] - 2026-09-16

First tagged release. AslaBot in Discuss, support tickets, administration plans with
approval, offline and online modes. Licence: LGPL-3.
