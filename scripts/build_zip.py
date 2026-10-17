#!/usr/bin/env python3
"""Build an installable Krita plugin ZIP using only the standard library."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent.parent
PLUGIN = "krita_speech_bubble_generator"


def build_zip(output: Path) -> Path:
    package = ROOT / PLUGIN
    files = [ROOT / f"{PLUGIN}.desktop", ROOT / "LICENSE"]
    files.extend(
        path
        for path in sorted(package.rglob("*"))
        if path.is_file()
        and not any(
            part.startswith(".") or part == "__pycache__"
            for part in path.relative_to(package).parts
        )
        and path.suffix not in {".pyc", ".pyo"}
    )
    if not (package / "__init__.py").is_file():
        raise FileNotFoundError(package / "__init__.py")
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    if output.resolve().is_relative_to(package.resolve()):
        raise ValueError("The output ZIP must be outside the plugin package.")

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        # Krita's importer discovers modules from explicit directory entries.
        archive.write(package, f"{PLUGIN}/")
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / f"{PLUGIN}.zip",
        help="Destination ZIP (default: dist/krita_speech_bubble_generator.zip).",
    )
    args = parser.parse_args()
    print(build_zip(args.output))


if __name__ == "__main__":
    main()
