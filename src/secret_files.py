"""Secrets from files (Baseten mounts them at /secrets/{name}).

Each required secret is read from its file when present and falls back
to the environment, so local runs are unchanged. In production
(ONYA_ENV=production) a required secret with neither a file nor an env
value is refused at startup. Values are never logged.
"""

import os
from pathlib import Path

SECRETS_DIR = Path("/secrets")

REQUIRED_SECRETS = ("META_API_KEY", "ONYA_DEMO_TOKEN", "SEC_USER_AGENT")


def get_secret(name, environ=None):
    """File value wins; environment is the fallback; None if absent."""
    path = SECRETS_DIR / name
    try:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError:
        pass
    env = os.environ if environ is None else environ
    value = (env.get(name) or "").strip()
    return value or None


def _check_contact(name, value):
    """SEC contact rule: the User-Agent must name a contact email."""
    if name == "SEC_USER_AGENT" and "@" not in (value or ""):
        raise RuntimeError(
            "required secret SEC_USER_AGENT must contain a contact "
            "email in production")


def load_secret_files(environ=None):
    """Copy file secrets into the environment for existing readers."""
    env = os.environ if environ is None else environ
    production = (env.get("ONYA_ENV") or "") == "production"
    for name in REQUIRED_SECRETS:
        value = get_secret(name, env)
        if value:
            if production:
                _check_contact(name, value)
            env[name] = value
        elif production:
            raise RuntimeError(
                f"required secret {name} is missing in production")
