"""Story lane: builds the aggregate ``story.json`` the essay renders.

``io`` owns the file format (atomic per-section merges, the Estimate object),
``frame`` loads the phase-2 analysis frame, ``boot`` is the stratified thread
bootstrap every estimate shares, ``core`` computes the S1 keys (funnel,
groups, cards, unplaced, domains, roles), ``method`` the runs/quality ledger,
and ``check`` the no-free-text gate. The CLI wires them under
``atlas story data`` / ``atlas story check``.
"""
