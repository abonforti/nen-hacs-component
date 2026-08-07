# AGENTS.md

Instructions for AI coding agents working on this repository. Human contributors should read [CONTRIBUTING.md](CONTRIBUTING.md); everything there applies here too.

This file covers only the constraints that are not obvious from reading the code.

## Never break existing entity IDs

`legacy_subscription_ids()` and `subscription_identity()` in `custom_components/nen/models.py` look like redundant indirection. They are not. They keep the entity IDs of accounts that existed before multi-property support was added, so those users' dashboards, automations and history keep working after an update.

Do not "simplify" them. If a change alters which subscription receives the legacy ID, it silently breaks every existing installation. Tests in `tests/test_coordinator.py` pin this behaviour.

## The API is unofficial and undocumented

NeN publishes no API documentation. Endpoints, field names and response shapes were captured from the web app's network traffic.

Never invent an endpoint, a query parameter or a response field. If something is needed and not already in `custom_components/nen/api.py`, capture it first from browser DevTools (Network tab, filter `prod.api.nen.it`) and include the observed payload in the pull request.

Field values are not always what they look like. Prices arrive in Italian decimal notation, for example `"0,13943"`. Use `_safe_float()`, which handles the comma; a bare `float()` raises.

## Imports and layout

The integration is a package at `custom_components/nen/` and uses relative imports (`from .api import ...`), so its modules cannot be imported standalone.

Tests currently run as:

```bash
PYTHONPATH=custom_components/nen pytest
```

With that path only modules free of relative imports are importable, which is why `models.py` is the only module under test today.

## Translations

`custom_components/nen/strings.json` and every file in `custom_components/nen/translations/` must have an identical key set. Adding a config flow step or error means updating all of them.

## CI gates

Three separate checks, all enforced. Passing the first does not imply the others:

```bash
ruff check .
ruff format --check .
mypy custom_components/nen
```

Hassfest and HACS validation also run on every pull request.

## Releases

`version` in `custom_components/nen/manifest.json` and the git tag must move together. HACS serves what the tag points at, so a bumped manifest without a matching `v*` tag ships nothing, and a tag without a bump ships a version that lies about itself.
