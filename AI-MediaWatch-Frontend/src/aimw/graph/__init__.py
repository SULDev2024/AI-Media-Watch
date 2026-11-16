"""Intelligence graph subsystem -- Phase 11.

The graph is an *application-layer* subsystem: it reads persisted packages,
correlates entities across them, and writes back a ``source="network"`` evidence
piece to packages that join a coordinated campaign (>=3 videos sharing an
entity with certainty >= 0.5).

Public surface
--------------
``models.NetworkConnection``      -> typed network-connection payload
``models.Campaign``               -> detected (videos, shared_entities, strength)
``builder.build_from_db(repo)``   -> bipartite ``nx.Graph`` over (video, entity)
``campaigns.find(G, min_videos)`` -> sorted list of ``Campaign``
``feedback.promote(repo, ...)``   -> writes ``network`` pieces back; re-scores; re-renders
``export.to_cytoscape(G)``        -> ``{nodes, edges}`` for Phase 14 frontend

Boundary contract (.importlinter ``graph-is-application-layer``): nobody in
``scoring``/``confidence``/``reasoning``/``collection``/``extraction`` imports
this package. The graph reads ``db``/``scoring``/``confidence``/``report`` but
never the other way around.
"""
