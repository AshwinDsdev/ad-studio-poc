"""
Database adapter — uses SQLite locally (zero config, built-in)
and Turso (libSQL) when TURSO_DATABASE_URL + TURSO_AUTH_TOKEN are set.
"""
import os
import sqlite3
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), "adstudio.db")

def _turso_available() -> bool:
    if not (TURSO_URL and TURSO_TOKEN):
        return False
    try:
        import libsql_client  # noqa: F401, PLC0415
        return True
    except ImportError:
        logger.warning(
            "TURSO_* is set but libsql-client is not installed. "
            "Falling back to local SQLite. Install with: pip install libsql-client"
        )
        return False


USE_TURSO = _turso_available()


# ---------------------------------------------------------------------------
# Thin adapter so the rest of the code calls db.execute() uniformly
# ---------------------------------------------------------------------------

class _ExecResult:
    """Minimal result object matching libsql_client's .rows interface."""

    def __init__(self, rows: list):
        self.rows = rows


class _SqliteAdapter:
    """Wraps sqlite3 to match the execute(sql, params) interface."""

    def __init__(self, path: str):
        self._path = path

    def execute(self, sql: str, params: tuple = ()):
        con = sqlite3.connect(self._path)
        try:
            cur = con.execute(sql, params)
            rows = cur.fetchall()
            con.commit()
            return _ExecResult(rows)
        finally:
            con.close()


class _TursoAdapter:
    """Wraps libsql_client to match the same interface."""

    def __init__(self, url: str, token: str):
        import libsql_client  # noqa: PLC0415
        self._client = libsql_client.create_client_sync(url=url, auth_token=token)

    def execute(self, sql: str, params: tuple = ()):
        try:
            return self._client.execute(sql, params)
        except KeyError as e:
            if str(e) == "'result'":
                raise RuntimeError(
                    "Turso connection failed or returned an error response. "
                    "Make sure your TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are valid, "
                    "or comment them out in your .env file to use the local SQLite database."
                ) from e
            raise


def get_db_client():
    if USE_TURSO:
        return _TursoAdapter(TURSO_URL, TURSO_TOKEN)
    return _SqliteAdapter(LOCAL_DB_PATH)


def init_db():
    db = get_db_client()
    db.execute("""
        CREATE TABLE IF NOT EXISTS ads (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            status TEXT,
            video_url TEXT,
            current_progress INTEGER DEFAULT 0,
            storyboard_json TEXT DEFAULT ''
        )
    """)
    mode = "Turso" if USE_TURSO else f"SQLite ({LOCAL_DB_PATH})"
    print(f"Database initialised successfully ({mode}).")


if __name__ == "__main__":
    init_db()
