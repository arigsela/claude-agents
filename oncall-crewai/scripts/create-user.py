#!/usr/bin/env python3
"""Create a user in the oncall-crewai user database.

Usage:
    python scripts/create-user.py --username admin --password changeme
    python scripts/create-user.py --username admin --password changeme --db /data/users.db
    python scripts/create-user.py --list
    python scripts/create-user.py --list --db /data/users.db

For use inside the orchestrator pod:
    kubectl exec -it -n oncall-crewai deploy/crewai-orchestrator -- \
        python /app/scripts/create-user.py --username admin --password changeme
"""

import argparse
import os
import sys

# Add src to path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from orchestrator.user_manager import UserManager


def main():
    parser = argparse.ArgumentParser(description="Manage oncall-crewai users")
    parser.add_argument("--username", help="Username to create")
    parser.add_argument("--password", help="Password for the user")
    parser.add_argument(
        "--db",
        default=os.getenv("USERS_DB_PATH", "/data/users.db"),
        help="Path to users SQLite database",
    )
    parser.add_argument("--list", action="store_true", help="List all users")

    args = parser.parse_args()

    um = UserManager(db_path=args.db)

    if args.list:
        users = um.list_users()
        if not users:
            print("No users found.")
            return
        print(f"{'Username':<20} {'User ID':<40} {'Created'}")
        print("-" * 80)
        for u in users:
            print(f"{u['username']:<20} {u['user_id']:<40} {u['created_at']}")
        return

    if not args.username or not args.password:
        parser.error("--username and --password are required (or use --list)")

    try:
        user = um.create_user(args.username, args.password)
        print(f"User created: {user.username} (ID: {user.user_id})")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
