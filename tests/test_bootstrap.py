"""The runtime package bootstrap (v0.9.18 #263).

`itables` cannot be added to the BQuant environment outside the notebook, so
the app installs it at startup. Three properties matter and all three fail
silently if broken, which is why they are pinned here rather than left to the
terminal: a warm session must not shell out at all, the install must produce
**no** output (anything it prints renders in the Voila page), and a failure
must be returned rather than raised, because a traceback in a Voila cell is not
something the user can see.
"""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stderr, redirect_stdout

import pytest
from src import bootstrap


class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


def test_defaults_cover_the_widget_stack():
    # anywidget is what carries the ITable JS over the widget protocol; dropping
    # it would leave a table that imports fine and never renders.
    assert set(bootstrap.RUNTIME_REQUIREMENTS) == {"itables", "anywidget"}


def test_present_packages_do_not_shell_out(monkeypatch):
    """A warm session must be free. `pytest` itself is always importable, so it
    stands in for an already-installed requirement."""
    called: list = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a) or _Proc())
    ok, detail = bootstrap.ensure_runtime_packages(("pytest",))
    assert ok and detail == "already present"
    assert called == []  # no pip invocation at all


def test_missing_package_is_installed_quietly_and_caches_invalidated(monkeypatch):
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return _Proc(stdout="Successfully installed ghostpkg")

    invalidated: list = []
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        bootstrap.importlib, "invalidate_caches", lambda: invalidated.append(True)
    )
    # First call reports it missing, the post-install check reports it present.
    calls = iter([["ghostpkg"], []])
    monkeypatch.setattr(bootstrap, "_missing", lambda names: next(calls))

    ok, detail = bootstrap.ensure_runtime_packages(("ghostpkg",))

    assert ok and "ghostpkg" in detail
    assert seen["cmd"][1:4] == ["-m", "pip", "install"]
    assert "ghostpkg" in seen["cmd"]
    # The property that makes it silent: pip's pipes are captured, so nothing
    # reaches the notebook's stdout and nothing renders under Voila.
    assert seen["kwargs"]["capture_output"] is True
    # pip writes into site-packages after the interpreter cached its listing;
    # without this the fresh package stays invisible to import in this kernel.
    assert invalidated == [True]


def test_failed_install_is_returned_not_raised(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _Proc(stderr="ERROR: No matching distribution"),
    )
    monkeypatch.setattr(bootstrap.importlib, "invalidate_caches", lambda: None)
    monkeypatch.setattr(bootstrap, "_missing", lambda names: ["ghostpkg"])

    ok, detail = bootstrap.ensure_runtime_packages(("ghostpkg",))

    assert ok is False
    assert "ghostpkg" in detail
    assert "No matching distribution" in detail  # the reason survives for the banner


def test_nothing_reaches_stdout_or_stderr(monkeypatch):
    """The whole point. Anything printed here lands in the rendered Voila page."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _Proc(
            stdout="Collecting ghostpkg\n", stderr="WARNING: noisy\n"
        ),
    )
    monkeypatch.setattr(bootstrap.importlib, "invalidate_caches", lambda: None)
    calls = iter([["ghostpkg"], []])
    monkeypatch.setattr(bootstrap, "_missing", lambda names: next(calls))

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        bootstrap.ensure_runtime_packages(("ghostpkg",))
    assert out.getvalue() == ""
    assert err.getvalue() == ""


@pytest.mark.parametrize(
    "spec,expected", [("itables", "itables"), ("itables==2.9.1", "itables")]
)
def test_missing_ignores_a_pinned_version(spec, expected):
    # `_missing` checks importability, so a pinned spec must be split before the
    # lookup or a pinned requirement would reinstall on every single startup.
    assert bootstrap._missing((spec,)) in ([], [spec])
    import importlib.util

    assert (importlib.util.find_spec(expected) is None) == (
        bootstrap._missing((spec,)) == [spec]
    )
