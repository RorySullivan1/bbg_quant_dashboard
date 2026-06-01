---
name: ipywidgets
description: Reference for building interactive UIs with the ipywidgets package in Jupyter / JupyterLab / Voila — the widget model (traitlets, .value, observe), the widget catalog, layout containers (Box/HBox/VBox, GridBox, GridspecLayout, AppLayout, TwoByTwoLayout, Tab, Accordion, Stack), the Layout and Style objects, events and linking (observe, on_click, interact, link/jslink), and the Output widget. Use whenever working with ipywidgets — creating or wiring widgets, arranging them in containers/grids, sizing/aligning with Layout, styling controls, handling value changes or clicks, linking widgets, or debugging why a widget isn't updating, sizing, or rendering. Trigger on ipywidgets, "widget", VBox/HBox/GridBox/GridspecLayout/AppLayout/Tab/Accordion/Stack, observe/interact, Output, Layout, .value, link/jslink.
---

# ipywidgets

`ipywidgets` (aka Jupyter Widgets) renders interactive HTML/JS controls in
Jupyter, JupyterLab, and Voila and keeps them in sync with Python objects.
This is a reference for the **package**: the model, the widgets, the layout
containers, styling, and events. Convention: `import ipywidgets as widgets`.

## Mental model

A widget is a **synchronized pair**: a Python (kernel-side) model and a
frontend (browser) view, kept in sync over a Comm channel via
**traitlets**. Widget attributes are traits; setting one in Python updates
the browser and vice-versa. The most important trait is usually **`.value`**.

```python
import ipywidgets as widgets
slider = widgets.IntSlider(value=5, min=0, max=10)
slider                 # last expression auto-displays in a notebook
# from IPython.display import display; display(slider)
slider.value           # -> 5 ; setting slider.value = 8 moves the UI live
```

A widget displayed twice shows two synced views of the *same* model.

## Widget catalog (by category)

- **Numeric:** `IntSlider`, `FloatSlider`, `FloatLogSlider`,
  `IntRangeSlider`, `FloatRangeSlider`, `BoundedIntText`, `IntText`,
  `FloatText`, `IntProgress`, `FloatProgress`.
- **Boolean:** `Checkbox`, `ToggleButton`, `Valid`.
- **Selection:** `Dropdown`, `Select`, `SelectMultiple` (**`.value` is a
  tuple**), `RadioButtons`, `ToggleButtons`, `SelectionSlider`,
  `SelectionRangeSlider`. Set choices via `options=` (a list, or
  `[(label, value), …]`).
- **String:** `Text`, `Textarea`, `Combobox`, `Password`, `Label`, `HTML`,
  `HTMLMath`.
- **Button & output:** `Button` (use `.on_click`), `Output` (see below).
- **Media / misc:** `Image`, `Video`, `Audio`, `FileUpload`, `DatePicker`,
  `ColorPicker`, `Play` (animation driver).

Common shared traits: `value`, `description`, `disabled`, and for selection
widgets `options` / `index`.

## Layout containers

**Flexbox boxes** — `Box`, `HBox` (row), `VBox` (column). Children passed as
a list/tuple; reassign `.children` to swap content.

```python
widgets.VBox([widgets.HBox([a, b]), c])
```

**`GridBox`** — CSS-grid container; drive it through its `Layout`:

```python
widgets.GridBox(
    [w0, w1, w2, w3],
    layout=widgets.Layout(
        grid_template_columns="repeat(2, 1fr)",
        grid_gap="8px",
    ),
)
```

**`GridspecLayout(n_rows, n_cols)`** — grid with **item placement by
indexing/slicing** (great for dashboards):

```python
grid = widgets.GridspecLayout(3, 3)
grid[0, :] = widgets.Button(description="header (full row)")
grid[1:, 0] = widgets.Button(description="sidebar (spans rows)")
grid[1:, 1:] = main_widget
```

**`AppLayout`** — "holy grail" page layout with named panes:

```python
widgets.AppLayout(
    header=hdr, left_sidebar=nav, center=body,
    right_sidebar=aside, footer=ftr,
    pane_widths=["200px", 1, "200px"], pane_heights=["60px", 4, "40px"],
)
```

**`TwoByTwoLayout`** — quick 2×2 quadrant layout
(`top_left`/`top_right`/`bottom_left`/`bottom_right`).

**Selection containers:**
- `Tab` and `Accordion` — hold `children`; set pane titles via
  `.titles = (...)` (ipywidgets ≥ 8) or `.set_title(i, "…")` (older);
  `selected_index` controls/reads the open pane (`None` collapses an
  Accordion).
- `Stack` (ipywidgets ≥ 8) — shows exactly **one** child at a time by
  `selected_index`; pair with a selector (e.g. `Dropdown`) via `jslink` for
  kernel-free page switching.

## The `Layout` object (CSS, on `widget.layout`)

Every widget has a `.layout` exposing CSS:

- **Sizing:** `width`, `height`, `min_width`/`max_width`,
  `min_height`/`max_height` (`"100%"`, `"320px"`, `"auto"`).
- **Box model:** `margin`, `padding`, `border`.
- **Flexbox (on a Box):** `display="flex"`, `flex_flow="row"|"column"`,
  `align_items`, `justify_content`; **on children:** `flex` (e.g.
  `"1 1 auto"` to grow/shrink), `align_self`, `order`.
- **CSS grid:** `grid_template_columns/rows`, `grid_gap`, `grid_area`.
- **Visibility:** `visibility`, `display="none"` (collapse).
- **Custom CSS hook:** `widget.add_class("my-class")` /
  `remove_class(...)`, then target `.my-class` from an injected
  `widgets.HTML("<style>…</style>")` — this is how you reach `:hover`,
  scrollbars, transitions, etc. that the Python API doesn't expose.

Prefer flex/`%` sizing over fixed pixels for responsive layouts; to make
side-by-side panels equal height, let children grow with `flex` rather than
hardcoding heights.

## Styling (`widget.style`)

`.style` is **widget-specific**: `Button` has `button_color`,
`text_color`, `font_weight`; sliders have `handle_color`; progress bars have
`bar_color`; description-bearing widgets have `description_width`.

```python
b = widgets.Button(description="Go")
b.style.button_color = "#16a34a"
dd = widgets.Dropdown(description="Metric",
                      style={"description_width": "initial"})
```

For anything `.style` can't express, use the `add_class` + injected-CSS hook.

## Events & interactivity

- **`observe`** — react to trait changes:
  ```python
  def on_change(change):   # change: owner, name, old, new, type
      print(change.new)
  slider.observe(on_change, names="value")   # omitting names fires on all traits
  ```
  Detach with `unobserve`.
- **`Button.on_click(handler)`** — buttons have no `value`; use clicks.
- **`interact` / `interactive` / `interactive_output`** — auto-generate
  controls from a function's args; wrap constants with `fixed(...)`.
  `interactive_output(f, {...})` separates control layout from output.
- **Linking widgets:** `link((a, "value"), (b, "value"))` and `dlink`
  (directional) run **kernel-side**; `jslink` / `jsdlink` run **in the
  browser** (keep working in a static export / Voila without the kernel).

## The `Output` widget

Captures stdout / rich display / matplotlib figures into a placed area:

```python
out = widgets.Output()
with out:
    print("logged here")          # or display(fig), df, etc.
out.clear_output(wait=True)        # clear (wait=True avoids flicker)
```

Useful for logs, dynamic content, or embedding non-widget output in a layout.

## Performance & correctness

- Batch many updates with `with widget.hold_trait_notifications():` to emit
  one frontend sync.
- **Reuse** widgets and swap `children` (or use `Stack`) instead of
  rebuilding trees; rebuilding drops state and is slow.
- Keep `observe` handlers cheap; avoid triggering cascades of recompute.
- Call `widget.close()` to release widgets you no longer need.

## Jupyter vs Voila

The same widgets render under **Voila** (notebook → standalone app) — there
are no input cells and the last expression / `display()` provides the view.
Avoid relying on cell side effects; build and return/`display` a root
container.

## Common pitfalls

- Forgetting `names="value"` → handler fires for every trait.
- `SelectMultiple.value` is a **tuple**, not a scalar.
- `children` expects a tuple/list; assign a new sequence to change it.
- `Tab`/`Accordion` title API differs by version (`titles` vs `set_title`).
- Setting `Layout` props on the wrong object (set on `widget.layout`).
- Fixed pixel sizing where flex/`%` is needed → misaligned/non-responsive UI.

## In this repo (brief)

`build_app()` in `src/layout.py` assembles the whole widget tree; style
tokens (colors/fonts/sizes) live in `src/style.py` — reference them, don't
inline hex. Tabular data grids use the **separate** `ipydatagrid` package
(not core ipywidgets). See `CLAUDE.md` for the project's layout contract and
conventions, and the `plotly` skill for chart widgets.
