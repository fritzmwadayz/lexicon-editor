# TaitaLumi Architecture

> **TaitaLumi** is a digital lexicon project for the Taita language (Dawida, Sagala, Kasighau dialects), built from a Taita/Swahili/English parallel Bible corpus. This document describes the system architecture, data pipeline, and component design.

---

## 1. Overview

TaitaLumi is structured as a **data pipeline → storage → curation interface** system:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  RAW DATA       │────▶│  DATA PIPELINE  │────▶│  LEXICON DB     │
│  (Bible extracts│     │  (parse/token/  │     │  (SQLite)       │
│   & mappings)   │     │   seed)         │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                           │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  EDITOR TUI     │
                                                  │  (curation)     │
                                                  └─────────────────┘
                                                           │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  CLEAN DATA     │
                                                  │  (exportable)   │
                                                  └─────────────────┘
```

The project is currently in **Phase 2: Data Curation** (the editor). Phases 1 (Data Collection) and 3+ (Translation App, LLM) are planned or partially implemented.

---

## 2. Data Pipeline (Phase 1)

### 2.1 Raw Data Sources

| Source | Format | Content |
|--------|--------|---------|
| `raw_data/dat_extracts/` | Plain text files | Bible verses, headers, book names in Taita, Swahili, KJV, and WEB (English) |
| `taita_swahili_mappings.csv` | CSV | Pre-existing word-level mappings between Taita and Swahili |
| `merged_bible.csv` | CSV | Aligned parallel corpus: Taita, Swahili, English verses |

### 2.2 Pipeline Flow

```
raw_data/dat_extracts/
    ├── verses_taita_txt
    ├── verses_kiswahili_txt
    ├── verses_kjv_txt
    ├── verses_web_txt
    └── ...
           │
           ▼
    ┌──────────────┐
    │  parser.py   │  ──▶  bible.db (intermediate SQLite)
    └──────────────┘
           │
           ▼
    ┌──────────────┐
    │  mapper.py   │  ──▶  Aligns verses into merged_bible.csv
    └──────────────┘
           │
           ▼
    ┌──────────────┐
    │ tokenizer.py │  ──▶  Extracts unique tokens from Taita text
    └──────────────┘
           │
           ▼
    ┌──────────────┐
    │  seed_db.py  │  ──▶  data/lexicon.db (working database)
    └──────────────┘
```

### 2.3 Tokenization Strategy

The tokenizer (`tokenizer.py`) normalizes Taita text before extraction:

1. **Remove bracketed annotations**: `{footnote markers}`, `{...}`
2. **Strip digits**: Chapter/verse numbers embedded in text
3. **Keep apostrophes**: Taita uses `'` for glottal stops / contractions (e.g., `w'ana`)
4. **Lowercase and split** on non-alphabetic characters
5. **Filter**: Only tokens with length > 1 are kept (removes single-letter artifacts)

This produces a set of **unique surface forms** that become the initial `entries` table.

### 2.4 Seeding Logic

`seed_db.py` creates the working database with four tables:

- **`entries`**: One row per unique token. Fields: `word` (original), `corrected` (to be filled), `swahili`, `english`, `pos`, `dialect`, `status`, `frequency`, `notes`.
- **`variations`**: Surface forms, plurals, dialectal variants linked to an entry.
- **`examples`**: Up to 2 parallel-text examples per entry (Taita verse + Swahili + English translations from the same CSV row).
- **`edit_history`**: Audit trail of every field change (who, what, when).

**Frequency counting**: Each time a token appears in a verse, its `frequency` is incremented. This helps prioritize high-frequency words for curation.

**Example capping**: Only 2 examples per entry are stored to keep the database manageable. These are drawn from the first verses where the word appears.

---

## 3. Database Schema

```sql
entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word        TEXT NOT NULL UNIQUE,     -- original token from corpus
    corrected   TEXT,                     -- standardized orthography
    swahili     TEXT,                     -- Swahili gloss
    english     TEXT,                     -- English gloss
    pos         TEXT,                     -- part of speech
    dialect     TEXT,                     -- dawida | sagala | kasighau
    notes       TEXT,
    status      TEXT DEFAULT 'pending',   -- pending | reviewed | approved | flagged
    category    TEXT,                     -- name | stopword | typo | NULL
    frequency   INTEGER DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

variations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    variation   TEXT NOT NULL,            -- surface form / plural / dialect variant
    dialect     TEXT,
    notes       TEXT
);

examples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    reference   TEXT NOT NULL,            -- "Mwanzo 1:1"
    book        TEXT NOT NULL,
    chapter     INTEGER NOT NULL,
    verse       INTEGER NOT NULL,
    taita       TEXT NOT NULL,            -- Taita verse text
    swahili     TEXT,                     -- Swahili verse text
    english     TEXT                      -- English verse text
);

edit_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    field       TEXT NOT NULL,            -- which column changed
    old_value   TEXT,
    new_value   TEXT,
    changed_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    changed_by  TEXT DEFAULT 'local'      -- for future multi-user support
);
```

### Design Decisions

- **`word` is UNIQUE**: Each surface form from the corpus gets one entry. Variations (plurals, dialectal forms) live in `variations`, not as separate entries.
- **`corrected` vs `word`**: `word` is immutable (the corpus token). `corrected` is the editable, standardized headword. This preserves the audit trail.
- **`category`**: Used to exclude non-dictionary words (proper nouns like "Mungu", "Yesu", stopwords) from the main editing queue without deleting them.
- **`status` workflow**: `pending` → `reviewed` → `approved`. `flagged` is for uncertain entries. `name` is handled via `category`.

---

## 4. Editor Architecture (Phase 2)

The editor is a **Textual TUI** (Terminal User Interface) living in the `editor/` directory. It is designed to be a standalone, pip-installable package.

### 4.1 Component Diagram

```
┌─────────────────────────────────────────┐
│              LexedApp                   │
│  (Textual App, CSS_PATH = style.tcss)   │
│                                         │
│  ┌─────────────┐  ┌─────────────────┐   │
│  │  UI Layer   │  │  Action Layer   │   │
│  │  (compose)  │  │  (keybindings)  │   │
│  └──────┬──────┘  └────────┬────────┘   │
│         │                  │             │
│  ┌──────▼──────┐  ┌────────▼────────┐   │
│  │  Widgets    │  │  collect_entry  │   │
│  │  (Input,    │◀─│  _from_ui()     │   │
│  │   TextArea, │  │                 │   │
│  │   Static)   │  │  load_entry_    │   │
│  └──────┬──────┘  │  into_ui()      │   │
│         │         └─────────────────┘   │
│  ┌──────▼──────┐                      │
│  │  Models     │                      │
│  │  (Entry,    │                      │
│  │  Variation, │                      │
│  │  UsageEx)   │                      │
│  └──────┬──────┘                      │
│         │                             │
│  ┌──────▼──────┐                      │
│  │  LexiconStore│                     │
│  │  (SQLite I/O) │                     │
│  └──────────────┘                     │
└─────────────────────────────────────────┘
```

### 4.2 Key Modules

| Module | Responsibility |
|--------|--------------|
| `app.py` | Textual App, screen layout, widget composition, event handling, keybindings |
| `models.py` | Plain dataclasses: `Entry`, `Variation`, `UsageExample`. No DB logic. |
| `store.py` | SQLite read/write. `load_entry()`, `save_entry()`, `get_entry_ids()`. Also writes `edit_history`. |
| `style.tcss` | Textual CSS styling. Dark theme with color-coded languages (Taita=orange, Swahili=green, English=blue). |

### 4.3 UI Layout

```
┌─ Status Bar ─────────────────────────────┐
│ entry 0001/40586  ·  lexicon.db  ·  [clean]│
├─ filter: [________] status: [pending] ───┤
├─ HEADWORD [mwana]      (was: mwana) ×156 ○ pending├─
├─ VARIATIONS ─────────────────────────────┤
│  [mwana] [dawida] [sg]          ✕        │
│  [wana]  [dawila] [pl]          ✕        │
│  + add variation                         │
├─ TRANSLATIONS ───────────────────────────┤
│  ● SWAHILI [mtoto]    ● ENGLISH [child]  │
├─ USAGE EXAMPLES ─────────────────────────┤
│  ┌─ Mwanzo 1:1 [Mwanzo 1:1] ────────────┐│
│  │ TA [Mwana wa Nyasaye...]             ││
│  │ SW [Mwana wa Mungu...]               ││
│  │ EN [The child of God...]             ││
│  └──────────────────────────────────────┘│
│  + add example                             │
├─ NOTES ──────────────────────────────────┤
│  [free text area]                          │
└────────────────────────────────────────────┘
```

### 4.4 Keybindings & Workflow

| Key | Action | Behavior |
|-----|--------|----------|
| `Ctrl+S` | Save & Review | Saves entry, auto-advances `pending` → `reviewed`, loads next pending entry |
| `Ctrl+N` | Mark as Name | Sets `category = "name"`, saves, skips to next (excludes from main queue) |
| `Ctrl+F` | Flag | Sets `status = "flagged"`, saves, loads next pending entry |
| `Alt+←` / `Alt+→` | Navigate | Prev/Next entry in current filter (warns if unsaved) |
| `Ctrl+E` | Add Example | Appends blank example (up to 2 max) |
| `Ctrl+V` | Add Variation | Appends blank variation row |
| `Ctrl+T` | Cycle Status | Manual cycle: pending → reviewed → approved → flagged |
| `Esc` | Quit | Exit application |

### 4.5 State Management

The editor maintains two levels of state:

1. **App state**: `self.current` (the `Entry` being edited), `self.dirty` (unsaved changes flag), `self.position` (index in filtered list), `self.entry_ids` (filtered ID list).
2. **Database state**: The SQLite database is the single source of truth. `edit_history` provides a complete audit trail.

**Navigation safety**: If `self.dirty` is true, navigation is blocked with a warning until the user saves. This prevents accidental data loss.

**Filter persistence**: The `status` and `filter_text` inputs are reactive. Typing in them immediately re-queries the database and updates the entry list. The default filter is `status = "pending"`.

---

## 5. Data Flow: Editing an Entry

```
User opens editor
    │
    ▼
LexiconStore.get_entry_ids(status="pending", exclude_category="name")
    │
    ▼
Load first Entry into UI widgets
    │
    ▼
User edits fields / adds variations / adds examples
    │
    ▼
Input.Changed / TextArea.Changed → self.dirty = True
    │
    ▼
User presses Ctrl+S
    │
    ▼
collect_entry_from_ui() → Entry object
    │
    ▼
LexiconStore.save_entry(entry)
    ├── UPDATE entries (track field changes in edit_history)
    ├── DELETE + INSERT variations
    ├── DELETE + INSERT examples
    └── COMMIT
    │
    ▼
Auto-advance status: pending → reviewed
    │
    ▼
_refresh_ids() → entry drops from pending list
    │
    ▼
Load next pending entry
```

---

## 6. Future Architecture (Phases 3+)

### 6.1 Translation Application

A lightweight web or mobile app for translating between Taita, Swahili, and English using the curated lexicon:

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│  User Input │────▶│  Lexicon Lookup │────▶│  Output     │
│  (Taita)    │     │  + POS tagging  │     │  (Swahili/  │
│             │     │  + Morphology   │     │   English)  │
└─────────────┘     └─────────────────┘     └─────────────┘
```

The `variations` table will be critical here — it maps surface forms to canonical entries, handling plurals and dialectal differences.

### 6.2 Tiny LLM

A small language model (sub-1B parameters) trained on the parallel corpus + curated lexicon:

- **Training data**: `merged_bible.csv` (parallel sentences) + `entries` (dictionary)
- **Vocabulary**: Derived from `entries.word` + `variations.variation`
- **Tokenization**: Custom tokenizer aware of Taita morphology (prefixes, suffixes, noun classes)
- **Architecture**: Likely a small transformer or RNN (LSTM/GRU) given corpus size constraints

The curated lexicon acts as a **structured prior** — the model can look up word embeddings from the dictionary rather than learning everything from raw text.

---

## 7. Project Structure

```
TaitaLumi/
├── data/
│   ├── lexicon.db              # Working database (created by seed_db.py)
│   ├── merged_bible.csv        # Aligned parallel corpus
│   └── word_usage_examples.csv # Generated example mappings
│
├── editor/                     # Standalone TUI package (pip-installable)
│   ├── lexed/
│   │   ├── __init__.py
│   │   ├── app.py              # Textual TUI application
│   │   ├── models.py           # Dataclasses
│   │   ├── store.py            # SQLite I/O layer
│   │   └── style.tcss          # Textual CSS styling
│   ├── README.md
│   └── requirements.txt
│
├── raw_data/
│   └── dat_extracts/           # Original Bible text extracts
│       ├── verses_taita_txt
│       ├── verses_kiswahili_txt
│       ├── verses_kjv_txt
│       ├── verses_web_txt
│       └── ...
│
├── scripts/                    # Data pipeline scripts
│   ├── seed_db.py              # CSV → SQLite lexicon.db
│   ├── mapper.py               # Alignment / mapping logic
│   ├── parser.py               # Raw text → structured data
│   ├── tokenizer.py            # Taita text tokenization
│   └── samples.py              # Sample generation / testing
│
├── taita_swahili_mappings.csv  # Pre-existing word mappings
├── test.py                     # Miscellaneous tests
├── ARCHITECTURE.md             # This document
└── README.md                   # Project overview
```

---

## 8. Design Principles

1. **Data-first**: The database schema is the contract. The UI and pipeline adapt to it, not the other way around.
2. **Audit everything**: Every field change is logged in `edit_history`. This supports collaboration and rollback.
3. **Exclude, don't delete**: Names and stopwords are categorized, not deleted. This preserves frequency data and allows re-inclusion later.
4. **Minimal viable curation**: The editor shows only what a human needs to judge — headword, glosses, examples, variations. No linguistic complexity unless the user adds it.
5. **Standalone editor**: The `editor/` package has no dependencies on the pipeline scripts. It only needs `lexicon.db`.

---

## 9. Contributing

See `README.md` for setup instructions. The editor can be run against any `lexicon.db` that matches the schema above — useful for testing or for other language projects with similar data.
