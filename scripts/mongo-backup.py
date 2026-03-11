#!/usr/bin/env python3
"""Rolling MongoDB backup — dump all collections to gzipped JSON.

Usage:
    python mongo-backup.py backup              # create daily backup + rotate
    python mongo-backup.py restore [path]      # restore from backup (latest daily if no path)
    python mongo-backup.py list                # list available backups

Requires MONGO_URI_SIGNALS env var. Loads .env from $STACK/.env if available.
"""
import gzip
import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------
stack = os.environ.get("STACK", os.path.expanduser("~/augur"))
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(stack, ".env"))
except ImportError:
    pass

from bson import json_util  # pymongo dependency — handles ObjectId, datetime, etc.
from pymongo import MongoClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", os.path.expanduser("~/backups/mongo")))
RETENTION = {"daily": 7, "weekly": 28, "monthly": 90}  # max age in days


def _connect():
    """Return (client, db) from MONGO_URI_SIGNALS."""
    uri = os.environ.get("MONGO_URI_SIGNALS", "")
    if not uri:
        print("ERROR: MONGO_URI_SIGNALS not set", file=sys.stderr)
        sys.exit(1)
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()
    except Exception:
        db = client.signals
    return client, db


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
def backup():
    """Dump all collections to a single gzipped JSON file with rolling rotation."""
    client, db = _connect()
    stamp = datetime.utcnow().strftime("%Y-%m-%d")

    # Dump all collections
    out = BACKUP_DIR / "daily" / f"signals-{stamp}.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    total_docs = 0
    for name in sorted(db.list_collection_names()):
        docs = list(db[name].find())
        data[name] = docs
        total_docs += len(docs)

    with gzip.open(str(out), "wt", encoding="utf-8") as f:
        json.dump(data, f, default=json_util.default, ensure_ascii=False)

    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"Backed up {len(data)} collections ({total_docs} docs, {size_mb:.1f} MB) to {out}")

    # Promote to weekly (Sunday) / monthly (1st of month)
    dow = datetime.utcnow().isoweekday()  # 7 = Sunday
    day = datetime.utcnow().day
    if dow == 7:
        weekly_dir = BACKUP_DIR / "weekly"
        weekly_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(out), str(weekly_dir / out.name))
        print(f"Promoted to weekly: {weekly_dir / out.name}")
    if day == 1:
        monthly_dir = BACKUP_DIR / "monthly"
        monthly_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(out), str(monthly_dir / out.name))
        print(f"Promoted to monthly: {monthly_dir / out.name}")

    # Rotate old dumps
    for tier, max_days in RETENTION.items():
        tier_dir = BACKUP_DIR / tier
        if not tier_dir.exists():
            continue
        cutoff = datetime.utcnow() - timedelta(days=max_days)
        for f in sorted(tier_dir.glob("*.json.gz")):
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                print(f"Rotated: {f}")

    client.close()


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
def restore(path=None):
    """Restore from a gzipped JSON backup. Uses latest daily if no path given."""
    if path is None:
        daily_dir = BACKUP_DIR / "daily"
        if not daily_dir.exists():
            print("ERROR: No daily backups found", file=sys.stderr)
            sys.exit(1)
        candidates = sorted(daily_dir.glob("*.json.gz"), reverse=True)
        if not candidates:
            print("ERROR: No backup files found", file=sys.stderr)
            sys.exit(1)
        path = str(candidates[0])

    p = Path(path)
    if not p.exists():
        print(f"ERROR: Backup file not found: {path}", file=sys.stderr)
        sys.exit(1)

    client, db = _connect()

    with gzip.open(str(p), "rt", encoding="utf-8") as f:
        data = json.load(f, object_hook=json_util.object_hook)

    total_docs = 0
    for name, docs in sorted(data.items()):
        if docs:
            db[name].drop()
            db[name].insert_many(docs)
            total_docs += len(docs)
            print(f"  Restored {name}: {len(docs)} docs")

    print(f"Restored {len(data)} collections ({total_docs} docs) from {p.name}")
    print("NOTE: Restart trading server to recreate indexes/TTLs (supervisorctl restart trading)")
    client.close()


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
def list_backups():
    """List available backups by tier."""
    if not BACKUP_DIR.exists():
        print("No backups found")
        return
    for tier in ("daily", "weekly", "monthly"):
        tier_dir = BACKUP_DIR / tier
        if not tier_dir.exists():
            continue
        files = sorted(tier_dir.glob("*.json.gz"), reverse=True)
        if files:
            print(f"\n{tier.upper()} (keep {RETENTION[tier]} days):")
            for f in files:
                size_mb = f.stat().st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                print(f"  {f.name}  ({size_mb:.1f} MB, {mtime})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "backup":
        backup()
    elif cmd == "restore":
        restore(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "list":
        list_backups()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
