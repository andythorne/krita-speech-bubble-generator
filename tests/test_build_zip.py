import configparser
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "build_zip", ROOT / "scripts" / "build_zip.py"
)
build_zip = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_zip)


class BuildZipTests(unittest.TestCase):
    def test_archive_supports_krita_plugin_discovery(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "dist" / "plugin.zip"
            build_zip.build_zip(output)
            with ZipFile(output) as archive:
                config = configparser.ConfigParser()
                config.read_string(
                    archive.read(f"{build_zip.PLUGIN}.desktop").decode("utf-8")
                )
                module = config["Desktop Entry"]["X-KDE-Library"]
                # Match Krita's get_source_module discovery requirements.
                directory = next(
                    name
                    for name in archive.namelist()
                    if name == f"{module}/" or name.endswith(f"/{module}/")
                )
                self.assertTrue(archive.getinfo(directory).is_dir())
                self.assertIn(f"{directory}__init__.py", archive.namelist())
                self.assertIn("LICENSE", archive.namelist())
                self.assertIsNone(archive.testzip())
                for name in archive.namelist():
                    self.assertNotIn("__pycache__", Path(name).parts)
                    self.assertFalse(name.endswith((".pyc", ".pyo")))
                    self.assertFalse(
                        any(part.startswith(".") for part in Path(name).parts)
                    )

    def test_rejects_output_inside_plugin_package(self):
        output = ROOT / build_zip.PLUGIN / "invalid.zip"
        with self.assertRaisesRegex(ValueError, "outside the plugin package"):
            build_zip.build_zip(output)


if __name__ == "__main__":
    unittest.main()
