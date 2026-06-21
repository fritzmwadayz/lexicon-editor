"""Data models for the Taita lexicon editor.

These plain dataclasses represent a lexicon entry independent of the
storage mechanism. The application UI interacts exclusively with these
objects, while the LexiconStore handles translating them to/from SQLite.

Aligned with the schema created by seed_db.py:
  - entries (word, corrected, swahili, english, pos, dialect, status, category, frequency, ...)
  - variations (entry_id, variation, dialect, notes)
  - examples (entry_id, reference, book, chapter, verse, taita, swahili, english)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Variation:
    """An alternative spelling or dialectal form of a headword.
    
    Attributes:
        variation: The alternate surface form of the word.
        dialect: The specific dialect this variation belongs to (e.g., 'Mbololo').
        notes: Any supplementary information about this variation.
    """
    variation: str = ""
    dialect: str = ""
    notes: str = ""


@dataclass
class UsageExample:
    """One parallel-text example drawn from the Bible corpus.
    
    Attributes:
        reference: Formatted string reference (e.g., 'Mwanzo 1:1').
        book: The name of the book (e.g., 'Mwanzo').
        chapter: The chapter number.
        verse: The verse number.
        taita: The text in Taita.
        swahili: The parallel text in Swahili.
        english: The parallel text in English.
    """
    reference: str = ""
    book: str = ""
    chapter: int = 0
    verse: int = 0
    taita: str = ""
    swahili: str = ""
    english: str = ""


@dataclass
class Entry:
    """A single lexicon entry representing a unique word.
    
    Attributes:
        id: The primary key from the database.
        word: The original tokenized form extracted from the corpus.
        corrected: The standardized headword spelling (edited by user).
        swahili: The Swahili gloss/translation.
        english: The English gloss/translation.
        pos: Part of speech (e.g., 'noun', 'verb').
        dialect: Dialect marker applied to the main entry.
        notes: Free-text notes for linguists/translators.
        status: Review workflow status ('pending', 'reviewed', 'approved', 'flagged').
        category: Lexical category to exclude non-dictionary words ('name', 'stopword', 'typo').
        frequency: The number of times this token appears in the corpus.
        variations: A list of alternate forms or spellings.
        examples: A list of parallel-text usage examples.
    """
    id: int
    word: str = ""
    corrected: str = ""
    swahili: str = ""
    english: str = ""
    pos: str = ""
    dialect: str = ""
    notes: str = ""
    status: str = "pending"
    category: str = ""
    frequency: int = 1
    variations: list[Variation] = field(default_factory=list)
    examples: list[UsageExample] = field(default_factory=list)

    @property
    def headword(self) -> str:
        """str: The display form of the word (corrected if set, else original)."""
        return self.corrected or self.word

    @headword.setter
    def headword(self, value: str) -> None:
        """Sets the display headword by updating the corrected field."""
        self.corrected = value

    @property
    def is_complete(self) -> bool:
        """bool: Rough heuristic indicating if the entry has both glosses."""
        return bool(self.swahili and self.english)

    @property
    def status_display(self) -> str:
        """str: A formatted string combining an icon and the status text."""
        icons = {
            "pending": "○",
            "reviewed": "◐",
            "approved": "●",
            "flagged": "⚑"
        }
        icon = icons.get(self.status, "○")
        return f"{icon} {self.status}"