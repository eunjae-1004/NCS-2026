from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.db import get_connection


def main() -> None:
    with get_connection() as conn:
        version = conn.execute(text("SELECT version()")).scalar()
        print("PostgreSQL:", (version or "")[:120])

        rows = conn.execute(
            text(
                """
                SELECT name, default_version, installed_version
                FROM pg_available_extensions
                WHERE name IN ('vector')
                ORDER BY name
                """
            )
        ).mappings().all()
        print("pg_available_extensions (vector):", [dict(r) for r in rows])

        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            print("CREATE EXTENSION vector: OK")
            ver = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            print("installed extversion:", ver)
        except Exception as exc:  # noqa: BLE001
            print("CREATE EXTENSION vector: FAILED")
            print("  ", exc)


if __name__ == "__main__":
    main()
