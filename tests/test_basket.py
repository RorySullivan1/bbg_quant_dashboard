"""The `Basket` — the Multi-Strategy selection's one owner (#341 dec. 1, #342).

The cap used to be guarded in three places and the selection used to live on a
widget; these pin that neither is true any more. The rule under most of them is
that **a rejected write changes nothing** — not the value, and not the
observers, because a grid re-tick and an analytics re-slice for a change that
did not happen are both worse than the rejection itself.
"""

from __future__ import annotations

import pytest
import traitlets
from src.config import MAX_SELECTED_STRATEGIES
from src.layout.basket import Basket, BasketResult


def _fires(basket: Basket) -> list[tuple[str, ...]]:
    """Record every `value` change the basket announces."""
    seen: list[tuple[str, ...]] = []
    basket.observe(lambda change: seen.append(change["new"]), names="value")
    return seen


def test_default_cap_is_the_configured_maximum():
    assert Basket().cap == MAX_SELECTED_STRATEGIES


def test_add_appends_in_order_and_dedups():
    b = Basket(cap=5)
    b.add(["B", "A"])
    b.add("C")
    b.add("A")  # already held
    assert b.value == ("B", "A", "C")


def test_add_over_the_cap_is_rejected_whole():
    """All or nothing: seating a subset would be the app choosing for the user."""
    b = Basket(cap=3)
    b.add(["A", "B"])
    fires = _fires(b)

    result = b.add(["C", "D", "E"])

    assert result == BasketResult(accepted=False, shown=5, cap=3)
    assert b.value == ("A", "B"), "a rejected add must leave the basket alone"
    assert fires == [], "a rejected add must not fire observers"


def test_replace_over_the_cap_is_rejected_and_reports_the_count():
    b = Basket(cap=2)
    b.add("A")
    result = b.replace(["X", "Y", "Z"])
    assert result.accepted is False
    assert (result.shown, result.cap) == (3, 2)
    assert b.value == ("A",)


def test_replace_dedups_keeping_the_first_occurrence_and_the_order_given():
    b = Basket(cap=5)
    b.replace(["C", "A", "C", "B", "A"])
    assert b.value == ("C", "A", "B")


def test_toggle_is_membership_flipped():
    b = Basket(cap=5)
    assert b.toggle("A").accepted
    assert b.value == ("A",)
    assert b.toggle("A").accepted
    assert b.value == ()


def test_toggle_over_the_cap_is_rejected():
    b = Basket(cap=1)
    b.add("A")
    result = b.toggle("B")
    assert result.accepted is False
    assert b.value == ("A",)


def test_remove_ignores_names_not_held():
    b = Basket(cap=5)
    b.add(["A", "B"])
    b.remove(["B", "NOPE"])
    assert b.value == ("A",)


def test_re_adding_appends_rather_than_restoring_position():
    """Cards are drawn in basket order; a ticker reappearing in the middle of
    the strip would read as a different card moving."""
    b = Basket(cap=5)
    b.add(["A", "B", "C"])
    b.remove("A")
    b.add("A")
    assert b.value == ("B", "C", "A")


def test_clear_empties_it():
    b = Basket(cap=5)
    b.add(["A", "B"])
    b.clear()
    assert b.value == ()


def test_observer_fires_once_per_accepted_change_and_not_for_a_no_op():
    b = Basket(cap=5)
    fires = _fires(b)
    b.add(["A", "B"])
    b.add("A")  # already held — no change
    b.remove("NOPE")  # not held — no change
    b.remove("A")
    assert fires == [("A", "B"), ("B",)]


def test_a_bare_string_is_one_ticker_not_one_per_character():
    b = Basket(cap=5)
    b.add("SPX Index")
    assert b.value == ("SPX Index",)


def test_assigning_value_directly_over_the_cap_raises():
    """The floor under the methods: there is no back door to 26 names."""
    b = Basket(cap=2)
    with pytest.raises(traitlets.TraitError):
        b.value = ("A", "B", "C")
    assert b.value == ()


def test_assigning_value_directly_dedups():
    b = Basket(cap=3)
    b.value = ("A", "B", "A")
    assert b.value == ("A", "B")


def test_len_contains_and_room():
    b = Basket(cap=4)
    b.add(["A", "B"])
    assert len(b) == 2
    assert "A" in b and "Z" not in b
    assert b.room == 2
