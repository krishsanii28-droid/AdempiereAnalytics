"""Settings: config.toml for behaviour, .env for secrets."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    session_hours: int
    dev_login: bool
    secret_key: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    statement_timeout_ms: int
    pool_max: int
    default_months: int
    top_n: int
    slow_moving_days: int
    max_rows: int


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


@lru_cache
def get_settings() -> Settings:
    with open(ROOT / "config.toml", "rb") as fh:
        cfg = tomllib.load(fh)
    # Real environment variables win over .env, so a deployment can inject secrets its own way.
    env = {**_read_env_file(ROOT / ".env"), **{k: v for k, v in os.environ.items() if k.startswith("INSIGHTAI_")}}

    missing = [k for k in ("INSIGHTAI_DB_PASSWORD", "INSIGHTAI_SECRET_KEY") if not env.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing {', '.join(missing)} in .env. Run scripts\\db_install.ps1 and scripts\\setup_service.ps1."
        )

    server, database, dashboard = cfg["server"], cfg["database"], cfg["dashboard"]
    return Settings(
        host=server["host"],
        port=int(server["port"]),
        session_hours=int(server["session_hours"]),
        dev_login=bool(server["dev_login"]),
        secret_key=env["INSIGHTAI_SECRET_KEY"],
        db_host=env.get("INSIGHTAI_DB_HOST", "localhost"),
        db_port=int(env.get("INSIGHTAI_DB_PORT", "5432")),
        db_name=env.get("INSIGHTAI_DB_NAME", "adempiere"),
        db_user=env.get("INSIGHTAI_DB_USER", "insightai_ro"),
        db_password=env["INSIGHTAI_DB_PASSWORD"],
        statement_timeout_ms=int(database["statement_timeout_ms"]),
        pool_max=int(database["pool_max"]),
        default_months=int(dashboard["default_months"]),
        top_n=int(dashboard["top_n"]),
        slow_moving_days=int(dashboard["slow_moving_days"]),
        max_rows=int(dashboard["max_rows"]),
    )
