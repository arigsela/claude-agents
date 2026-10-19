"""Offline evaluation: the local stand-in for the docs repository's MCP server
(``localrepo``), record and replay of model responses (``replay``), the eval spend
guard (``spend``), scoring against labelled lines (``score``), the harness that
runs the graph on labelled instances (``harness``; CLI: ``python -m docs_checker.evals``)
and the curation of the eval set and its labels (``curate``; CLI:
``python -m docs_checker.evals.curate``)."""
