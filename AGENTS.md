# Development guidance

## Project layout

- `krita_speech_bubble_generator/krita_speech_bubble_generator.py`: dock UI,
  saved settings, selection tracking and canvas editing.
- `bubble_geometry.py` and `bubble_preview.py` in the package: shared vector
  geometry and interactive preview.
- `canvas_context.py`: canvas transforms and background snapshots.
- `tests/test_bubbles.py`: Qt regression tests with a substitute Krita host.

## Compatibility and editing

The package and docker are named Krita Speech Bubble Generator, but saved
document identifiers deliberately retain the old names:

- Shape/group IDs: `rsbg-bubble` and `rsbg-bubble-<id>`.
- Document annotation prefix: `rsbg-bubble-`.

Do not rename these identifiers as part of branding changes. Preserve loading
of older settings, including missing-field defaults and the `Round` to
`Rounded` style mapping. Shared layers can contain multiple bubbles: update
only the targeted group and retain sibling artwork, stacking and transforms.

Use the same geometry for preview and export. Keep seeded patterns stable
during text and tail edits, and retain the text area and tail-length lock.

## Validation

Use the existing test suite with Python 3 and PyQt5:

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
```

The fake Krita host cannot establish native canvas repaint or persistence
behaviour. Do not describe these tests as application-level validation.
See [CONTRIBUTING.md](CONTRIBUTING.md) for manual Krita workflows.

## Documentation

Whenever a user-facing feature is added, removed or changed, update `README.md`
in the same change so its feature list and usage instructions stay accurate.

Keep implementation details and agent instructions out of the user-facing
README. Put contribution guidance in `CONTRIBUTING.md`. Retain upstream
attribution and the GPLv3 license.
