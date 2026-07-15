"""
history_store.py
=================
Lightweight SQLite-backed history for the CDMS Promo Claim dashboard.
Saves each Stage 1 (Working) and Stage 2 (Claim comparison) run so past
months can be reviewed without re-uploading files, and lets old runs be
deleted.

NOTE on persistence: on Streamlit Community Cloud's free tier, the local
filesystem (including this SQLite file) is NOT guaranteed to survive a
code redeploy or a long-inactivity reboot. It reliably survives page
refreshes, new visits, and normal day-to-day use while the app instance
stays warm. For a guarantee that survives every possible reboot, an
external database (e.g. Supabase/Postgres) would be needed instead.
"""

import io
import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd

DB_PATH = "cdms_history.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS working_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saved_at TEXT NOT NULL,
            label TEXT NOT NULL,
            source_file TEXT,
            distributor_count INTEGER,
            total_prc_off_claim REAL,
            total_db_margin_amt REAL,
            total_db_tot_claim REAL,
            summary_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claim_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saved_at TEXT NOT NULL,
            label TEXT NOT NULL,
            working_run_id INTEGER,
            claim_file TEXT,
            accuracy_pct REAL,
            total_variance REAL,
            comparison_json TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------- Stage 1 --

def save_working_run(summary_df: pd.DataFrame, label: str, source_file: str = "") -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO working_runs
           (saved_at, label, source_file, distributor_count,
            total_prc_off_claim, total_db_margin_amt, total_db_tot_claim, summary_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            _now(), label, source_file, int(summary_df.shape[0]),
            float(summary_df["Working_Prc_Off_Claim"].sum()),
            float(summary_df["Working_DB_Margin_Amt"].sum()),
            float(summary_df["Working_DB_Tot_Claim"].sum()),
            summary_df.to_json(orient="records"),
        ),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def list_working_runs() -> pd.DataFrame:
    conn = _connect()
    df = pd.read_sql_query(
        """SELECT id, saved_at, label, source_file, distributor_count,
                  total_prc_off_claim, total_db_margin_amt, total_db_tot_claim
           FROM working_runs ORDER BY saved_at DESC""",
        conn,
    )
    conn.close()
    return df


def load_working_run(run_id: int) -> pd.DataFrame:
    run_id = int(run_id)
    conn = _connect()
    row = conn.execute("SELECT summary_json FROM working_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return pd.read_json(io.StringIO(row[0]), orient="records")


def delete_working_run(run_id: int) -> None:
    run_id = int(run_id)
    conn = _connect()
    conn.execute("DELETE FROM working_runs WHERE id = ?", (run_id,))
    conn.execute("DELETE FROM claim_runs WHERE working_run_id = ?", (run_id,))
    conn.commit()
    conn.close()


# ------------------------------------------------------------- Stage 2 --

def save_claim_run(comparison_df: pd.DataFrame, score: dict, label: str,
                    working_run_id: int = None, claim_file: str = "") -> int:
    working_run_id = int(working_run_id) if working_run_id is not None else None
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO claim_runs
           (saved_at, label, working_run_id, claim_file, accuracy_pct, total_variance, comparison_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            _now(), label, working_run_id, claim_file,
            float(score.get("Accuracy %", 0.0)), float(score.get("Total Variance", 0.0)),
            comparison_df.to_json(orient="records"),
        ),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def list_claim_runs() -> pd.DataFrame:
    conn = _connect()
    df = pd.read_sql_query(
        """SELECT id, saved_at, label, working_run_id, claim_file, accuracy_pct, total_variance
           FROM claim_runs ORDER BY saved_at DESC""",
        conn,
    )
    conn.close()
    return df


def load_claim_run(run_id: int) -> pd.DataFrame:
    run_id = int(run_id)
    conn = _connect()
    row = conn.execute("SELECT comparison_json FROM claim_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return pd.read_json(io.StringIO(row[0]), orient="records")


def delete_claim_run(run_id: int) -> None:
    run_id = int(run_id)
    conn = _connect()
    conn.execute("DELETE FROM claim_runs WHERE id = ?", (run_id,))
    conn.commit()
    conn.close()
