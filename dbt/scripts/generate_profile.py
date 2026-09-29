"""
Parses DATABASE_URL from the repo's .env and writes the 'veltrana_sim'
target into ~/.dbt/profiles.yml - never into the repo. dbt_project.yml
just references the profile by name; the actual host/port/user/password/
dbname live only in this external file, regenerated from .env whenever it
changes, so nothing about the connection is hardcoded anywhere in git.

Run this once (or again whenever DATABASE_URL changes) before `dbt run`.
Merges into any existing profiles.yml rather than overwriting it, so
other projects' profiles on this machine are left alone.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_NAME = "veltrana_sim"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_database_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ValueError(f"Unexpected DATABASE_URL scheme: {parsed.scheme!r}")
    if not parsed.hostname or not parsed.path.lstrip("/"):
        raise ValueError("DATABASE_URL is missing a host or database name")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "dbname": parsed.path.lstrip("/"),
    }


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not found in .env or environment")

    conn = parse_database_url(dsn)

    profiles_path = Path.home() / ".dbt" / "profiles.yml"
    profiles_path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if profiles_path.exists():
        existing = yaml.safe_load(profiles_path.read_text()) or {}

    existing[PROFILE_NAME] = {
        "target": "dev",
        "outputs": {
            "dev": {
                "type": "postgres",
                "host": conn["host"],
                "port": conn["port"],
                "user": conn["user"],
                "password": conn["password"],
                "dbname": conn["dbname"],
                "schema": "silver",
                "threads": 4,
                "sslmode": "require",
            }
        },
    }

    profiles_path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))
    print(f"Wrote profile '{PROFILE_NAME}' -> {profiles_path}")
    print(f"  host={conn['host']} port={conn['port']} dbname={conn['dbname']} user={conn['user']} schema=silver")


if __name__ == "__main__":
    main()
