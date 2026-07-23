"""SQLite cache for financial data and stock quotes."""

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.environ.get(
    "A_SHARE_DB_PATH",
    os.path.expanduser("~/projects/a_share_fetcher/data.db"),
)


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS financials (
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL DEFAULT '',
            year INTEGER NOT NULL,
            roe REAL,
            debt_ratio REAL,
            gross_margin REAL,
            fcf REAL,
            payout REAL,
            pb REAL,
            roe_pb REAL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (stock_code, year)
        );

        CREATE TABLE IF NOT EXISTS fetch_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_count INTEGER,
            year_range TEXT,
            success INTEGER,
            error_msg TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def upsert_financials(rows: list[dict]):
    """Insert or replace financial data rows."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        conn.execute("""
            INSERT OR REPLACE INTO financials
                (stock_code, stock_name, year, roe, debt_ratio,
                 gross_margin, fcf, payout, pb, roe_pb, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["code"], r.get("name", ""), r["year"],
            r.get("roe"), r.get("debt_ratio"), r.get("gross_margin"),
            r.get("fcf"), r.get("payout"), r.get("pb"), r.get("roe_pb"),
            now,
        ))
    conn.commit()
    conn.close()


def load_financials(years: list[int] | None = None,
                    codes: list[str] | None = None) -> list[dict]:
    """Load cached financial data with column names matching dashboard fields."""
    conn = get_db()
    query = "SELECT stock_code, stock_name, year, roe, debt_ratio, gross_margin, fcf, payout, pb, roe_pb FROM financials WHERE 1=1"
    params: list = []
    if years:
        placeholders = ",".join("?" * len(years))
        query += f" AND year IN ({placeholders})"
        params.extend(years)
    if codes:
        placeholders = ",".join("?" * len(codes))
        query += f" AND stock_code IN ({placeholders})"
        params.extend(codes)
    query += " ORDER BY stock_code, year"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    cols = ["code", "name", "year", "roe", "debt_ratio", "gross_margin",
            "fcf", "payout", "pb", "roe_pb"]
    return [dict(zip(cols, row)) for row in rows]


def is_stale(table: str = "financials", ttl_hours: int = 48) -> bool:
    """Check if data is older than TTL."""
    conn = get_db()
    row = conn.execute(f"SELECT MAX(fetched_at) FROM {table}").fetchone()
    conn.close()
    if not row or not row[0]:
        return True
    last = datetime.fromisoformat(row[0])
    age = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    return age > ttl_hours
