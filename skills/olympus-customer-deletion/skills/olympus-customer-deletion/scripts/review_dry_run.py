#!/usr/bin/env python3
"""
Parse delete_with_ai.py dry-run output and produce a reviewable CSV.

Each row = one file. Columns show EXISTS / NOT FOUND per storage system.
Only files with at least one existing location are included.

Usage:
    python3 review_dry_run.py --csv <deletion_list.csv> --output <review.csv>

The script runs the dry-run internally and parses its stdout.
Requires PYTHONPATH to include the otools/tools directory:
    PYTHONPATH=scripts/otools/src/otools/tools python3 ...

Or pass --dry-run-output if you already have the dry-run output saved to a file:
    python3 review_dry_run.py --dry-run-output dryrun.txt --output review.csv
"""

import argparse
import csv
import os
import re
import subprocess
import sys

# Maps path prefix patterns → short column name
LOCATION_PATTERNS = [
    (r"automation_drop/prod/",                         "s3_prod"),
    (r"automation_drop/dev/",                          "s3_dev"),
    (r"^sftp/",                                        "s3_sftp"),
    (r"/mnt/use-prod-sftpraw/etl_root_dir/",          "sftp_old_etl"),
    (r"/mnt/use-prod-sftpraw/sftp-home/",             "sftp_old_home"),
    (r"/sftp-home/",                                   "sftp_new"),
    (r"zeus_metadata",                                 "mysql"),
]

COLUMNS = ["filename"] + [col for _, col in LOCATION_PATTERNS] + ["exists_count"]


def classify_path(path):
    for pattern, col in LOCATION_PATTERNS:
        if re.search(pattern, path):
            return col
    return None


def parse_dry_run_output(text):
    """
    Parse dry-run stdout into a list of dicts:
      { "filename": str, "s3_prod": "EXISTS"|"NOT FOUND", ... }
    """
    results = []
    current = None

    for line in text.splitlines():
        # New file block: "📄 N. filename.txt"
        file_match = re.match(r"\s*📄\s+\d+\.\s+(.+)", line)
        if file_match:
            if current:
                results.append(current)
            current = {col: "" for col in COLUMNS}
            current["filename"] = file_match.group(1).strip()
            current["exists_count"] = 0
            continue

        if current is None:
            continue

        # EXISTS line
        exists_match = re.match(r"\s+✓ EXISTS\s+(.+)", line)
        if exists_match:
            path = exists_match.group(1).strip()
            col = classify_path(path)
            if col:
                current[col] = "EXISTS"
                current["exists_count"] += 1
            continue

        # NOT FOUND line
        notfound_match = re.match(r"\s+✗ NOT FOUND\s+(.+)", line)
        if notfound_match:
            path = notfound_match.group(1).strip()
            col = classify_path(path)
            if col and not current[col]:
                current[col] = "NOT FOUND"
            continue

        # MySQL line  (✓ or ✗ MySQL rows)
        mysql_match = re.match(r"\s+([✓✗]) MySQL rows\s+(.+)", line)
        if mysql_match:
            status = "EXISTS" if mysql_match.group(1) == "✓" else "NOT FOUND"
            current["mysql"] = status
            if status == "EXISTS":
                current["exists_count"] += 1

    if current:
        results.append(current)

    return results


def run_dry_run(csv_path):
    """Run delete_with_ai.py --dry-run and return stdout."""
    script = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..", "scripts", "otools", "src", "otools", "tools", "delete_with_ai.py"
    )
    # Try to find delete_with_ai.py relative to repo root
    repo_root = os.environ.get("OLYMPUS_ROOT", os.getcwd())
    script = os.path.join(repo_root, "scripts", "otools", "src", "otools", "tools", "delete_with_ai.py")

    env = os.environ.copy()
    tools_dir = os.path.join(repo_root, "scripts", "otools", "src", "otools", "tools")
    env["PYTHONPATH"] = tools_dir + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, script, "--csv", csv_path, "--dry-run", "--no-ai", "--skip-mysql"],
        capture_output=True, text=True, env=env
    )
    return result.stdout + result.stderr


def main():
    parser = argparse.ArgumentParser(description="Parse dry-run output into a reviewable CSV")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--csv", help="Deletion list CSV — script runs dry-run automatically")
    group.add_argument("--dry-run-output", help="Path to saved dry-run stdout text file")
    parser.add_argument("--output", required=True, help="Output review CSV path")
    parser.add_argument("--repo-root", default=os.getcwd(), help="Path to olympus repo root")
    args = parser.parse_args()

    os.environ["OLYMPUS_ROOT"] = args.repo_root

    if args.dry_run_output:
        with open(args.dry_run_output) as f:
            text = f.read()
    else:
        print(f"Running dry-run on: {args.csv}")
        print("This may take a minute...\n")
        text = run_dry_run(args.csv)

    records = parse_dry_run_output(text)

    if not records:
        print("ERROR: No file records found in dry-run output. Check that the dry-run ran correctly.")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    # Summary table
    total_files = len(records)
    files_with_data = sum(1 for r in records if r["exists_count"] > 0)

    print(f"Review CSV written: {args.output}")
    print(f"  Total files: {total_files}")
    print(f"  Files with at least one location found: {files_with_data}")
    print(f"  Files with no data anywhere: {total_files - files_with_data}")

    print(f"\n{'Filename':<55} {'s3p':^5} {'s3d':^5} {'s3s':^5} {'sftp_o':^7} {'sftp_n':^7} {'mysql':^7} {'hits':^5}")
    print("-" * 100)
    for r in records:
        def mark(col):
            v = r.get(col, "")
            return "✓" if v == "EXISTS" else ("✗" if v == "NOT FOUND" else "-")
        name = r["filename"][:52] + "..." if len(r["filename"]) > 55 else r["filename"]
        print(f"{name:<55} {mark('s3_prod'):^5} {mark('s3_dev'):^5} {mark('s3_sftp'):^5} "
              f"{mark('sftp_old_etl'):^7} {mark('sftp_new'):^7} {mark('mysql'):^7} {r['exists_count']:^5}")

    print(f"\nColumn key: s3p=S3 prod, s3d=S3 dev, s3s=S3 sftp, sftp_o=SFTP old, sftp_n=SFTP new, mysql=Zeus")
    print(f"\nReview {args.output} then confirm to proceed with live deletion.")


if __name__ == "__main__":
    main()
