"""
Loads data/bronze/*.parquet into Supabase Postgres, 1:1 and untransformed -
the other half of build-order step 5 (export.py writes the files, this
loads them). Bronze is meant to be a straight load of what the generator
exported, matching how a real vendor feed would land, so each table's
schema is inferred purely from its dataframe's own dtypes; there is no
column mapping, renaming, or cleanup here - that's Silver's job.

Reads DATABASE_URL from .env at the repo root. Requires psycopg2.
"""

from __future__ import annotations

import datetime as dt
import io
import os
from pathlib import Path

import pandas as pd
import psycopg2

import config as cfg

TABLE_NAMES = [
    "rx_audit",
    "claims",
    "sp_hub",
    "sell_in",
    "crm_calls",
    "rep_roster",
    "hcp_master",
    "formulary",
    "alignment",
]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def pg_type_for_column(series: pd.Series) -> str:
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(dtype):
        return "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        return "DOUBLE PRECISION"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMP"
    if dtype == object:
        # Parquet round-trips a plain python date column (e.g.
        # alignment.effective_date) as dtype object, not datetime64.
        sample = series.dropna()
        if len(sample):
            val = sample.iloc[0]
            if isinstance(val, dt.datetime):
                return "TIMESTAMP"
            if isinstance(val, dt.date):
                return "DATE"
    return "TEXT"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def create_table(cur, table: str, df: pd.DataFrame) -> None:
    cols_sql = ",\n    ".join(
        f"{quote_ident(col)} {pg_type_for_column(df[col])}" for col in df.columns
    )
    # CASCADE because downstream dbt models (e.g. silver.int_hcp_master_normalized)
    # hold a live view dependency on bronze tables - a Bronze reload is expected to
    # blow those away too; rerun `dbt run` afterward to rebuild them.
    cur.execute(f"DROP TABLE IF EXISTS bronze.{quote_ident(table)} CASCADE")
    cur.execute(f"CREATE TABLE bronze.{quote_ident(table)} (\n    {cols_sql}\n)")


def load_table(cur, table: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cols = ", ".join(quote_ident(c) for c in df.columns)
    cur.copy_expert(
        f"COPY bronze.{quote_ident(table)} ({cols}) FROM STDIN WITH (FORMAT csv)",
        buf,
    )


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not found in .env or environment")

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        conn.commit()

        results = []
        for name in TABLE_NAMES:
            path = cfg.BRONZE_DIR / f"{name}.parquet"
            if not path.exists():
                raise SystemExit(f"{path} not found - run export.py first")
            df = pd.read_parquet(path)

            with conn.cursor() as cur:
                create_table(cur, name, df)
                load_table(cur, name, df)
                cur.execute(f"SELECT COUNT(*) FROM bronze.{quote_ident(name)}")
                (loaded_count,) = cur.fetchone()
            conn.commit()

            results.append((name, len(df), loaded_count))
            print(f"  bronze.{name}: {loaded_count:,} rows loaded")

        print()
        mismatches = [n for n, expected, actual in results if expected != actual]
        if mismatches:
            print(f"WARNING: row count mismatch for {mismatches}")
        else:
            print(f"All {len(results)} tables loaded 1:1.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
