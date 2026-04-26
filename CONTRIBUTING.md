# Contributing

## Getting started

```bash
git clone https://github.com/abonforti/nen-hacs-component
cd nen-hacs-component
pip install -r requirements-dev.txt
```

## Development setup

Symlink the component into a local HA dev instance:

```bash
ln -s $(pwd) /path/to/ha/config/custom_components/nen
```

Then restart HA and add the integration via the UI.

## Running tests

```bash
pytest tests/ -v
```

## Code style

- Follow [HA integration development guidelines](https://developers.home-assistant.io/docs/creating_integration_manifest)
- Run `ruff check .` before submitting
- No new dependencies without discussion

## Pull requests

- One feature or fix per PR
- Include a description of what changed and why
- If you have **Il Robo** active on your NeN account, PRs adding that integration are especially welcome — see the TODO in README.md for context

## API changes

NeN's API is unofficial and undocumented. If an endpoint breaks:

1. Open an issue with the error from HA logs
2. Capture the new request from browser DevTools (Network tab, filter `prod.api.nen.it`)
3. Submit a PR with the fix

## Reporting issues

Include:
- HA version
- Integration version
- Relevant lines from HA logs (`Settings → System → Logs`)
