# pamela

Personal physical activity and macro tracker app.

A small local web app: a FastAPI backend with SQLite storage and a framework-free
HTML/CSS/JS frontend (no build step, no npm). It's made for desktop browsers
(Firefox and Chromium), with the window at full width (1920px) or half width (~960px).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
make install        # pip install -e ".[dev]"
make serve          # http://127.0.0.1:8000 (auto-reloads on code changes)
```

Or without `make`: `pamela --reload` (options: `--host`, `--port`).

## Features

- **Day**: log food from your catalog (type to search, `↑`/`↓`, `Enter`, type the amount, `Enter`)
  or use *Quick add* to enter the macros directly. Click an amount to edit it. Log activities;
  if you leave kcal empty, it's estimated from the activity's MET value and your body weight.
  The summary shows kcal and macros against your targets, plus burned and net kcal.
  Keys `[` / `]` move to the previous or next day.
- **Foods**: catalog of foods with macros per *N* units (e.g. per 100 g, per 1 slice).
  Foods you log often are listed first. Editing or deleting a food doesn't change past log
  entries, because each entry stores a snapshot of its macros.
- **History**: daily kcal and protein charts against your targets, averages, and a
  per-day table (click a day to open it).

## Folders

| Folder   | What it holds | In git? |
|----------|---------------|---------|
| `local/` | `pamela.sqlite3`, the database (created on first run) | no |
| `info/`  | `config.toml`, settings you edit by hand (created from a template on first run) | no |
| `src/pamela/` | the app: `api.py` (routes), `db.py` (schema + migrations), `config.py`, `static/` (frontend) | yes |

You can point them somewhere else with the `PAMELA_LOCAL_DIR` / `PAMELA_INFO_DIR` env vars.

### `info/config.toml`

Holds the profile (body weight for calorie estimates), daily targets (kcal, protein, carbs,
fat, fiber), meal names, and activity types (name, MET, whether it has a distance).
Changes are picked up without restarting: switch back to the browser tab and the page
reloads them. If the file has a mistake, a red banner shows what's wrong. The template is
`src/pamela/defaults/config.toml`.

These settings will gradually move into the app. When one does, it moves out of `info/`
and into the database.

## Development

```bash
make test   # pytest with coverage
make lint   # ruff
```

- **API**: the JSON API is under `/api`; interactive docs are at `/docs`.
- **Schema changes**: append a new SQL script to `MIGRATIONS` in `src/pamela/db.py`.
  Never edit one that has already shipped. `PRAGMA user_version` tracks which migrations
  have run.
- **Frontend**: the frontend is three files in `src/pamela/static/`. Edit them and reload
  the page.
