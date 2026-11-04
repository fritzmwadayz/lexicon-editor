# lexed TUI Guide

How the `lexed` terminal interface works, from using it to maintaining it. For installation, see the [README](../README.md).

<!-- Verification note for the maintainer: the storage-layer sections (store.py) were written from the source. Screen layout, widget behaviour and the dirty-state/filter details come from the project's earlier design notes and the README. Check them against app.py before publishing. -->

## 1. What you are editing

The editor shows **one dictionary entry at a time**. Each entry is a unique word form found in the Taita Bible text (the `word`, which never changes). Your job is to turn it into a clean dictionary entry:

- decide the standardized spelling (`corrected` headword),
- add Swahili and English glosses and the part of speech,
- add variations (plurals, dialect forms),
- keep or adjust up to two example verses,
- or mark it as a proper name, or flag it as uncertain.

Entries start as `pending`. Saving moves them to `reviewed`.

## 2. Screen layout

```
Status bar     entry position / total · database file · saved or unsaved
Filters        text filter · status filter (default: pending)
Headword       corrected form (original token shown as "was") · frequency · status
Variations     surface forms, plurals, dialect variants (add / remove rows)
Translations   Swahili gloss · English gloss
Examples       up to 2 parallel verses: TA (Taita) · SW (Swahili) · EN (English)
Notes          free text
```

Language colours: Taita is orange, Swahili green, English blue. The total in the status bar excludes entries marked as names.

## 3. Keybindings

| Key | Action | What happens |
|---|---|---|
| `Ctrl+S` | Save and review | Saves the entry, sets `pending` to `reviewed`, loads the next pending entry |
| `Ctrl+N` | Mark as name | Sets `category = name`, saves, skips to next. Names leave the main queue but are not deleted |
| `Ctrl+F` | Flag | Sets `status = flagged`, saves, loads next |
| `Alt+Left` / `Alt+Right` | Navigate | Previous / next entry in the current filter |
| `Ctrl+E` | Add example | Appends a blank example (maximum 2) |
| `Ctrl+V` | Add variation | Appends a blank variation row |
| `Ctrl+T` | Cycle status | pending, reviewed, approved, flagged |
| `Esc` | Quit | Exits the application |

## 4. Editing workflow

1. Start the editor. The default view is every `pending` entry, with names excluded.
2. Read the examples to see the word in context.
3. Fill in the headword (`corrected`). The original token stays visible as "was".
4. Add glosses, part of speech and dialect where you know them. Add variations if the word has plural or dialect forms.
5. Press `Ctrl+S`. The entry is saved and the next one loads.
6. For proper names, press `Ctrl+N`. When you are unsure, press `Ctrl+F` and move on.

Order of the queue: entries are served alphabetically by `word`. Frequency (how many verses contain the word) is shown on screen but does not affect the order.

### Status meanings

| Status | Meaning |
|---|---|
| `pending` | Not yet reviewed |
| `reviewed` | Edited and saved at least once |
| `approved` | Confirmed as final |
| `flagged` | Needs a second look |

### Categories

`category` is separate from `status`. Values used by the pipeline: `name` (proper noun), `stopword`, `typo`, or empty. Only `name` is currently excluded from the editing queue and the progress count.

## 5. Behaviour worth knowing

- **Filters.** The text filter matches against the original word, the corrected headword, and the Swahili and English glosses (substring match). The status filter is an exact match. Both re-query the database as you type.
- **Unsaved changes.** If an entry has unsaved edits, moving to another entry is blocked with a warning until you save.
- **The database is the source of truth.** Each save writes straight to SQLite.
- **Audit trail.** Every change to the main fields (`corrected`, `swahili`, `english`, `pos`, `dialect`, `notes`, `status`, `category`) is logged to `edit_history` with the old value, new value, timestamp and `changed_by`. Unchanged fields are not logged.
- **Variations and examples are replaced on save:** the old rows are deleted and the current ones re-inserted. These changes are not recorded in `edit_history`.
- **Blank fields** are stored as empty strings, not `NULL`.

## 6. Architecture

```
app.py    LexedApp (Textual): layout, widgets, key bindings, event handling
            |  plain Entry objects
models.py Entry, Variation, UsageExample (dataclasses, no database logic)
            |
store.py  LexiconStore: all SQLite access
            |
          lexicon.db  (created by seed_db.py in taita-dictionary)
style.tcss  Textual CSS: dark theme and language colours
```

### LexiconStore

`LexiconStore(db_path, editor_name="local")` opens the database with foreign keys on and rows accessible by column name. It never creates tables: it expects the schema produced by `seed_db.py` plus the `category` column added by `fixer.py`.

| Method | Purpose |
|---|---|
| `count_entries()` | Total number of entries |
| `get_progress_counts()` | `{"total", "reviewed"}` for the status bar. Excludes `category = name`; counts `reviewed` and `approved` as done |
| `get_entry_ids(filter_text, status, exclude_category="name")` | IDs matching the filters, ordered by `word` |
| `load_entry(entry_id)` | A full `Entry` with its variations and examples, or `None`. `NULL` columns become empty strings |
| `save_entry(entry)` | Logs field changes, updates the entry, replaces variations and examples, in a single transaction |

### Save flow

```
Ctrl+S
  collect the entry from the UI widgets
  store.save_entry(entry)
      load the previous version
      write one edit_history row per changed field
      UPDATE entries (and set updated_at)
      DELETE + INSERT variations
      DELETE + INSERT examples
      COMMIT (one transaction)
  if status was pending, set it to reviewed
  refresh the ID list (the entry leaves the pending queue)
  load the next entry
```

### State

The app tracks the entry being edited, an unsaved-changes flag, the position in the filtered list, and the list of matching IDs. Everything else lives in the database.

## 7. Extending it

- **Change the queue order.** Edit the `ORDER BY` clause in `get_entry_ids()`. Ordering by `frequency DESC, word` serves the most common words first.
- **Add a field.** Add the column to the schema in `taita-dictionary/seed_db.py` (and a migration for existing databases), the dataclass in `models.py`, the read in `load_entry()`, the `field_map` and `UPDATE` in `save_entry()`, and the widget in `app.py`.
- **Swap the backend.** `app.py` only talks to `LexiconStore` through `Entry` objects, so another store with the same methods can replace it.

## 8. Known gaps

Detailed in the [README](../README.md#known-gaps). The main ones for anyone planning to build on this:

- Alphabetical queue only: no sort options.
- No export of the curated data.
- Variation and example edits are not audited.
- Single user and single machine: no locking, syncing or per-user attribution beyond the `changed_by` text field.
- No orthography guide, so there is no written standard for the `corrected` headword.
- No tests.
