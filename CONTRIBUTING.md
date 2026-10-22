# Contributing

Thanks for helping improve Krita Speech Bubble Generator.

## Report a bug or suggest a feature

Open an [issue](../../issues) with a clear description. For bugs, include your
Krita version, operating system, steps to reproduce, and what you expected to
happen. Screenshots and a small example document can help explain visual or
editing problems.

For feature ideas, describe the drawing or lettering workflow you want to
improve. Discuss substantial changes in an issue before starting work.

## Work on the plugin

Fork this repository, create a branch, and make focused changes. The plugin
source is in `krita_speech_bubble_generator/`; its entry point is
`krita_speech_bubble_generator.py`.

For local development, copy or link the package directory and
`krita_speech_bubble_generator.desktop` into your Krita resource folder's
`pykrita` directory. Disable other installed copies so you know which version
you are using. Restart Krita after changing Python source.

### Architecture

Program to small interfaces, implement interchangeable behavior polymorphically,
and compose collaborators. Keep shared mathematics and values simple; do not
duplicate algorithms or introduce inheritance merely to move code between files.

The package has three responsibility-based subpackages: `bubbles/` describes and
renders bubbles, `editor/` coordinates interaction, and `krita_host/` accesses
native documents. Keep their `__init__.py` files free of eager imports; the
existing root bootstrap and public docker module remain the entry points.

| Module | Responsibility |
| --- | --- |
| `krita_speech_bubble_generator.py` | Thin docker shell, dependency composition, and Krita lifecycle forwarding. |
| `editor/view.py` | Qt controls, local input behavior, and semantic edit signals. |
| `editor/presenter.py` | Editor transitions, pending edits, selection polling, and background scheduling. |
| `editor/contracts.py` | View, rendering, and document-access contracts. |
| `editor/state.py` | Explicit editing target and session values. |
| `editor/preferences.py` | Local cross-session editor preferences, independent of document annotations. |
| `bubbles/settings.py` | Immutable editable settings and version-1 saved-record validation/encoding. |
| `bubbles/renderer.py` | Text measurement/wrapping and the shared preview/export pipeline. |
| `bubbles/types.py` | Rendering-facing `BubbleType` style strategies and the shape/style composition adapter. |
| `bubbles/shapes.py` | `BubbleShape` interface, shape-owned padding, layout-aware enclosures, convex hulls and subdivision. |
| `bubbles/shouting_algorithms.py` | `ShoutingAlgorithm` interface and the four contour implementations. |
| `bubbles/registry.py` | Ordered built-in implementations and identifier lookup. |
| `bubbles/geometry.py` | Shared path, tail, and SVG mathematics. |
| `krita_host/gateway.py` | Native document reads/writes, selection resolution, annotations, and placement. |
| `krita_host/legacy.py` | Conservative, opt-in recovery of one original-plugin outline and its text from SVG. |
| `krita_host/recovery.py` | Stable group-ID recognition, conservative old-record matching, and placement reconstruction after reparenting. |
| `krita_host/canvas_context.py` | Canvas transforms and temporary background snapshots. |
| `editor/preview.py` | Preview drawing, coordinate mapping, and tail-handle input. |
| `editor/tail_compass.py`, `editor/text_resize_handle.py`, `editor/wheel_guard.py` | Local tail presets, text-resize and scroll interactions. |

The presenter consumes contracts, not concrete controls or native shapes.
Dependencies are assembled by the docker shell. Geometry implementations must not
read widgets, documents, or global random state. UI events carry settings
snapshots; rendering never generates a new pattern seed.

#### Add a shape, style or shouting algorithm

Implement `BubbleShape`, `BubbleType` or `ShoutingAlgorithm` and add the implementation
to `SHAPES`, `BUBBLE_STYLES` or `SHOUTING_ALGORITHMS`. Shapes own padding and
enclosure geometry; styles decorate the supplied contour through `decorate`.
Shapes also supply `project` for normalized decoration coordinates: Oval keeps
its analytic projection and existing seeded patterns, while polygonal shapes use
actual contour intersections. Styles must not identify shapes by name or class.
`BubbleType.layout_body` is the rendering-facing layout boundary, and the
composition adapter combines one shape with one style. A shouting bubble composes
its selected algorithm; do not create subclasses for individual combinations.
`BUBBLE_TYPES` and the original `body_rect`/`body_path` methods remain legacy
geometry API adapters, not editor selectors. Keep identifiers
stable because they are saved in documents. Selector order and available
implementations come from the registries, and conditional controls use capability
metadata rather than checks for concrete classes or style names.

Reuse common enclosure sizing, seeded spike generation, tail construction, and
SVG output. Distinct strategies can supply different parameters to shared
mechanics without copying the entire algorithm. Preserve random draw order when
refactoring: a saved seed must continue producing the same outline.

Enclosure padding is a shape policy: at zero, retain only necessary outline
and shape clearance, not an arbitrary text-size-scaled minimum margin. Measure
text at the SVG's actual pixel size and include glyph overhangs, accents and
descenders. Preserve automatic wrapping and baseline spacing.
Optical vertical centering is opt-in: use the filled glyph-area centroid,
including holes and overlapping strokes, and expand the enclosure as needed
without changing wrapping or baseline spacing. Empty lettering retains the
geometric layout.
Use `BubbleShape.layout` for measured enclosure sizing. Its inputs are the centered
text bounds and each positioned line's bounds, including rich runs, glyph
overhangs, empty lines and optical centering. Tracing builds a convex hull and
outward padding; Rounded subdivides angles three times and conservatively expands
the result to retain the padded enclosure. Square supplies bounded rounded corners
with straight edge segments and expands enough to retain the padded rectangle.
Rounded decoration delegates this policy to the shape, without identifying shape
names or classes. Sharp retains hull vertices. Thought
and Shouting decorate the same selected contour without changing the lettering.
Simple horizontal clearance is twice vertical clearance. Advanced padding
decouples the two axes for every shape; only Oval supports squareness. Disabling
Advanced resets vertical padding to simple padding and squareness to zero.
The saved `oval_custom`, `oval_vertical_padding` and `oval_squareness` names are
retained for compatibility but belong to shape settings, not style settings.
Keep cloud lobes and spike patterns seeded while shaping their underlying contour.

Wrapping is an independent text policy: `Standard` preserves the original
automatic wrapper; `Diamond` uses measured rich word widths and symmetric
short/long/short targets. It only operates in automatic mode, respects paragraph
breaks, and feeds the same line/run measurement and SVG pipeline as Standard.
Never reorder words or strip source formatting when changing line breaks.
Simple tail angles and straight-tail symmetry use the line from the body center to the pointer,
never the combined body-and-tail bounds or a nearest-edge normal. Intersect that
ray with the actual body for the tail-length origin; do not snap to supporting
corners or spikes. Keep dragging and preview/export consistent.
Curvature offsets rotate with that axis without moving the pointer or changing
the straight-line tail-length setting. Use the same bend for speech tails and
thought trails, preserving seeded blob sizes and irregularity.
Tail length is an absolute value, independent of typography. Controls, dragging,
saved records and preferences share its 0–990 integer range in `INTEGER_RANGES`;
font changes and style pastes must not shorten it. This retains the previous
overall maximum (99 × 10) without coupling a target's tail to a pasted font size.
Tail enablement is independent of placement: disabling removes the tail and both
preview handles without clearing settings. Advanced mode stores a separate start
angle on the actual body contour and an endpoint offset from the body center.
Unset advanced positions derive from simple placement; the first start drag
freezes the displayed endpoint. Start and end move independently, and the
simple compass, length and lock controls are disabled in Advanced mode. Both
speech and thought composition receive the same optional explicit anchor through
`TailParameters`; do not add style dispatch for advanced tails. Keep endpoints
outside the body, including after enclosure changes. Missing saved fields retain
enabled simple tails, and style transfer preserves all placement and mode fields.
Thought trail counts use the saved `thought_blobs` setting (1–10, default 3),
independently of body node counts. Keep seeded blob sizes and rotations stable
while reserving each blob's diameter and outline along the shared tail curve,
then dividing the remaining arc length into N+1 equal empty gaps for N blobs.
Use conservative radii for irregular ellipses, and include the body's half-stroke
at the start. Enforce body clearance as a minimum for the first center; when it
must advance, keep subsequent edge gaps and the final tip gap equal. Reduce
oversized blobs to fit short or crowded trails without moving the selected
endpoints.

Add contract coverage for each implementation, and specific geometry coverage
where its behavior differs. A new persisted option may also require settings,
codec, and UI changes; adding an implementation must not require editing central
renderer or document-write conditionals.

#### Preserve document and editing contracts

Keep `rsbg-bubble`, `rsbg-bubble-<id>`, the `rsbg-bubble-` annotation prefix, and the
version-1 record format compatible. Fresh editor defaults and defaults for missing
legacy fields are deliberately different; do not merge them. Normalize old
records before loading controls, without mutating the caller's data.
New records add `shape` and `wrapping`, with `style` containing only the independent
style. When `shape` is missing, normalize legacy Oval/Square to Sharp on the same
shape, Rounded/Round to Square/Rounded, and Thought/Shouting to Oval with their
existing style. Missing wrapping is Standard. Loading is read-only: existing
artwork adopts the new enclosure sizing only on the next user edit.

New and imported groups use `rsbg-bubble-<uuid>` identities. Save the version-1
record under the group name as a layer-independent document annotation, as well
as the legacy layer-scoped annotation key. Never match current bubbles by their
lettering: duplicate and empty text must survive repeated merges. Load old
layer-scoped records and upgrade their group identity without redrawing.
The optional version-1 `layer_id` field identifies the layer whose coordinate
system the saved baseline belongs to, not the bubble's identity. It prevents
stale layer-scoped records from winning when a bubble moves back to an old layer.
When native merging bakes group transforms into children, reconstruct placement
from the saved group's SVG outline before updating it. Older already-merged
groups may reconnect by uniquely matching orphaned records; ambiguous cases must
be refused. Selection observation is read-only; migration happens when loading.

Pending edits belong to an explicit document/layer/group target. Reconcile
selection before a delayed write, preserve eligible edits to the previous target,
and never redirect them to the newly selected bubble or document. Failed writes
must not advance the successfully applied settings. Updates on shared layers
must retain sibling artwork, stacking, selection, and canvas transforms.

Legacy import is explicit, not part of selection polling. Reject ambiguous
layers before modifying them, and keep the original shapes until the first
update. Join recovered lines into automatically centered text, default to Oval,
and fit padding through the shared renderer to account for its enclosure sizing.
Imported settings use the same version-1 records as new bubbles.
Recover the original tail tip as well as the body bounds. After fitting padding,
map that tip into the regenerated body's coordinates and fit its tail through
the renderer, rather than copying the old bounding-box extension as the new
visible length. Preserve the original tip's canvas placement within control
rounding, including when the old body is rotated or nonuniformly scaled.

Keep Qt timers parented to the owning objects and on the GUI thread. Hide-time
flushing, canceled background work, and programmatic-load signal suppression are
part of the editing contract, not incidental implementation details.

#### Dependencies

**Do not add dependencies.** This applies to runtime, development, testing,
building, packaging, and CI, including optional or vendored libraries. Use the
standard library and the existing PyQt5/Krita APIs; no framework, package upgrade,
runtime download, or minimum-Python-version increase is needed for this
architecture. Use `abc`, `typing`, `dataclasses`, and the existing `unittest` runner
instead of adding interface, injection, serialization, or architecture tools.

### Build an installable ZIP

With Python 3.9 or newer, run from the repository root:

```sh
python3 scripts/build_zip.py
```

The output is `dist/krita_speech_bubble_generator.zip`. To choose another
destination, pass `--output /path/to/plugin.zip`. The script also works when
invoked from another directory. It packages the desktop entry and plugin folder
at the ZIP root, along with the license, and excludes Python caches and hidden
files. No Krita or PyQt installation is needed to build it.

To publish a release, push a version tag such as `v1.0.0`. The
`Build release ZIP` GitHub Actions workflow runs the same build script, saves
the ZIP as a workflow artifact, and attaches it to the corresponding GitHub
release, creating that release with generated notes if it does not exist.

### Automated tests

With Python 3 and PyQt5 available, run from the repository root:

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
```

The tests use real Qt rendering and input handling with a substitute Krita host.
They do not require Krita, but do not replace trying changes in the application.

### VS Code and strict typing

Use a repository-local environment for the plugin's existing PyQt5 requirement:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install PyQt5
```

In VS Code, run **Python: Select Interpreter** and select `.venv/bin/python`.
The workspace defaults to this interpreter, and `pyrightconfig.json` enables
strict analysis of the plugin source. PyQt5 includes its own type declarations;
the small declarations under `stubs/krita/` describe only the native Krita API
used by the bootstrap. They are development-only and are not packaged with the
plugin. The two native imports suppress only `reportMissingModuleSource` because
Krita supplies their implementation inside the application, not in `.venv`.
Native document operations are described by structural contracts in
`krita_host/contracts.py`, while editor sessions retain opaque host identities.
Keep these declarations consistent with the Krita APIs actually used; do not
replace unresolved imports or missing annotations with blanket suppressions.

Run the existing suite using the same interpreter:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests
```

### Try changes in Krita

Exercise the affected workflow in a `.kra` document. For bubble editing changes,
include adding a bubble, selecting and editing it, switching between bubbles,
and saving and reopening the document. Check automatic updates and selection
changes, and ensure updates do not move the bubble or alter neighbouring artwork.
For original-plugin import, try a rounded bubble with a tail, one without a
tail, and a square bubble. Check that import alone leaves the artwork unchanged,
that the first edit keeps its placement, and that saving and reopening retains
editability. Verify that unrelated artwork and multi-bubble layers are refused.
Try the tail compass with locked, unlocked and zero-length tails, then drag to
an angle between presets.
Toggle tail Enabled off and on with a configured curved tail. In Advanced mode,
drag each handle, including with canvas background, rotation and scaling; confirm
that moving the start retains the end, the start follows the edge, and the end
cannot be placed inside the bubble. Check disabled simple controls, return to
simple mode, and save/reopen with both a disabled tail and advanced placement.

For merged bubbles, include identical dialogue and empty lettering. Merge
several generated vector layers, save and reopen, then select and edit each
bubble without using the Import tab. Repeat merges and try merging immediately
after typing a pending edit. Check that selection alone leaves artwork untouched,
the first edit retains placement and sibling artwork, and reopening keeps
editing enabled. Try older already-merged bubbles too: unique saved settings
should reconnect automatically, while ambiguous or missing settings are refused.

Add regression coverage for changed behaviour where practical. Update user
documentation when controls or workflows change, and describe your changes and
how you exercised them in the pull request.

## Documentation and images

Keep the README focused on installing and using the plugin. Contributor guidance
belongs here; agent-specific development guidance belongs in [AGENTS.md](AGENTS.md).

The README illustration is `docs/images/bubble-preview.svg`, sized
**1200 x 480 pixels (2.5:1)**. It is a style illustration, not a screenshot of
Krita. A screenshot or replacement illustration at the same size can take its
place; update the README image link and alt text if its format or content changes.

## License and attribution

Contributions must be compatible with this project's GPLv3 license. Retain the
original license and applicable copyright notices, and credit externally sourced
work appropriately.

This project derives from Danil Zotin's
[Rogudator's Speech Bubble Generator](https://github.com/rogudator/rogudators_speech_bubble_generator).
The original logo is retained at
`krita_speech_bubble_generator/upstream_logo.png` for project history, not as
the current project's branding.
