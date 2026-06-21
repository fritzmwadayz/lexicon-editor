# lexed — Taita Lexicon Editor

A terminal-based editor for curating a Taita/Swahili/English lexicon from a parallel Bible corpus.

## Installation

```bash
pip install -e .
```

Or just install the dependency:

```bash
pip install textual
```

## Usage

```bash
# Run against a lexicon database
python -m lexed.app /path/to/lexicon.db

# Or from the project root
python -m lexed.app ../data/lexicon.db
```

If the database doesn't exist, empty tables are created automatically.

## Keybindings

| Key | Action |
|-----|--------|
| `Ctrl+S` | Save entry, mark as reviewed, load next |
| `Ctrl+N` | Mark as proper name, skip to next |
| `Ctrl+F` | Flag entry for later review |
| `Alt+←` / `Alt+→` | Previous / next entry |
| `Ctrl+E` | Add usage example |
| `Ctrl+V` | Add variation |
| `Ctrl+T` | Cycle status manually |
| `Esc` | Quit |

## Data Model

The editor expects a SQLite database with these tables (created by `seed_db.py`):

- `entries` — headwords, glosses, POS, status, frequency
- `variations` — alternate forms, plurals, dialectal variants
- `examples` — parallel Bible verses (Taita + Swahili + English)
- `edit_history` — audit trail of all changes

## Files

```
lexed/
  __init__.py
  app.py        — Textual application, UI layout, event handling
  models.py     — Dataclasses: Entry, Variation, UsageExample
  store.py      — SQLite read/write layer
  style.tcss    — Dark theme styling
```

The UI is completely decoupled from storage — `app.py` only talks to `LexiconStore`, which returns/accepts plain `Entry` objects. You can swap the backend without touching the UI.
