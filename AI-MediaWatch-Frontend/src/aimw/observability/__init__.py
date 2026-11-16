"""Production observability for AI MediaWatch.

Structured log events for drift detection and SLO monitoring.
Events are emitted via standard Python logging at DEBUG/INFO/WARNING level.
Log aggregators filter on the ``metric`` extra field to build dashboards.
"""
