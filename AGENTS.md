# Development guidance

## Project layout

- `krita_speech_bubble_generator/krita_speech_bubble_generator.py`: thin docker
  composition and lifecycle shell.
- `bubbles/`: immutable settings/codec, polymorphic bubble types, composed
  shouting strategies, registries, geometry primitives, and shared rendering.
- `editor/`: UI, orchestration, service contracts, session values, interactive
  preview, and local input helpers.
- `krita_host/`: native document operations, selection resolution, canvas
  transforms, and background snapshots.
- `tests/`: contract, geometry, service, UI, and fake-host workflow coverage.

## Architectural constraints

Program to interfaces, use polymorphism for interchangeable behavior, and compose
collaborators at bootstrap. Use `BubbleType` subclasses and compose a
`ShoutingAlgorithm` into `ShoutingBubble`. Do not bypass these interfaces with
concrete-type or style-name dispatch elsewhere. Keep shared mechanics DRY.

Add no dependencies of any kind: runtime, development, tests, build, packaging,
or CI. Use only the standard library and existing PyQt5/Krita APIs. Do not upgrade
packages, vendor libraries, or raise the minimum Python version.

See `CONTRIBUTING.md` for module ownership and extension guidance.

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
