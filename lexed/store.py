"""Storage layer for the Taita lexicon editor.

This module provides a thin wrapper around a SQLite database populated
by `seed_db.py`. It handles reading entries into dataclass models and
writing changes back while maintaining an audit trail in `edit_history`.

It strictly expects the schema defined in seed_db.py and does NOT
create its own tables.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Entry, UsageExample, Variation


class LexiconStore:
    """Manages SQLite connections and queries for the lexicon database.
    
    Attributes:
        db_path: Path to the SQLite database file.
        conn: The active sqlite3 connection object.
    """

    def __init__(self, db_path: str | Path, editor_name: str = "local"):
        """Initializes the store and connects to the database.
        
        Args:
            db_path: Path to the lexicon SQLite database.
            editor_name: Identifier to record in the edit_history table.
        """
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._editor = editor_name

    def close(self) -> None:
        """Closes the database connection safely."""
        self.conn.close()

    # -- Queries -------------------------------------------------------

    def count_entries(self) -> int:
        """Returns the total number of entries in the database."""
        cur = self.conn.execute("SELECT COUNT(*) FROM entries")
        return cur.fetchone()[0]

    def get_progress_counts(self) -> dict[str, int]:
        """Calculates global progress metrics for the status bar.
        
        Excludes words categorized as 'name' since they are not part
        of the core dictionary workflow.
        
        Returns:
            A dictionary with 'total' active words and 'reviewed' words.
        """
        base_where = "WHERE (category IS NULL OR category != 'name')"
        
        total = self.conn.execute(
            f"SELECT COUNT(*) FROM entries {base_where}"
        ).fetchone()[0]
        
        # Count both 'reviewed' and 'approved' as "done"
        reviewed = self.conn.execute(
            f"SELECT COUNT(*) FROM entries {base_where} AND status IN ('reviewed', 'approved')"
        ).fetchone()[0]
        
        return {"total": total, "reviewed": reviewed}

    def get_entry_ids(
        self, 
        filter_text: str = "", 
        status: str = "", 
        exclude_category: str = "name"
    ) -> list[int]:
        """Fetches a list of entry IDs matching the given filters.
        
        Args:
            filter_text: Substring to match against word, corrected, swahili, or english.
            status: Exact match for the status field (e.g., 'pending').
            exclude_category: Category to exclude from results. Defaults to 'name'
                              to keep proper nouns out of the main editing queue.
                              
        Returns:
            A sorted list of integer entry IDs.
        """
        query = "SELECT id FROM entries WHERE 1=1"
        params: list[str | int] = []

        if exclude_category:
            query += " AND (category IS NULL OR category != ?)"
            params.append(exclude_category)

        if filter_text:
            pattern = f"%{filter_text}%"
            query += " AND (word LIKE ? OR corrected LIKE ? OR swahili LIKE ? OR english LIKE ?)"
            params.extend([pattern, pattern, pattern, pattern])

        if status:
            query += " AND status = ?"
            params.append(status)

        #query += " ORDER BY word"
        query += " ORDER BY frequency DESC, word"
        cur = self.conn.execute(query, params)
        return [row[0] for row in cur.fetchall()]

    def load_entry(self, entry_id: int) -> Entry | None:
        """Loads a complete Entry object with its variations and examples.
        
        Args:
            entry_id: The primary key of the entry to load.
            
        Returns:
            A fully populated Entry object, or None if not found.
        """
        row = self.conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            return None

        variations = [
            Variation(
                variation=r["variation"],
                dialect=r["dialect"] or "",
                notes=r["notes"] or "",
            )
            for r in self.conn.execute(
                "SELECT * FROM variations WHERE entry_id = ? ORDER BY id",
                (entry_id,),
            ).fetchall()
        ]

        examples = [
            UsageExample(
                reference=r["reference"],
                book=r["book"],
                chapter=r["chapter"],
                verse=r["verse"],
                taita=r["taita"],
                swahili=r["swahili"] or "",
                english=r["english"] or "",
            )
            for r in self.conn.execute(
                "SELECT * FROM examples WHERE entry_id = ? ORDER BY id",
                (entry_id,),
            ).fetchall()
        ]

        return Entry(
            id=row["id"],
            word=row["word"],
            corrected=row["corrected"] or "",
            swahili=row["swahili"] or "",
            english=row["english"] or "",
            pos=row["pos"] or "",
            dialect=row["dialect"] or "",
            notes=row["notes"] or "",
            status=row["status"] or "pending",
            category=row["category"] or "",
            frequency=row["frequency"] or 1,
            variations=variations,
            examples=examples,
        )

    # -- Writes --------------------------------------------------------

    def _track_change(
        self, 
        entry_id: int, 
        field: str, 
        old_value: str | None, 
        new_value: str | None
    ) -> None:
        """Records a field-level change in the edit_history table.
        
        Only writes a row if the old and new values actually differ.
        
        Args:
            entry_id: The ID of the entry being modified.
            field: The name of the database column being changed.
            old_value: The previous value.
            new_value: The newly applied value.
        """
        if old_value == new_value:
            return
        self.conn.execute(
            """INSERT INTO edit_history (entry_id, field, old_value, new_value, changed_by)
               VALUES (?, ?, ?, ?, ?)""",
            (entry_id, field, old_value, new_value, self._editor),
        )

    def save_entry(self, entry: Entry) -> None:
        """Persists an Entry and all its child objects to the database.
        
        Replaces existing variations and examples for the entry. Records
        field-level diffs in the edit_history table.
        
        Args:
            entry: The populated Entry dataclass to save.
        """
        prev = self.load_entry(entry.id)

        with self.conn:
            # Track and update main fields
            field_map = {
                "corrected": entry.corrected,
                "swahili": entry.swahili,
                "english": entry.english,
                "pos": entry.pos,
                "dialect": entry.dialect,
                "notes": entry.notes,
                "status": entry.status,
                "category": entry.category,
            }
            for fname, new_val in field_map.items():
                old_val = getattr(prev, fname, None) if prev else None
                self._track_change(entry.id, fname, old_val, new_val)

            self.conn.execute(
                """UPDATE entries
                   SET corrected = ?, swahili = ?, english = ?, pos = ?, dialect = ?,
                       notes = ?, status = ?, category = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    entry.corrected, entry.swahili, entry.english,
                    entry.pos, entry.dialect, entry.notes,
                    entry.status, entry.category, entry.id,
                ),
            )

            # Replace variations
            self.conn.execute(
                "DELETE FROM variations WHERE entry_id = ?", (entry.id,)
            )
            for var in entry.variations:
                self.conn.execute(
                    "INSERT INTO variations (entry_id, variation, dialect, notes) VALUES (?, ?, ?, ?)",
                    (entry.id, var.variation, var.dialect, var.notes),
                )

            # Replace examples
            self.conn.execute(
                "DELETE FROM examples WHERE entry_id = ?", (entry.id,)
            )
            for ex in entry.examples:
                self.conn.execute(
                    """INSERT INTO examples
                       (entry_id, reference, book, chapter, verse, taita, swahili, english)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry.id, ex.reference, ex.book, ex.chapter, ex.verse,
                        ex.taita, ex.swahili, ex.english,
                    ),
                )