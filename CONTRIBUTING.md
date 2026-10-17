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

### Try changes in Krita

Exercise the affected workflow in a `.kra` document. For bubble editing changes,
include adding a bubble, selecting and editing it, switching between bubbles,
and saving and reopening the document. Check automatic updates and selection
changes, and ensure updates do not move the bubble or alter neighbouring artwork.

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
