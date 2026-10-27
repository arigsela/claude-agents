"""What the investigating agent may touch. One module, used by the hook and by verify.

Queries (P0): every Loki stream selector and every Prometheus vector selector must select
Taskboard. The Grafana token can read every namespace, so this check is the boundary.
It tokenizes the query (strings are single tokens, so a `{` inside `line_format "..."` is
never mistaken for a selector), then checks each selector. Anything it does not understand
is rejected.

Also here: the Bash allowlist (read-only git and gh, no paths outside the checkouts) and the
Read/Grep/Glob path check. Every function returns None when allowed, else a reason string.
"""

from __future__ import annotations

import os
import re
import shlex

NAMESPACE = "taskboard"
LOKI_UID = "loki"
PROM_UID = "PBFA97CFB590B2093"
MAX_QUERY_LEN = 4000


class ScopeError(Exception):
    pass


# ---------------------------------------------------------------------------------- tokens

_TWO_CHAR_OPS = ("=~", "!~", "!=", "==", ">=", "<=", "|=", "|~", "|>", "!>")
_ONE_CHAR_OPS = "=<>+-*/%^|!@"
_PUNCT = "{}()[],:"


def _is_ident_start(c: str) -> bool:
    return ("a" <= c <= "z") or ("A" <= c <= "Z") or c == "_"


def _is_ident_char(c: str) -> bool:
    return _is_ident_start(c) or ("0" <= c <= "9") or c == ":"


def _is_num_char(c: str) -> bool:
    return ("0" <= c <= "9") or ("a" <= c <= "z") or ("A" <= c <= "Z") or c in "._"


def _tokenize(q: str, lang: str) -> list[tuple[str, str]]:
    """Split a LogQL or PromQL query into (kind, value) tokens.

    kinds: str (raw, with quotes), ident, num (numbers and durations), punct, op.
    """
    toks: list[tuple[str, str]] = []
    i, n = 0, len(q)
    while i < n:
        c = q[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == '"' or (c == "'" and lang == "promql"):
            j = i + 1
            while j < n and q[j] != c:
                if q[j] == "\n":
                    raise ScopeError("newline inside a string")
                j += 2 if q[j] == "\\" else 1
            if j >= n:
                raise ScopeError("unterminated string")
            toks.append(("str", q[i : j + 1]))
            i = j + 1
            continue
        if c == "`":
            j = q.find("`", i + 1)
            if j < 0:
                raise ScopeError("unterminated string")
            toks.append(("str", q[i : j + 1]))
            i = j + 1
            continue
        if c == "'":
            raise ScopeError("single quotes are not LogQL strings")
        if c == "#":
            raise ScopeError("comments are not allowed")
        if _is_ident_start(c):
            j = i + 1
            while j < n and _is_ident_char(q[j]):
                j += 1
            toks.append(("ident", q[i:j]))
            i = j
            continue
        if ("0" <= c <= "9") or (c == "." and i + 1 < n and "0" <= q[i + 1] <= "9"):
            j = i + 1
            while j < n:
                if _is_num_char(q[j]):
                    j += 1
                elif q[j] in "+-" and q[j - 1] in "eE" and j + 1 < n and "0" <= q[j + 1] <= "9":
                    j += 1
                else:
                    break
            toks.append(("num", q[i:j]))
            i = j
            continue
        if q[i : i + 2] in _TWO_CHAR_OPS:
            toks.append(("op", q[i : i + 2]))
            i += 2
            continue
        if c in _PUNCT:
            toks.append(("punct", c))
            i += 1
            continue
        if c in _ONE_CHAR_OPS:
            toks.append(("op", c))
            i += 1
            continue
        raise ScopeError(f"unexpected character {c!r}")
    return toks


def _is(tok: tuple[str, str] | None, value: str) -> bool:
    return tok is not None and tok[0] in ("punct", "op") and tok[1] == value


def _parse_matchers(toks: list[tuple[str, str]], i: int) -> tuple[list[tuple[str, str, str]], int]:
    """Parse `{ name op "value", ... }` starting at toks[i] == '{'. Returns (matchers, index after '}')."""
    matchers: list[tuple[str, str, str]] = []
    i += 1
    while True:
        if i >= len(toks):
            raise ScopeError("unbalanced { in selector")
        t = toks[i]
        if _is(t, "}"):
            return matchers, i + 1
        if t[0] != "ident" or ":" in t[1]:
            raise ScopeError(f"unexpected {t[1]!r} in selector")
        if i + 2 >= len(toks):
            raise ScopeError("incomplete matcher in selector")
        op, val = toks[i + 1], toks[i + 2]
        if op[0] != "op" or op[1] not in ("=", "!=", "=~", "!~"):
            raise ScopeError(f"unexpected {op[1]!r} after label {t[1]!r}")
        if val[0] != "str":
            raise ScopeError(f"label {t[1]!r} needs a quoted value")
        matchers.append((t[1], op[1], val[1]))
        i += 3
        if i < len(toks) and _is(toks[i], ","):
            i += 1
        elif not (i < len(toks) and _is(toks[i], "}")):
            raise ScopeError("expected , or } in selector")


def _namespace_problem(matchers: list[tuple[str, str, str]], namespace: str) -> tuple[bool, str | None]:
    """(has the exact namespace matcher, reason if any namespace matcher is not exactly it)."""
    wanted = {f'"{namespace}"', f"`{namespace}`", f"'{namespace}'"}
    found = False
    for name, op, raw in matchers:
        if name != "namespace":
            continue
        if op != "=" or raw not in wanted:
            return False, f'namespace matcher namespace{op}{raw} is not namespace="{namespace}"'
        found = True
    return found, None


def _selector_text(matchers: list[tuple[str, str, str]]) -> str:
    return "{" + ", ".join(f"{n}{o}{v}" for n, o, v in matchers) + "}"


def _basic(q) -> str | None:
    if not isinstance(q, str) or not q.strip():
        return "empty query"
    if len(q) > MAX_QUERY_LEN:
        return f"query longer than {MAX_QUERY_LEN} characters"
    return None


# ---------------------------------------------------------------------------------- LogQL


def check_logql(q, namespace: str = NAMESPACE) -> str | None:
    """Every stream selector must contain namespace="<namespace>" (exact equality)."""
    bad = _basic(q)
    if bad:
        return bad
    try:
        toks = _tokenize(q, "logql")
        selectors = 0
        i = 0
        while i < len(toks):
            t = toks[i]
            if _is(t, "{"):
                matchers, i = _parse_matchers(toks, i)
                found, problem = _namespace_problem(matchers, namespace)
                if problem:
                    return problem
                if not found:
                    return f'stream selector {_selector_text(matchers)} lacks namespace="{namespace}"'
                selectors += 1
                continue
            if _is(t, "}"):
                return "unbalanced } in query"
            i += 1
    except ScopeError as e:
        return str(e)
    if selectors == 0:
        return "no stream selector"
    return None


def is_scoped_stream_selector(q, namespace: str = NAMESPACE) -> str | None:
    """A bare stream selector, e.g. the `matcher` of list_loki_label_values."""
    bad = check_logql(q, namespace)
    if bad:
        return bad
    toks = _tokenize(q, "logql")
    if not (_is(toks[0], "{") and _is(toks[-1], "}")) or sum(1 for t in toks if _is(t, "{")) != 1:
        return "matcher must be a single stream selector like {namespace=\"%s\"}" % namespace
    return None


# ---------------------------------------------------------------------------------- PromQL

AGGREGATIONS = {
    "sum", "min", "max", "avg", "group", "stddev", "stdvar", "count", "count_values",
    "bottomk", "topk", "quantile", "limitk", "limit_ratio",
}
FUNCTIONS = {
    "abs", "absent", "absent_over_time", "ceil", "changes", "clamp", "clamp_max", "clamp_min",
    "day_of_month", "day_of_week", "day_of_year", "days_in_month", "delta", "deriv", "exp",
    "floor", "histogram_avg", "histogram_count", "histogram_sum", "histogram_fraction",
    "histogram_quantile", "histogram_stddev", "histogram_stdvar", "double_exponential_smoothing",
    "holt_winters", "hour", "idelta", "increase", "irate", "label_join", "label_replace", "ln",
    "log2", "log10", "minute", "month", "predict_linear", "rate", "resets", "round", "scalar",
    "sgn", "sort", "sort_desc", "sort_by_label", "sort_by_label_desc", "sqrt", "time",
    "timestamp", "vector", "year", "avg_over_time", "min_over_time", "max_over_time",
    "sum_over_time", "count_over_time", "quantile_over_time", "stddev_over_time",
    "stdvar_over_time", "last_over_time", "present_over_time", "mad_over_time", "acos", "acosh",
    "asin", "asinh", "atan", "atanh", "cos", "cosh", "sin", "sinh", "tan", "tanh", "deg", "rad",
    "pi", "start", "end",
}
LABEL_LIST_KEYWORDS = {"by", "without", "on", "ignoring", "group_left", "group_right"}
BINARY_KEYWORDS = {"and", "or", "unless", "atan2", "bool"}


def check_promql(q, namespace: str = NAMESPACE) -> str | None:
    """Every vector selector needs namespace="<namespace>" or a `<namespace>_` metric name."""
    bad = _basic(q)
    if bad:
        return bad
    prefix = f"{namespace}_"
    try:
        toks = _tokenize(q, "promql")
        n = len(toks)
        selectors = 0
        i = 0
        while i < n:
            t = toks[i]
            nxt = toks[i + 1] if i + 1 < n else None
            if t[0] == "ident":
                name = t[1]
                if name in LABEL_LIST_KEYWORDS:
                    if _is(nxt, "("):
                        j = i + 2
                        while j < n and not _is(toks[j], ")"):
                            if not (toks[j][0] == "ident" or _is(toks[j], ",")):
                                return f"unexpected {toks[j][1]!r} in {name}(...)"
                            j += 1
                        if j >= n:
                            return f"unbalanced {name}("
                        i = j + 1
                        continue
                    if name in ("group_left", "group_right"):
                        i += 1
                        continue
                    return f"{name} must be followed by a label list"
                if name in BINARY_KEYWORDS:
                    i += 1
                    continue
                if name == "offset":
                    j = i + 1
                    if _is(toks[j] if j < n else None, "-"):
                        j += 1
                    if j >= n or toks[j][0] != "num":
                        return "offset needs a duration"
                    i = j + 1
                    continue
                if name.lower() in ("inf", "nan"):
                    i += 1
                    continue
                if _is(nxt, "("):
                    if name in FUNCTIONS or name in AGGREGATIONS:
                        i += 1
                        continue
                    return f"unknown or disallowed function {name}()"
                if name in AGGREGATIONS and nxt is not None and nxt[0] == "ident" and nxt[1] in ("by", "without"):
                    i += 1
                    continue
                # A metric name, with or without matchers.
                if _is(nxt, "{"):
                    matchers, i = _parse_matchers(toks, i + 1)
                else:
                    matchers, i = [], i + 1
                found, problem = _namespace_problem(matchers, namespace)
                if problem:
                    return problem
                if not (found or name.startswith(prefix)):
                    sel = name + (_selector_text(matchers) if matchers else "")
                    return f'selector {sel} lacks namespace="{namespace}" and is not a {prefix}* metric'
                selectors += 1
                continue
            if _is(t, "{"):
                matchers, i = _parse_matchers(toks, i)
                found, problem = _namespace_problem(matchers, namespace)
                if problem:
                    return problem
                if not found:
                    return f'selector {_selector_text(matchers)} lacks namespace="{namespace}"'
                selectors += 1
                continue
            if _is(t, "}"):
                return "unbalanced } in query"
            if _is(t, "["):
                j = i + 1
                while j < n and not _is(toks[j], "]"):
                    if not (toks[j][0] == "num" or _is(toks[j], ":")):
                        return f"unexpected {toks[j][1]!r} in [...]"
                    j += 1
                if j >= n:
                    return "unbalanced ["
                i = j + 1
                continue
            if _is(t, "]"):
                return "unbalanced ] in query"
            i += 1
    except ScopeError as e:
        return str(e)
    if selectors == 0:
        return "no metric selector"
    return None


# ---------------------------------------------------------------------------------- tools

# tool -> (datasource uid, query field, query language, allowed input keys)
GRAFANA_TOOLS = {
    "query_loki_logs": (LOKI_UID, "logql", "logql", {
        "datasourceUid", "logql", "startRfc3339", "endRfc3339", "limit", "direction",
        "queryType", "stepSeconds", "format"}),
    "query_loki_stats": (LOKI_UID, "logql", "logql", {
        "datasourceUid", "logql", "startRfc3339", "endRfc3339"}),
    "query_prometheus": (PROM_UID, "expr", "promql", {
        "datasourceUid", "expr", "startTime", "endTime", "stepSeconds", "queryType", "projectName"}),
    "list_loki_label_names": (LOKI_UID, "matcher", "selector", {
        "datasourceUid", "matcher", "startRfc3339", "endRfc3339"}),
    "list_loki_label_values": (LOKI_UID, "matcher", "selector", {
        "datasourceUid", "labelName", "matcher", "startRfc3339", "endRfc3339"}),
}
GRAFANA_PREFIX = "mcp__grafana__"


def check_tool_call(tool_name, tool_input, namespace: str = NAMESPACE) -> str | None:
    """A Grafana MCP call (full name `mcp__grafana__<tool>` or bare `<tool>`)."""
    if not isinstance(tool_name, str):
        return "tool name is not a string"
    name = tool_name
    if name.startswith(GRAFANA_PREFIX):
        name = name[len(GRAFANA_PREFIX):]
    elif name.startswith("mcp__"):
        return f"MCP tool {tool_name} is not allowed (only Grafana Loki/Prometheus queries)"
    if name not in GRAFANA_TOOLS:
        return f"tool {name} is not allowed; allowed: {', '.join(sorted(GRAFANA_TOOLS))}"
    if not isinstance(tool_input, dict):
        return "tool input is not an object"
    uid, field, lang, keys = GRAFANA_TOOLS[name]
    extra = sorted(set(tool_input) - keys)
    if extra:
        return f"unexpected parameters for {name}: {', '.join(extra)}"
    if tool_input.get("datasourceUid") != uid:
        return f"{name} must use datasourceUid {uid!r}, got {tool_input.get('datasourceUid')!r}"
    if tool_input.get("projectName"):
        return "projectName is not allowed"
    q = tool_input.get(field)
    if lang == "logql":
        return check_logql(q, namespace)
    if lang == "promql":
        return check_promql(q, namespace)
    if not q:
        return f'{name} needs a matcher like {{namespace="{namespace}"}}'
    return is_scoped_stream_selector(q, namespace)


def check_query(kind: str, q, namespace: str = NAMESPACE) -> str | None:
    if kind == "logql":
        return check_logql(q, namespace)
    if kind == "promql":
        return check_promql(q, namespace)
    return f"unknown query kind {kind!r}"


# ---------------------------------------------------------------------------------- Bash

ALLOWED_COMMANDS = (
    ("git", "log"), ("git", "show"), ("git", "blame"), ("git", "diff"),
    ("gh", "pr", "view"), ("gh", "pr", "list"), ("gh", "pr", "diff"),
    ("gh", "issue", "view"), ("gh", "issue", "list"),
)
# Options that read or write files outside the repo. git accepts unambiguous abbreviations of
# long options, so any prefix of these (from 3 characters on) is rejected too.
DANGEROUS_OPTIONS = (
    "--output", "--output-directory", "--contents", "--no-index", "--ext-diff",
    "--ignore-revs-file", "--exec", "--upload-pack", "--web",
)
SHORT_BANNED = {("git", "blame"): {"-S"}}
# The fix agent (mode "fix") may look at its own diff and run the exact sandboxed test command
# (run-tests.sh, passed in as `exact`), nothing else. Tests never run on the runner itself.
FIX_COMMANDS = (("git", "diff"), ("git", "status"))
SHELL_META = set(";&|<>(){}$`\n\r\\")


def check_bash(command, roots: list[str], mode: str = "full", exact: tuple[tuple[str, ...], ...] = ()) -> str | None:
    """Read-only git/gh commands only (fix mode: git diff/status, plus the commands in `exact`, matched
    argument for argument); no shell operators; no paths outside the checkouts."""
    if mode not in ("full", "fix"):
        return f"Bash is not available in {mode} mode"
    allowed_cmds = FIX_COMMANDS if mode == "fix" else ALLOWED_COMMANDS
    if not isinstance(command, str) or not command.strip():
        return "empty command"
    quote = None
    for c in command:
        if quote:
            if c == quote:
                quote = None
            elif c in "$`\n\r" or (quote == '"' and c == "\\"):
                return f"character {c!r} is not allowed in commands"
            continue
        if c in "'\"":
            quote = c
        elif c in SHELL_META:
            return f"shell operator {c!r} is not allowed; run one git or gh command at a time"
    if quote:
        return "unbalanced quote"
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return f"cannot parse command: {e}"
    real_roots = [os.path.realpath(r) for r in roots]
    if len(argv) >= 3 and argv[0] == "git" and argv[1] == "-C":
        if os.path.realpath(argv[2]) not in real_roots:
            return "git -C is only allowed with one of the checkouts"
        argv = ["git"] + argv[3:]
    if mode == "fix" and tuple(argv) in {tuple(x) for x in exact}:
        return None
    prefix = next((p for p in allowed_cmds if tuple(argv[: len(p)]) == p), None)
    if prefix is None:
        allowed = ", ".join([" ".join(p) for p in allowed_cmds] + [" ".join(x) + " (exactly)" for x in exact])
        return f"only these commands are allowed: {allowed}"
    for arg in argv[len(prefix):]:
        opt = arg.split("=", 1)[0]
        if opt.startswith("--") and len(opt) > 3 and any(d.startswith(opt) for d in DANGEROUS_OPTIONS):
            return f"option {opt} is not allowed"
        if opt in SHORT_BANNED.get(prefix, set()) or (opt.startswith("-S") and prefix == ("git", "blame")):
            return f"option {opt} is not allowed"
        if arg.startswith(("/", "~")) or arg == ".." or arg.startswith("../") or "/../" in arg or arg.endswith("/.."):
            return f"path {arg} is outside the checkouts"
    return None


# ---------------------------------------------------------------------------------- paths


def _inside(path: str, roots: list[str]) -> bool:
    real = os.path.realpath(path)
    for r in roots:
        rr = os.path.realpath(r)
        if real == rr or real.startswith(rr.rstrip(os.sep) + os.sep):
            return True
    return False


def check_path_tool(tool_name: str, tool_input, roots: list[str]) -> str | None:
    """Read/Grep/Glob must stay inside the checkouts (roots[0] is the working directory)."""
    if not isinstance(tool_input, dict):
        return "tool input is not an object"
    if not roots:
        return "no checkouts configured"
    cwd = roots[0]
    fields = {"Read": ("file_path",), "Grep": ("path",), "Glob": ("path",)}.get(tool_name, ())
    for f in fields:
        p = tool_input.get(f)
        if p in (None, ""):
            continue
        if not isinstance(p, str):
            return f"{f} is not a string"
        full = p if os.path.isabs(p) else os.path.join(cwd, p)
        if not _inside(full, roots):
            return f"{p} is outside the checkouts"
    if tool_name == "Glob":
        pat = tool_input.get("pattern", "")
        if isinstance(pat, str) and (pat.startswith(("/", "~")) or ".." in pat.split("/")):
            return f"glob pattern {pat} reaches outside the checkouts"
    return None


# ---------------------------------------------------------------------------------- writes (fix mode)

# The docs are the spec; workflows, agent settings, git internals, build and test configuration are
# never the fix. The Edit/Write hook and the patch filter both use protected_reason.
PROTECTED_DIRS = (".github", ".claude", "docs")
PROTECTED_NAMES = {
    "pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "pytest.ini", "conftest.py", "uv.lock", "poetry.lock",
    "Pipfile", "Pipfile.lock", "Makefile", "GNUmakefile", ".pre-commit-config.yaml", ".gitattributes", ".gitmodules",
    ".gitignore", ".mcp.json",
}
PROTECTED_PATTERNS = (re.compile(r"^requirements.*\.(txt|in)$"), re.compile(r"^Dockerfile"), re.compile(r"^Containerfile"))


def protected_reason(rel: str) -> str | None:
    """Why a repo-relative path may not be changed by a fix, or None."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "~")) or "\\" in rel or "\0" in rel:
        return f"{rel!r} is not a plain repo-relative path"
    parts = rel.split("/")
    if any(x in ("", ".", "..") for x in parts):
        return f"{rel} is not a normalized repo-relative path"
    if ".git" in parts:
        return f"{rel} is inside a .git directory"
    if parts[0] in PROTECTED_DIRS:
        return f"{rel} is under {parts[0]}/, which a fix may not change"
    name = parts[-1]
    if name in PROTECTED_NAMES or any(p.match(name) for p in PROTECTED_PATTERNS):
        return f"{rel} is build, test or tool configuration, which a fix may not change"
    if len(parts) == 1 and (name.startswith(".") or name.endswith((".cfg", ".ini", ".toml"))):
        return f"{rel} is configuration at the repo root, which a fix may not change"
    if parts[0].startswith("."):
        return f"{rel} is under a hidden directory at the repo root, which a fix may not change"
    return None


def check_write_path(tool_name: str, tool_input, root: str) -> str | None:
    """Edit/Write/MultiEdit/NotebookEdit: inside the app checkout, never a protected path."""
    if not isinstance(tool_input, dict):
        return "tool input is not an object"
    if not root:
        return "no checkout configured"
    p = tool_input.get("notebook_path") if tool_name == "NotebookEdit" else tool_input.get("file_path")
    if not isinstance(p, str) or not p:
        return "file_path is missing"
    full = p if os.path.isabs(p) else os.path.join(root, p)
    if not _inside(full, [root]):
        return f"{p} is outside the app checkout"
    real, rroot = os.path.realpath(full), os.path.realpath(root)
    if real == rroot:
        return "cannot write the checkout directory itself"
    return protected_reason(os.path.relpath(real, rroot).replace(os.sep, "/"))
