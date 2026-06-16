"""Storage adapter — Postgres/JSONB via SQLAlchemy 2.0 (owned by Foundation).

Implements the storage port repository protocols. All tables are campaign-scoped
(FR-CRIT-4). DBOS workflow state co-resides in the same Postgres (FR-DUR-3).
"""
