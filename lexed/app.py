"""Main Textual TUI application for the Taita lexicon editor.

This module provides a single-entry-at-a-time editing interface for cleaning
and translating Taita words extracted from a parallel Bible corpus.

Workflow:
    - Names and stopwords are excluded from the default view via the `category` field.
    - Ctrl+S saves the entry and auto-advances 'pending' entries to 'reviewed'.
    - Ctrl+N instantly tags an entry as a 'name' and skips to the next.
    - Ctrl+F flags an entry for later review.
    - Alt+Left / Alt+Right navigates entries (bypasses input cursor movement).
"""

from __future__ import annotations

import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static, TextArea

from .models import Entry, UsageExample, Variation
from .store import LexiconStore


class VariationRow(Horizontal):
    """A horizontal row widget representing one editable Variation.
    
    Args:
        var: The Variation dataclass to display/edit.
        index: The current index of this variation in the parent list.
    """

    def __init__(self, var: Variation, index: int) -> None:
        super().__init__(classes="var-row")
        self.var = var
        self.index = index

    def compose(self) -> ComposeResult:
        yield Input(
            value=self.var.variation,
            placeholder="variation",
            classes="var-input",
            id=f"var-{self.index}",
        )
        yield Input(
            value=self.var.dialect,
            placeholder="dialect",
            classes="var-dialect",
            id=f"var-dialect-{self.index}",
        )
        yield Input(
            value=self.var.notes,
            placeholder="notes",
            classes="var-notes",
            id=f"var-notes-{self.index}",
        )
        yield Static("✕", classes="del-btn", id=f"del-var-{self.index}")


class ExampleBlock(Vertical):
    """A vertical block widget representing one editable UsageExample.
    
    Args:
        example: The UsageExample dataclass to display/edit.
        index: The current index of this example in the parent list.
    """

    def __init__(self, example: UsageExample, index: int) -> None:
        super().__init__(classes="example-block")
        self.example = example
        self.index = index

    def compose(self) -> ComposeResult:
        with Horizontal(classes="example-head"):
            yield Static(self.example.reference or "(no ref)", classes="ref")
            
            ref_detail = ""
            if self.example.book:
                ref_detail = f"[{self.example.book} {self.example.chapter}:{self.example.verse}]"
            yield Static(ref_detail, classes="ref-detail")

        lang_map = [
            ("TA", "elang-ta", "taita"),
            ("SW", "elang-sw", "swahili"),
            ("EN", "elang-en", "english"),
        ]
        
        for lang, css_class, attr in lang_map:
            with Horizontal(classes="eline"):
                yield Static(lang, classes=f"elang {css_class}")
                yield Input(
                    value=getattr(self.example, attr),
                    placeholder=f"{lang} text",
                    classes="etext-input",
                    id=f"ex-{self.index}-{attr}",
                )


class LexedApp(App):
    """The main Textual Application class for the lexicon editor."""

    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("ctrl+s", "save_entry", "Save"),
        ("ctrl+f", "flag_entry", "Flag"),
        ("ctrl+n", "mark_name", "Name"),
        ("alt+left", "prev_entry", "Prev"),
        ("alt+right", "next_entry", "Next"),
        ("ctrl+e", "add_example", "Add ex"),
        ("ctrl+v", "add_variation", "Add var"),
        ("ctrl+t", "cycle_status", "Status"),
        ("escape", "quit", "Quit"),
    ]

    def __init__(self, db_path: str) -> None:
        """Initializes the app and connects to the data store.
        
        Args:
            db_path: Path to the SQLite lexicon database.
        """
        super().__init__()
        self.store = LexiconStore(db_path)
        self._filter_text = ""
        self._filter_status = "pending"  # Default queue shows only unreviewed words
        self.entry_ids = self.store.get_entry_ids(status="pending")
        self.position = 0
        self.current: Entry | None = None
        self.dirty = False

    # -- Lifecycle ----------------------------------------------------

    def compose(self) -> ComposeResult:
        """Builds the initial UI layout."""
        yield Static(id="statusbar")

        with Horizontal(id="filter-bar"):
            yield Static("filter:", classes="filter-label")
            yield Input(placeholder="search word/gloss…", id="filter-input")
            yield Static("status:", classes="filter-label")
            yield Input(
                placeholder="pending", 
                id="status-filter", 
                classes="filter-status", 
                value="pending"
            )

        with VerticalScroll(id="main-scroll"):
            with Horizontal(id="headword-row"):
                yield Static("HEADWORD", id="headword-label")
                yield Input(id="headword-input")
                yield Static(id="headword-original")
                yield Static(id="headword-meta")

            with Vertical(classes="panel", id="variations-panel"):
                yield Static("VARIATIONS", classes="panel-head")
                with Vertical(classes="panel-body", id="variations-body"):
                    pass

            with Vertical(classes="panel"):
                yield Static("TRANSLATIONS", classes="panel-head")
                with Horizontal(id="gloss-row", classes="panel-body"):
                    with Vertical(classes="gloss-col"):
                        yield Static("● SWAHILI", classes="gloss-label-sw")
                        yield Input(classes="gloss-input", id="gloss-sw")
                    with Vertical(classes="gloss-col"):
                        yield Static("● ENGLISH", classes="gloss-label-en")
                        yield Input(classes="gloss-input", id="gloss-en")

            with Vertical(classes="panel", id="examples-panel"):
                yield Static("USAGE EXAMPLES", classes="panel-head")
                with Vertical(classes="panel-body", id="examples-body"):
                    pass

            with Vertical(classes="panel"):
                yield Static("NOTES", classes="panel-head")
                with Vertical(classes="panel-body"):
                    yield TextArea(id="notes-input")

        yield Footer()

    async def on_mount(self) -> None:
        """Runs after the UI is mounted. Loads the first entry."""
        if self.entry_ids:
            await self.load_entry(self.entry_ids[self.position])
        else:
            self.notify("No pending entries in database.", severity="warning")
            
        self.query_one("#filter-input", Input).focus()

    # -- Filtering -----------------------------------------------------

    def _refresh_ids(self) -> None:
        """Re-queries the database based on current filter states."""
        self.entry_ids = self.store.get_entry_ids(
            filter_text=self._filter_text,
            status=self._filter_status,
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Responds to typing in the filter or status input bars."""
        is_filter = event.input.id == "filter-input"
        is_status = event.input.id == "status-filter"

        if is_filter or is_status:
            if is_filter:
                self._filter_text = event.value
            if is_status:
                self._filter_status = event.value

            self._refresh_ids()
            
            if self.entry_ids:
                self.position = 0
                self.call_after_refresh(self.load_entry, self.entry_ids[0])
            else:
                self.current = None
                self.query_one("#statusbar", Static).update("no matches")
            return

        # Any other input field triggers the dirty state
        self.dirty = True
        self.refresh_statusbar()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Responds to typing in the notes Text Area."""
        self.dirty = True
        self.refresh_statusbar()

    # -- Entry Loading / UI Sync ----------------------------------------

    async def load_entry(self, entry_id: int) -> None:
        """Fetches an entry from the store and populates the UI.
        
        Args:
            entry_id: The database ID of the entry to load.
        """
        entry = self.store.load_entry(entry_id)
        if entry is None:
            return
            
        self.current = entry
        self.dirty = False
        await self.load_entry_into_ui(entry)
        self.refresh_statusbar()

    async def load_entry_into_ui(self, entry: Entry) -> None:
        """Takes an Entry object and pushes its data into the UI widgets."""
        # Headword section
        self.query_one("#headword-input", Input).value = entry.headword
        orig = self.query_one("#headword-original", Static)
        
        if entry.corrected and entry.corrected != entry.word:
            orig.update(f"(was: {entry.word})")
        else:
            orig.update("")

        # Meta line: Category, POS, Frequency, Status
        meta_parts = []
        if entry.category:
            meta_parts.append(f"[{entry.category.upper()}]")
        if entry.pos:
            meta_parts.append(entry.pos)
        meta_parts.append(f"×{entry.frequency}")
        meta_parts.append(entry.status_display)
        
        self.query_one("#headword-meta", Static).update("  ".join(meta_parts))

        # Translations
        self.query_one("#gloss-sw", Input).value = entry.swahili
        self.query_one("#gloss-en", Input).value = entry.english
        self.query_one("#notes-input", TextArea).text = entry.notes

        # Variations
        var_body = self.query_one("#variations-body", Vertical)
        await var_body.remove_children()
        for i, var in enumerate(entry.variations):
            await var_body.mount(VariationRow(var, i))
        await var_body.mount(Static("+ add variation", id="add-var-btn"))

        # Examples
        ex_body = self.query_one("#examples-body", Vertical)
        await ex_body.remove_children()
        for i, ex in enumerate(entry.examples):
            await ex_body.mount(ExampleBlock(ex, i))
        await ex_body.mount(Static("+ add example", id="add-example-btn"))

    def collect_entry_from_ui(self) -> Entry:
        """Reads the current state of all UI widgets back into an Entry object.
        
        Returns:
            The modified Entry object reflecting current UI state.
        """
        assert self.current is not None
        entry = self.current

        entry.headword = self.query_one("#headword-input", Input).value
        entry.swahili = self.query_one("#gloss-sw", Input).value
        entry.english = self.query_one("#gloss-en", Input).value
        entry.notes = self.query_one("#notes-input", TextArea).text

        # Gather variations
        variations: list[Variation] = []
        for row in self.query("VariationRow"):
            var_input = row.query_one(f"#var-{row.index}", Input)
            dialect_input = row.query_one(f"#var-dialect-{row.index}", Input)
            notes_input = row.query_one(f"#var-notes-{row.index}", Input)
            
            variations.append(Variation(
                variation=var_input.value,
                dialect=dialect_input.value,
                notes=notes_input.value,
            ))
        entry.variations = variations

        # Gather examples
        examples: list[UsageExample] = []
        for block in self.query("ExampleBlock"):
            i = block.index
            taita_input = block.query_one(f"#ex-{i}-taita", Input)
            swahili_input = block.query_one(f"#ex-{i}-swahili", Input)
            english_input = block.query_one(f"#ex-{i}-english", Input)
            
            examples.append(UsageExample(
                reference=block.example.reference,
                book=block.example.book,
                chapter=block.example.chapter,
                verse=block.example.verse,
                taita=taita_input.value,
                swahili=swahili_input.value,
                english=english_input.value,
            ))
        entry.examples = examples

        return entry

    def refresh_statusbar(self) -> None:
        """Updates the text in the top status bar."""
        total = len(self.entry_ids)
        pos = self.position + 1 if total else 0
        
        dirty_text = "[dirty]● unsaved" if self.dirty else "[clean]✓ saved"
        
        filter_hint = ""
        if self._filter_text:
            filter_hint += f" · filter: {self._filter_text}"
        if self._filter_status:
            filter_hint += f" · status: {self._filter_status}"

        db_name = Path(self.store.db_path).name
        message = f"entry {pos:04d}/{total}  ·  {db_name}{filter_hint}  ·  {dirty_text}"
        self.query_one("#statusbar", Static).update(message)

    # -- List State Management -----------------------------------------

    async def _advance_list(self, entry: Entry) -> None:
        """Handles UI state after an entry is saved or its status changes.
        
        If the entry still belongs in the filtered view, it updates the UI in place.
        If the entry dropped out of the filtered view (e.g. pending -> reviewed),
        it loads the next valid entry in the list.
        
        Args:
            entry: The entry that was just modified and saved.
        """
        self._refresh_ids()
        
        if entry.id in self.entry_ids:
            # Entry remains in view, just refresh UI
            self.position = self.entry_ids.index(entry.id)
            await self.load_entry_into_ui(entry)
        else:
            # Entry dropped out of view (e.g. changed from pending to reviewed)
            if self.entry_ids:
                self.position = min(self.position, len(self.entry_ids) - 1)
                self.call_after_refresh(self.load_entry, self.entry_ids[self.position])
            else:
                self.current = None
                self.query_one("#statusbar", Static).update(
                    "no entries matching current filter"
                )

    # -- Actions / Keybindings -----------------------------------------

    def action_save_entry(self) -> None:
        """Saves the current entry. Auto-advances 'pending' to 'reviewed'."""
        if self.current is None:
            return
            
        entry = self.collect_entry_from_ui()

        # Auto-advance workflow
        if entry.status == "pending":
            entry.status = "reviewed"

        self.store.save_entry(entry)
        self.current = entry
        self.dirty = False

        self.call_after_refresh(self._advance_list, entry)
        self.notify("Saved.")

    async def action_flag_entry(self) -> None:
        """Flags the current entry for later review."""
        if self.current is None:
            return
        if self.current.status == "flagged":
            self.notify("Already flagged.", severity="information")
            return

        entry = self.collect_entry_from_ui()
        entry.status = "flagged"
        
        self.store.save_entry(entry)
        self.current = entry
        self.dirty = False

        await self._advance_list(entry)
        self.notify("Flagged.")

    async def action_mark_name(self) -> None:
        """Categorizes the entry as a proper noun/name and skips to next."""
        if self.current is None:
            return

        entry = self.collect_entry_from_ui()
        entry.category = "name"
        
        self.store.save_entry(entry)
        self.current = entry
        self.dirty = False

        await self._advance_list(entry)
        self.notify("Tagged as name.", severity="information")

    async def action_prev_entry(self) -> None:
        """Navigates to the previous entry in the current filtered list."""
        await self._navigate(-1)

    async def action_next_entry(self) -> None:
        """Navigates to the next entry in the current filtered list."""
        await self._navigate(1)

    async def _navigate(self, delta: int) -> None:
        """Handles directional navigation logic.
        
        Args:
            delta: -1 for previous, +1 for next.
        """
        if not self.entry_ids:
            return
            
        if self.dirty:
            self.notify(
                "Unsaved changes — press Ctrl+S to save first", 
                severity="warning"
            )
            return

        new_pos = max(0, min(len(self.entry_ids) - 1, self.position + delta))
        if new_pos != self.position:
            self.position = new_pos
            await self.load_entry(self.entry_ids[self.position])

    async def action_add_example(self) -> None:
        """Appends a blank usage example to the current entry."""
        if self.current is None:
            return
        self.current.examples.append(UsageExample())
        await self.load_entry_into_ui(self.current)
        self.dirty = True
        self.refresh_statusbar()

    async def action_add_variation(self) -> None:
        """Appends a blank variation to the current entry."""
        if self.current is None:
            return
        self.current.variations.append(Variation())
        await self.load_entry_into_ui(self.current)
        self.dirty = True
        self.refresh_statusbar()

    async def action_cycle_status(self) -> None:
        """Manually cycles the status: pending -> reviewed -> approved -> flagged."""
        if self.current is None:
            return

        entry = self.collect_entry_from_ui()
        order = ["pending", "reviewed", "approved", "flagged"]
        
        current = entry.status if entry.status in order else "pending"
        idx = order.index(current)
        entry.status = order[(idx + 1) % len(order)]

        self.store.save_entry(entry)
        self.current = entry
        self.dirty = False

        await self._advance_list(entry)
        self.notify(f"Status: {entry.status}")

    # -- Click Handling ------------------------------------------------

    async def on_click(self, event) -> None:
        """Dispatches clicks on dynamic UI elements like add/delete buttons."""
        widget_id = getattr(event.widget, "id", None)
        if not widget_id:
            return

        if widget_id == "add-var-btn":
            await self.action_add_variation()
        elif widget_id == "add-example-btn":
            await self.action_add_example()
        elif widget_id.startswith("del-var-"):
            index = int(widget_id.removeprefix("del-var-"))
            await self._delete_variation(index)

    async def _delete_variation(self, index: int) -> None:
        """Removes a variation row by index after syncing UI state.
        
        Args:
            index: The 0-based index of the variation to delete.
        """
        if self.current is None or index >= len(self.current.variations):
            return
            
        # Sync current UI state before deleting to prevent clobbering other rows
        self.current = self.collect_entry_from_ui()
        del self.current.variations[index]
        
        await self.load_entry_into_ui(self.current)
        self.dirty = True
        self.refresh_statusbar()


def main() -> None:
    """Entry point for running the lexed editor directly."""
    db_path = sys.argv[1] if len(sys.argv) > 1 else "lexicon.db"
    app = LexedApp(db_path)
    app.run()


if __name__ == "__main__":
    main()