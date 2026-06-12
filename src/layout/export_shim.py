"""Client-side shim that makes Plotly's PNG export work inside the BQuant
desktop app.

Plotly's modebar "Download plot as a png" button calls ``Plotly.downloadImage``,
which (since plotly.js PR #4008) hands the browser a ``blob:`` object-URL on the
download anchor. A real browser — including the BQuant *web* interface — saves
that to the user's Downloads. The BQuant *desktop* app, however, runs in an
embedded webview that does not implement ``blob:`` anchor downloads, so the host
shows a "pick an app / can't open this blob link" dialog and nothing is saved.

There is no Plotly config to swap the download back to a ``data:`` URI, and no
documented Bloomberg download bridge. But the desktop webview *does* honour
``data:`` URI downloads (the mechanism Plotly used before the blob change). So
this shim intercepts the blob download at the DOM level and re-issues the exact
same image as a ``data:`` URI download, which lands in the user's Downloads.

It is a single invisible ``anywidget`` (already a project dependency) mounted
once in the app tree; the global hook installs on first render and is a no-op in
a real browser where blob downloads already work (the converted ``data:``
download behaves identically there).
"""

from __future__ import annotations

import ipywidgets as W

try:
    import anywidget

    _HAVE_ANYWIDGET = True
except Exception:  # pragma: no cover - anywidget is a declared dependency
    _HAVE_ANYWIDGET = False

# Installed once on the frontend. Tracks the Blob behind every object-URL Plotly
# creates (deferring revoke so the click handler can still read it), then — in a
# capture-phase click listener, before the anchor's default blob download runs —
# converts our tracked blob downloads into an equivalent `data:` URI download.
_SHIM_ESM = r"""
function render({ el }) {
  el.style.display = "none";
  if (window.__bbgBlobDownloadShim) return;
  window.__bbgBlobDownloadShim = true;

  const blobs = new Map();
  const origCreate = URL.createObjectURL.bind(URL);
  const origRevoke = URL.revokeObjectURL.bind(URL);

  URL.createObjectURL = function (obj) {
    const url = origCreate(obj);
    if (obj instanceof Blob) blobs.set(url, obj);
    return url;
  };
  // Defer the real revoke so a download click handler can still resolve the
  // blob; everything else about createObjectURL/revokeObjectURL is preserved.
  URL.revokeObjectURL = function (url) {
    setTimeout(function () {
      blobs.delete(url);
      try { origRevoke(url); } catch (e) { /* already gone */ }
    }, 0);
  };

  document.addEventListener(
    "click",
    function (e) {
      const a =
        e.target && e.target.closest ? e.target.closest("a[download]") : null;
      if (!a) return;
      const href = a.getAttribute("href") || "";
      if (href.indexOf("blob:") !== 0) return;
      const blob = blobs.get(href);
      if (!blob) return; // not one we tracked — leave it alone

      // Replace the unsupported blob download with a data: URI download.
      e.preventDefault();
      e.stopImmediatePropagation();
      const name = a.getAttribute("download") || "download";
      const reader = new FileReader();
      reader.onload = function () {
        const a2 = document.createElement("a");
        a2.href = reader.result; // data:...;base64,...
        a2.download = name;
        document.body.appendChild(a2);
        a2.click();
        document.body.removeChild(a2);
      };
      reader.onerror = function () {
        console.error("bbg blob-download shim: failed to read blob", name);
      };
      reader.readAsDataURL(blob);
    },
    true, // capture: run before the anchor's own default action
  );
}
export default { render };
"""


if _HAVE_ANYWIDGET:

    class BlobDownloadShim(anywidget.AnyWidget):
        """Invisible widget that converts Plotly's ``blob:`` PNG download into a
        ``data:`` URI download so the modebar export works in the BQuant desktop
        webview. Mount one instance anywhere in the app tree."""

        _esm = _SHIM_ESM

else:  # pragma: no cover - graceful no-op when anywidget is unavailable

    class BlobDownloadShim(W.HTML):
        """Fallback no-op: the export shim is non-essential, so a missing
        ``anywidget`` must never break the dashboard — render nothing."""

        _esm = _SHIM_ESM  # kept for introspection/tests

        def __init__(self, *args, **kwargs):
            super().__init__(value="", layout=W.Layout(display="none"))
