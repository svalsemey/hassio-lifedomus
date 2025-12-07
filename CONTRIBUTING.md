# Contributing

Thank you for your interest in improving Lifedomus for Home Assistant.

## Code style and quality

- Strong typing everywhere; do not introduce untyped code or “Any” without necessity.
- No bare `except` and no `except Exception`; catch explicit exceptions.
- Docstrings required for modules, classes, and public methods/functions.
- Keep comments and docs in English.
- Avoid home-grown abstractions where Home Assistant helpers exist (e.g., DataUpdateCoordinator).
- Keep platform code lean and delegate parsing/transport to shared modules.

## Static checks and linters

- Ruff: `ruff check .` and `ruff format .`
- mypy: `mypy custom_components/lifedomus`
- hassfest: `python3 -m script.hassfest` (from a HA devcontainer or CI)
- Optional: `pyright`/`pylance` locally in your IDE

## Local development

- Use a Home Assistant devcontainer or a test HA instance.
- Install dev requirements if needed (linters, mypy).
- Run Home Assistant with this custom integration under `custom_components/lifedomus/`.

## Commit and PR guidelines

- Use descriptive commit messages.
- Reference issues in commits/PRs when applicable.
- One feature/fix per PR is preferred.
- Add tests when applicable and update docs (README, translations) as relevant.

## Security

- Do not submit secrets, real credentials, or private keys in issues or PRs.
- Redact sensitive values in logs and examples.

## Reporting issues

- Use the issue templates provided.
- Include HA version, integration version, gateway firmware, steps to reproduce, and logs with `custom_components.lifedomus: debug` enabled.
