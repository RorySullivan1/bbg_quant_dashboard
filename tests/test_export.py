"""Server-side PNG export (`src/layout/export.py`).

The figure is rendered to PNG bytes via kaleido — entirely server-side, so the
result reaches the user without the client-side download Bloomberg's terminal
webview blocks. The render tests need kaleido (with its bundled Chromium)
installed, so they skip cleanly where it isn't; the control's wiring is tested
without invoking kaleido so it always runs.
"""

from __future__ import annotations

import ipywidgets as W
import plotly.graph_objects as go
import pytest
from src.layout.export import _png_export_control, _render_png

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _tiny_fig() -> go.Figure:
    return go.Figure(go.Scatter(x=[0, 1, 2], y=[1, 3, 2]))


def test_export_control_structure_without_kaleido():
    # The control is a VBox whose first child is the "⤓ PNG" button and whose
    # second is the (initially empty) result sink. Building it must not touch
    # kaleido — the render only happens on click.
    control = _png_export_control(_tiny_fig, filename="chart.png")
    assert isinstance(control, W.VBox)
    button, sink = control.children
    assert isinstance(button, W.Button) and "PNG" in button.description
    assert isinstance(sink, W.VBox) and sink.children == ()


def test_render_png_returns_png_bytes():
    pytest.importorskip("kaleido")
    png = _render_png(_tiny_fig())
    assert isinstance(png, bytes) and png.startswith(_PNG_MAGIC)


def test_click_populates_sink_with_link_and_preview():
    pytest.importorskip("kaleido")
    control = _png_export_control(_tiny_fig, filename="my chart.png")
    button, sink = control.children
    button.click()
    # Delivery is a user-clicked data-URI download link + an inline Image preview.
    link, preview = sink.children
    assert isinstance(link, W.HTML)
    assert 'download="my_chart.png"' in link.value  # spaces normalized
    assert "data:image/png;base64," in link.value
    assert isinstance(preview, W.Image)
    assert bytes(preview.value).startswith(_PNG_MAGIC)  # Image stores a memoryview


def test_click_surfaces_error_without_raising(monkeypatch):
    # A kaleido/render failure must surface in the sink, never raise out of the
    # click handler (which would break the whole callback).
    import src.layout.export as export_mod

    def _boom(_fig):
        raise RuntimeError("no chromium")

    monkeypatch.setattr(export_mod, "_render_png", _boom)
    control = _png_export_control(_tiny_fig, filename="chart.png")
    button, sink = control.children
    button.click()
    (msg,) = sink.children
    assert isinstance(msg, W.HTML)
    assert "PNG export failed" in msg.value and "no chromium" in msg.value
    assert button.disabled is False  # re-enabled in the finally block
