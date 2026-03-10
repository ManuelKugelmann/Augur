#!/usr/bin/env python3
"""Extract profile data from MongoDB Atlas into seed JSON files.

Reads all profiles_{kind} collections from Atlas and writes them as
individual JSON files under profiles/{region}/{kind}/{id}.json.
This is the reverse of seed_profiles() in src/store/server.py.

Only overwrites files whose content has actually changed (avoids noisy diffs).

Usage:
    # Extract all profiles from Atlas
    python scripts/extract-seeds.py

    # Dry run — show what would be written without writing
    python scripts/extract-seeds.py --dry-run

    # Custom profiles directory
    python scripts/extract-seeds.py --profiles-dir /tmp/profiles

Requires MONGO_URI_SIGNALS env var (MongoDB Atlas connection string).
"""
import json
import os
import sys
from pathlib import Path

# Load .env if available
stack = os.environ.get("STACK", os.path.expanduser("~/assist"))
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(stack, ".env"))
except ImportError:
    pass

from pymongo import MongoClient

VALID_KINDS = frozenset({
    "countries", "stocks", "etfs", "crypto", "indices", "sources",
    "commodities", "crops", "materials", "products", "companies",
    "regions",
})

# Fields to strip from extracted documents (internal MongoDB/store fields)
STRIP_FIELDS = {"_id", "_id_str", "_seeded"}

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILES_DIR = REPO_ROOT / "profiles"


def connect(uri: str) -> MongoClient:
    """Connect to MongoDB Atlas."""
    return MongoClient(uri)


def extract_profiles(db, profiles_dir: Path, dry_run: bool = False) -> dict:
    """Extract all profiles from MongoDB to JSON seed files.

    Args:
        db: pymongo Database object (signals database).
        profiles_dir: Path to profiles/ directory.
        dry_run: If True, don't write files — just report what would change.

    Returns: {kind: {written: N, unchanged: N, total: N}} summary.
    """
    results = {}

    for kind in sorted(VALID_KINDS):
        col_name = f"profiles_{kind}"
        col = db[col_name]
        docs = list(col.find().sort("_id_str", 1))

        written = 0
        unchanged = 0

        for doc in docs:
            profile_id = doc.get("_id_str")
            region = doc.get("region", "global")

            if not profile_id:
                continue

            # Strip internal fields
            clean = {k: v for k, v in doc.items() if k not in STRIP_FIELDS}

            # Serialize to pretty JSON
            new_content = json.dumps(clean, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

            # Build output path
            out_dir = profiles_dir / region / kind
            out_path = out_dir / f"{profile_id}.json"

            # Check if content changed
            if out_path.exists():
                existing = out_path.read_text(encoding="utf-8")
                if existing == new_content:
                    unchanged += 1
                    continue

            if not dry_run:
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path.write_text(new_content, encoding="utf-8")

            written += 1

        if docs:
            results[kind] = {"written": written, "unchanged": unchanged, "total": len(docs)}

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract profiles from MongoDB Atlas into seed JSON files"
    )
    parser.add_argument(
        "--profiles-dir",
        default=os.environ.get("PROFILES_DIR", str(DEFAULT_PROFILES_DIR)),
        help=f"Path to profiles directory (default: {DEFAULT_PROFILES_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing",
    )
    args = parser.parse_args()

    uri = os.environ.get("MONGO_URI_SIGNALS")
    if not uri:
        print("ERROR: MONGO_URI_SIGNALS env var required", file=sys.stderr)
        sys.exit(1)

    profiles_dir = Path(args.profiles_dir)

    if args.dry_run:
        print("[DRY RUN — no files will be written]\n")

    client = connect(uri)
    db = client.get_default_database()

    results = extract_profiles(db, profiles_dir, dry_run=args.dry_run)

    client.close()

    # Summary
    total_written = 0
    total_unchanged = 0
    total_docs = 0
    for kind, stats in sorted(results.items()):
        w, u, t = stats["written"], stats["unchanged"], stats["total"]
        total_written += w
        total_unchanged += u
        total_docs += t
        status = f"  {kind}: {t} profiles"
        if w:
            status += f", {w} written"
        if u:
            status += f", {u} unchanged"
        print(status)

    print(f"\nTotal: {total_docs} profiles, {total_written} written, {total_unchanged} unchanged")

    if total_written == 0 and not args.dry_run:
        print("No changes — seed files are up to date.")


if __name__ == "__main__":
    main()
