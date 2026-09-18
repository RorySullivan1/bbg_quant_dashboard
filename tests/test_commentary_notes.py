"""The QIS Bulletin's commentary notes (#304, epic #303).

`data/commentary.json` replaces the single author-written HTML blob with a list
of dated notes. What these tests pin is the contract the renderer (#307)
will read against: the three fields, the newest-first order, `text` carried
verbatim, and — the half that matters at startup — that no shape of broken file
can raise. The loader runs while the app is being built, so a malformed note
must cost that note, not the dashboard.
"""

from __future__ import annotations

import json
import warnings
from datetime import date

import pytest
from src.commentary import CommentaryNote, load_commentary_notes


def _write(tmp_path, payload) -> str:
    path = tmp_path / "commentary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _note(title: str, iso: str, text: str = "Body.") -> dict:
    return {"title": title, "date": iso, "text": text}


# --- the contract ----------------------------------------------------------


def test_a_note_carries_its_title_its_own_date_and_its_text(tmp_path):
    notes = load_commentary_notes(
        _write(tmp_path, [_note("Carry leads", "2026-09-15", "Front end repriced.")])
    )

    assert notes == [
        CommentaryNote(
            title="Carry leads", date=date(2026, 9, 15), text="Front end repriced."
        )
    ]
    # A real date, not the ISO string: the renderer formats it, and the board
    # no longer stamps every note with today.
    assert isinstance(notes[0].date, date)


def test_text_comes_back_verbatim(tmp_path):
    """Escaping and the paragraph split belong to the renderer (#307).

    If the loader ever starts "helping" here — collapsing the blank lines, or
    escaping the angle brackets — the renderer would escape already-escaped
    text and the note would render as literal `&lt;`.
    """
    body = "Spreads < 50bp.\n\nCarry & roll held up."
    (note,) = load_commentary_notes(_write(tmp_path, [_note("T", "2026-01-01", body)]))

    assert note.text == body


def test_notes_come_back_newest_first(tmp_path):
    notes = load_commentary_notes(
        _write(
            tmp_path,
            [
                _note("middle", "2026-05-01"),
                _note("oldest", "2025-12-31"),
                _note("newest", "2026-09-15"),
            ],
        )
    )

    assert [n.title for n in notes] == ["newest", "middle", "oldest"]


def test_two_notes_on_one_day_keep_the_order_they_were_written(tmp_path):
    # A stable sort, so same-day notes read in file order rather than in
    # whatever order the sort happened to leave them.
    notes = load_commentary_notes(
        _write(
            tmp_path,
            [_note("first", "2026-09-15"), _note("second", "2026-09-15")],
        )
    )

    assert [n.title for n in notes] == ["first", "second"]


def test_an_unknown_key_is_ignored(tmp_path):
    # So a field added to the file later cannot break a build that predates it.
    payload = [{**_note("T", "2026-01-01"), "author": "desk", "tags": ["rates"]}]

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        (note,) = load_commentary_notes(_write(tmp_path, payload))

    assert note.title == "T"


# --- nothing here may raise at startup -------------------------------------


def test_a_missing_file_is_empty_and_silent(tmp_path):
    """No commentary yet is an ordinary state, not a fault.

    A warning here would fire on every build of a catalog that simply has no
    notes, which is how a real warning gets tuned out.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert load_commentary_notes(tmp_path / "absent.json") == []


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("{not json", "not valid JSON"),
        ('{"notes": []}', "does not hold a list"),
        ('"a string"', "does not hold a list"),
    ],
)
def test_a_broken_file_warns_and_yields_nothing(tmp_path, raw, reason):
    path = tmp_path / "commentary.json"
    path.write_text(raw, encoding="utf-8")

    with pytest.warns(UserWarning, match=reason):
        assert load_commentary_notes(path) == []


def test_an_unreadable_file_warns_and_yields_nothing(tmp_path, monkeypatch):
    path = _write(tmp_path, [_note("T", "2026-01-01")])

    def boom(*_args, **_kwargs):
        raise PermissionError("nope")

    monkeypatch.setattr("pathlib.Path.read_text", boom)

    with pytest.warns(UserWarning, match="Could not read"):
        assert load_commentary_notes(path) == []


@pytest.mark.parametrize(
    "entry",
    [
        "just a string",
        {"date": "2026-01-01", "text": "no title"},
        {"title": "no date", "text": "t"},
        {"title": "no text", "date": "2026-01-01"},
        {"title": 7, "date": "2026-01-01", "text": "t"},
        {"title": "t", "date": "2026-01-01", "text": ["not", "a", "string"]},
        {"title": "t", "date": "15/09/2026", "text": "t"},
        {"title": "t", "date": "2026-13-45", "text": "t"},
    ],
)
def test_a_malformed_note_is_skipped_and_the_rest_survive(tmp_path, entry):
    """One bad note costs that note, not the file.

    The alternative — voiding the whole file — means a typo in a note from
    March takes today's note off the screen too. This follows
    `UserBenchmarkStore.load`, which filters bad members out of a good list.
    """
    payload = [_note("good one", "2026-09-15"), entry]

    with pytest.warns(UserWarning, match="Skipping note 1"):
        notes = load_commentary_notes(_write(tmp_path, payload))

    assert [n.title for n in notes] == ["good one"]


def test_a_file_of_nothing_but_bad_notes_is_empty(tmp_path):
    with pytest.warns(UserWarning, match="Skipping note"):
        assert load_commentary_notes(_write(tmp_path, ["bad", {}])) == []


# --- the file we actually ship ---------------------------------------------


def test_the_shipped_commentary_file_parses_cleanly():
    # Guards the placeholder the repo ships the way `test_data.py` guards
    # `indexdb.json`: it must parse, and it must do so without a warning.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        notes = load_commentary_notes()

    assert notes
    assert all(isinstance(n.date, date) and n.title and n.text for n in notes)
