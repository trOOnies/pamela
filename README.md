<p align="center">
  <img src="src/pamela/static/pamela.svg" alt="Pamela logo: a sun hat whose crown is a rising sun and whose brim is a leaf" width="128">
</p>

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

To look around before logging real data, run `make seed` first: it fills an empty
database with about two months of mock foods, meals, activities and check-ins
(`python -m pamela.seed --days N` for a different length). It refuses to touch a database
that already has data; delete `local/pamela.sqlite3` to go back to an empty one.

Or without `make`: `pamela --reload` (options: `--host`, `--port`).

To close Pamela, press **Exit** (top right) in the app: it waits for pending saves,
folds the SQLite WAL back into `local/pamela.sqlite3` and stops the server, reloader
included. Ctrl+C in the terminal still works too.

## Features

- **Day**: log food from your catalog (type to search, `↑`/`↓`, `Enter`, type the amount, `Enter`)
  or use *Quick add* to enter the macros directly. Click an amount to edit it. Log activities;
  if you leave kcal empty, it's estimated from the activity's MET value and your body weight.
  The summary shows kcal and macros against your targets, plus burned and net kcal.
  Burned kcal and active time include the day's steps (as easy walking, ~100 steps a minute
  at 3.5 MET), minus the steps that logged on-foot activities already account for (their
  type's steps per minute x minutes), so a logged walk isn't counted twice. History does the same.
  Meals named Breakfast, Lunch, Dinner and Snack show 🌅 ☀️ 🌙 🍪.
  Foods with a serving or package size offer quick portions (*1 serving*, *½ pack*…).
  *Saved meal* mode loads a saved meal as an editable draft that is only logged when you
  press *Log*. The *Check-in* card holds daily steps, sleep, body weight (kg), body fat (%)
  and mood (with feelings); *Notes* holds a few optional words on how the day went.
  Calorie estimates for activities use the latest weight logged on or before that day.
  Activity types are grouped by category, recently used first.
  The top bar shows the weekday and the date (always `YYYY-MM-DD`); *Today* is highlighted
  and disabled on today, and future days can't be opened or logged (the API refuses them too).
  Keys `[` / `]` move to the previous or next day.
- **Foods**: catalog of foods with macros per *N* units (e.g. per 100 g, per 1 slice),
  optional serving and package sizes, and diet tags (vegetarian, vegan, kosher, lactose-free,
  peanut-free, TACC-free). Type or scan a barcode (EAN) and press *Look up*: it's searched in
  the catalog, then on [Open Food Facts](https://world.openfoodfacts.org) (only the barcode is
  sent), and the form is filled in for you to review. Foods are saved with their barcode.
  Foods you log often are listed first. Editing a food updates every log entry of it, on
  any day; deleting a food leaves its entries with their last values.
- **Groceries**: your stock at home, in carts (one per trip to the shops). A cart has a day,
  an optional store, and per food the amount or number of packs, an optional expiry date and
  price. A cart can also hold other items that aren't food (name, amount, unit, price):
  they only count towards its total, never in Foods or the stock. A discount (an amount
  or a %) comes off the subtotal, and an optional delivery fee is added after it, so the
  total matches the receipt. Carts can be edited (day, store, discount, delivery fee, items
  added, changed or removed) or deleted.
  Logging a catalog food in the Day tab takes it out of the stock, soonest expiry first;
  editing or deleting the entry (or clearing the day) puts it back. A cart entered late
  also covers what was logged since its day. Mark an item (or part of it) as *Expired* to
  take it out, with an undo. Expiry dates turn amber three days ahead and red once past;
  *Ran out* lists finished foods with *Buy again*, and tiles sum up what's expiring, what was
  spent and what was thrown out in the last 30 days.
- **Saved meals**: fixed mixes of catalog foods (or *☆ save* a meal from the Day tab).
- **History**: daily kcal, protein, steps and sleep charts against your targets, body weight
  and body fat line charts, averages, and a per-day table with mood and notes (click a day
  to open it). Each chart has its own color.
- **Settings**: your profile (gender, default *Prefer not to say*, and height in cm, used
  for BMI), daily targets (kcal, macros, steps, sleep), each either one value for all
  history or custom periods ("from this date on"), so past days keep the target they had.
  Going back to a single value resets the periods after a confirmation. Targets are positive
  whole numbers; sleep is at most 24 h. Also the exercise types (about 75 built in, with MET
  values and, for those done on foot, steps per minute), editable.
- **Help**: how each tab works, keyboard shortcuts, and your current settings from
  `info/config.toml` (targets and meals), and a note that Pamela gives no health advice.
  Press `?` to open it.

## Folders

| Folder   | What it holds | In git? |
|----------|---------------|---------|
| `local/` | `pamela.sqlite3`, the database (created on first run) | no |
| `info/`  | `config.toml`, settings you edit by hand (created from a template on first run) | no |
| `src/pamela/` | the app: `api.py` (routes), `db.py` (schema + migrations), `config.py`, `static/` (frontend) | yes |

You can point them somewhere else with the `PAMELA_LOCAL_DIR` / `PAMELA_INFO_DIR` env vars.

### `info/config.toml`

Holds the meal names and a fallback body weight, used for calorie estimates until you log
a weigh-in. Daily targets and
activity types used to live here; they are now in the database (Settings tab). An old
`[targets]` table or `[[activity_types]]` list is imported once on the first start after
upgrading and ignored afterwards, so you can delete them.
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
