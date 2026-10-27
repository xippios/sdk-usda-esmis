"""Per-task tests with recorded fixtures: at least one replay test for every task.

What every task shares (a sync function returning ``Result[T]`` with an agent docstring,
registered by the adapters and listed in the README status table) is core's family check,
which ``tests/test_family.py`` collects. A replay test that checks what was sent compares
``xippios.core.testing.sent_query(route)``, the scrubbed query of the last request, or
``sent_urls(route)``, the URLs the route received with credentials redacted, rather than
keep a request from ``route.calls`` in its frame, where a failure or ``pytest -l`` would
print it.
"""
