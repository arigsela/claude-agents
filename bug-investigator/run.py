"""Entry point for the action's steps. Stdlib only; run with `python3 -I run.py <command> ...`.

-I keeps the working directory (the app checkout) and PYTHON* variables off the import path.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

COMMANDS = ("hook", "gather", "prep", "verify", "trail", "render", "post", "selftest",
            "fix-prep", "fix-check", "propose")


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: run.py {{{'|'.join(COMMANDS)}}} ...", file=sys.stderr)
        return 64
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "hook":
        from bug_investigator import hook as m
    elif cmd == "gather":
        from bug_investigator import gather as m
    elif cmd in ("prep", "selftest"):
        from bug_investigator import settings as m
        if cmd == "selftest":
            return m.selftest_main(rest)
    elif cmd == "verify":
        from bug_investigator import verify as m
    elif cmd == "trail":
        from bug_investigator import trail as m
    elif cmd == "render":
        from bug_investigator import render as m
    elif cmd in ("fix-prep", "fix-check", "propose"):
        from bug_investigator import fix as m
        return {"fix-prep": m.prep_main, "fix-check": m.check_main, "propose": m.propose_main}[cmd](rest)
    else:
        from bug_investigator import tickets as m
    return m.main(rest)


if __name__ == "__main__":
    sys.exit(main())
