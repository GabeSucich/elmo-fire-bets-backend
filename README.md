# elmo-fire-bets-backend

## Running

```
uv run uvicorn main:app --reload
```

## Migrations

Alembic reads `DATABASE_URL` from the environment (`.env` locally); the URL in
`alembic.ini` is only a fallback. Set it explicitly to target another database.

```
uv run alembic current        # what this database is on
uv run alembic upgrade head   # apply everything outstanding
```

Against production, prefix the command rather than editing any file:

```
DATABASE_URL="<prod url>" uv run alembic upgrade head
```

Nothing runs migrations automatically — the Procfile only starts uvicorn — so this is a
deliberate step. **Migrate before deploying the code that needs it**, otherwise the new
code can write values the database does not yet know about.

### Adding a revision

```
uv run alembic revision --autogenerate -m "what changed"
```

Autogenerate diffs the models against the database, so it only sees changes not already
applied locally. Two things it does **not** detect, which must be written by hand — see
`alembic/versions/4e069622d8b9_add_wnf_slate_type.py` for the pattern:

- **New enum values.** SQLAlchemy persists enum member *names*, so adding `WNF = "WNF"`
  to `SlateType` needs `ALTER TYPE slatetype ADD VALUE IF NOT EXISTS 'WNF' AFTER 'FNF'`.
  Postgres cannot drop an enum value, so the downgrade rebuilds the type without it.
  (Postgres 12+ allows `ADD VALUE` inside a transaction, as long as the new value is not
  used in that same transaction — no autocommit block needed.)
- **Data changes.**

Test the round trip locally before running it anywhere else:

```
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

## Seeding

`seed.py` **drops every table** before recreating them. Local only — never against
production, which is migrated with Alembic.

```
uv run seed.py
```
