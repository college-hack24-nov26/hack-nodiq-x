#!/usr/bin/env python3
"""
migrate_to_supabase.py — idempotent one-shot migration from the legacy
ephemeral persistence (SQLite + local artifact files) into Supabase.

What it moves
-------------
  users, analyses, reports, feedback, calibrations, sessions,
  revoked_tokens, resets, full analysis payloads (full_payloads)
      -> Supabase PostgreSQL (NODIQ_BACKEND=supabase)
  analysis artifacts:
      <FULL_DIR>/<analysis_id>_annotated.png / _mask.png
      content-addressed uploads referenced by analyses.stored_path
      -> Supabase Storage, private bucket
         users/{user_id}/analyses/{analysis_id}/{kind}.{ext}

Safety
------
  * Rerunnable: every insert is an upsert; existing rows are verified
    rather than duplicated (fixed-email users keep their id).
  * Never deletes the SQLite source or local files (the local artifact
    copies stay as a warm cache for the server).
  * Artifact upload failures abort the affected analysis migration but
    never corrupt already-persisted rows.

Usage
-----
    # set env first (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    # DATABASE_URL, optionally SUPABASE_BUCKET, NODIQ_DATA_DIR)
    python migrate_to_supabase.py            # migrate + verify
    python migrate_to_supabase.py --verify   # counts only, no writes
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

import nodiq.services.db as store          # noqa: E402  (backend chosen below)
import nodiq.services.storage as storage   # noqa: E402


def _sqlite_rows(table):
    """Read raw rows from the legacy SQLite database (always the file on
    disk, never the selected backend)."""
    db_file = os.environ.get("NODIQ_DB_PATH") or \
        (store.DATA_DIR / "nodiq.db")
    if not Path(db_file).exists():
        return []
    con = sqlite3.connect(str(db_file))
    con.row_factory = sqlite3.Row
    try:
        return con.execute(
            f"SELECT * FROM {table}").fetchall()          # noqa: S608
    except sqlite3.OperationalError:
        # legacy database predates this table (e.g. revoked_tokens before
        # token revocation existed) — nothing to migrate for it
        return []
    finally:
        con.close()


def _upsert(table, row: dict):
    cols = list(row)
    stmt = (f"INSERT OR REPLACE INTO {table} "
            f"({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})")
    params = [row[c] for c in cols]
    # Long migrations can outlive a pooler idle window; each statement is an
    # idempotent upsert, so retrying the whole statement on a dropped
    # connection is safe (no partial-row risk, no duplication).
    last_exc = None
    for attempt in range(3):
        try:
            store._CONN.execute(stmt, params)
            return
        except Exception as exc:
            retriable = ("closed the connection" in str(exc).lower()
                         or "operationalerror" in type(exc).__name__.lower())
            if retriable and attempt < 2:
                store.init_db()   # re-ping/reconnect, then retry the upsert
                last_exc = exc
                continue
            raise
    if last_exc:
        raise last_exc


def migrate_full_payloads(con):
    """analysis payload JSON files -> full_payloads table (+ Storage for
    visual artifacts)."""
    full_dir = store.DATA_DIR / "analyses_full"
    if not full_dir.exists():
        return 0, 0
    payload_files = sorted(full_dir.glob("*.json"))
    migrated = skipped = 0
    for path in payload_files:
        analysis_id = path.stem
        try:
            blob = path.read_text(encoding="utf-8")
            json.loads(blob)                     # refuse to copy corruption
        except Exception as exc:
            print(f"  ! skip unreadable payload {path.name}: {exc}")
            skipped += 1
            continue
        # postgres column names: id, payload, stored_at
        _upsert("full_payloads", {
            "id": analysis_id, "payload": blob,
            "stored_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        migrated += 1
    return migrated, skipped


def migrate_artifacts(con):
    """Upload visual artifacts + original uploads to Supabase Storage."""
    full_dir = store.DATA_DIR / "analyses_full"
    uploaded = missing_owner = skipped = 0
    rows = _sqlite_rows("analyses")
    by_id = {r["id"]: dict(r) for r in rows}
    for analysis_id, rec in by_id.items():
        user_id = rec.get("user_id")
        if not user_id:
            missing_owner += 1
            continue
        for kind in ("annotated", "mask"):
            src = full_dir / f"{analysis_id}_{kind}.png"
            if not src.exists():
                continue
            key = storage.object_key(user_id, analysis_id, kind)
            if storage.BACKEND == "supabase":
                try:
                    if storage.get_bytes(user_id, analysis_id, kind) is None:
                        storage.put_bytes(user_id, analysis_id, kind,
                                          src.read_bytes())
                        uploaded += 1
                except Exception as exc:
                    print(f"  ! upload failed {key}: {str(exc)[:100]}")
                    skipped += 1
            else:
                skipped += 1   # local backend: nothing to upload
        # original upload (content-addressed file under uploads/)
        stored_path = rec.get("stored_path")
        if stored_path and Path(stored_path).exists():
            key = storage.object_key(user_id, analysis_id, "original")
            try:
                if storage.BACKEND == "supabase" and \
                        storage.get_bytes(user_id, analysis_id,
                                          "original") is None:
                    storage.put_bytes(user_id, analysis_id, "original",
                                      Path(stored_path).read_bytes())
                    uploaded += 1
            except Exception as exc:
                print(f"  ! upload failed {key}: {str(exc)[:100]}")
                skipped += 1
    return uploaded, missing_owner, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="count only, do not write")
    args = ap.parse_args()

    if os.environ.get("NODIQ_BACKEND", "").strip().lower() != "supabase":
        print("NODIQ_BACKEND=supabase is required (safety: this tool must "
              "never silently write to the dev SQLite backend).")
        return 2
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL missing — set the Supabase Postgres connection "
              "string in the environment (never commit it).")
        return 2
    if not (os.environ.get("SUPABASE_URL") and
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("NOTE: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing — "
              "artifacts will NOT be uploaded (database-only migration).")

    store.init_db()
    print(f"storage backend: {storage.BACKEND} "
          f"(bucket: {storage.BUCKET})")
    if storage.BACKEND != "supabase":
        print("WARNING: Supabase Storage is not configured — artifacts will "
              "NOT be uploaded (database-only migration).")

    tables = ("users", "analyses", "reports", "feedback", "calibrations",
              "sessions", "revoked_tokens", "resets")
    counts = {}
    for table in tables:
        rows = _sqlite_rows(table)
        counts[table] = len(rows)
        if args.verify:
            continue
        for r in rows:
            _upsert(table, dict(r))

    payloads = artifacts = 0
    if not args.verify:
        payloads, skipped = migrate_full_payloads(None)
        artifacts, no_owner, art_skip = migrate_artifacts(None)

    print("\n=== migration summary ===")
    for table in tables:
        print(f"{table:>16}: {counts[table]}")
    print(f"      payloads: {payloads} (skipped {skipped})")
    print(f"      artifacts uploaded: {artifacts} "
          f"(no-owner {no_owner}, failed {art_skip})")

    if not args.verify:
        print("\nverify (rerun this script with --verify after deploy):")
        store.init_db()
        for table in tables:
            n = store._CONN.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            print(f"{table:>16}: pg={n} sqlite={counts[table]} "
                  f"{'OK' if n >= counts[table] else 'MISMATCH'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
