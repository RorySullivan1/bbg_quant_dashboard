"""Server-side chart PNG export for the Bloomberg terminal.

Every chart is a plotly ``FigureWidget`` carrying the built-in modebar
"Download plot as PNG" camera button. That button is **client-side**
(``Plotly.downloadImage`` builds a data-URI and fires a *synthetic* anchor
click), which works in a real browser / Voila but is **blocked inside
Bloomberg's embedded terminal webview** — so terminal users have no way to get
a chart image out.

This module renders the *already-built* figure to PNG **server-side** with
kaleido (no browser download involved) behind a small "⤓ PNG" button, then
delivers the result two ways: an inline ``Image`` preview (always displays — the
guaranteed fallback) and a **user-clicked** ``<a download>`` data-URI link (a
genuine click frequently succeeds where Plotly's synthetic auto-download is
blocked).
"""

from __future__ import annotations

import base64
from collections.abc import Callable

import ipywidgets as W
import plotly.graph_objects as go

from ..config import PNG_EXPORT_SCALE, PNG_EXPORT_WIDTH
from ..style import Color


def _render_png(fig: go.Figure) -> bytes:
    """Render a plotly figure to PNG bytes via kaleido (server-side).

    Captures the figure's *current* state — traces, colors, dark theme — so the
    export matches what's on screen. Runs entirely in Python; no browser
    download is involved, which is why it works inside the terminal webview.
    """
    return fig.to_image(format="png", width=PNG_EXPORT_WIDTH, scale=PNG_EXPORT_SCALE)


def _png_export_control(
    get_fig: Callable[[], go.Figure],
    *,
    filename: Callable[[], str] | str,
) -> W.VBox:
    """A "⤓ PNG" button + result sink that exports a plotly chart to PNG.

    ``get_fig`` is resolved at *click* time — panes swap which figure is mounted,
    so the export must target whatever chart is currently shown. ``filename`` is
    a string or a zero-arg callable (so the name can follow the active analysis).

    Returns a ``VBox`` whose first child is the button (``.children[0]``) and
    whose second is the sink the rendered image + download link drop into.
    """
    button = W.Button(
        description="⤓ PNG",
        tooltip="Render this chart to a downloadable PNG",
        layout=W.Layout(width="96px", height="30px", margin="6px 0 0 0"),
    )
    button.add_class("bbg-pill")
    sink = W.VBox(layout=W.Layout(width="100%"))

    def _name() -> str:
        raw = filename() if callable(filename) else filename
        return raw.replace(" ", "_")

    def _on_click(_b: W.Button) -> None:
        button.disabled = True
        sink.children = (
            W.HTML(f"<span style='color:{Color.CHART_TEXT.value}'>Rendering…</span>"),
        )
        try:
            png = _render_png(get_fig())
        except Exception as exc:  # kaleido import / render failure — never raise
            sink.children = (
                W.HTML(
                    f"<span style='color:{Color.RED_600.value}'>PNG export failed: "
                    f"{type(exc).__name__}: {exc}</span>"
                ),
            )
            return
        finally:
            button.disabled = False

        b64 = base64.b64encode(png).decode("ascii")
        link = W.HTML(
            f'<a download="{_name()}" href="data:image/png;base64,{b64}" '
            f'style="color:{Color.ACCENT_2.value};font-weight:600;'
            'text-decoration:none">⤓ Download PNG</a>'
        )
        preview = W.Image(
            value=png,
            format="png",
            layout=W.Layout(max_width="100%", margin="4px 0 0 0"),
        )
        sink.children = (link, preview)

    button.on_click(_on_click)
    return W.VBox(
        [button, sink],
        layout=W.Layout(width="100%", margin="2px 0 0 0"),
    )
