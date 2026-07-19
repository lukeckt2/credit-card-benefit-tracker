# Alembic Migrations

Initial migration creates only the core runtime tables:

- `card_master`
- `benefit_definitions`
- `benefit_periods`
- `usage_events`
Rollover run history and appendix import-history tables are intentionally omitted from the initial build.
