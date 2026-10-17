"""Isolated imports protect host availability and one-time registration."""

from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BootstrapTests(unittest.TestCase):
    def run_script(self, script):
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=str(ROOT), env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hostless_package_model_renderer_and_gateway_import_without_registration(self):
        self.run_script("""
            import sys
            sys.modules["krita"] = None
            import krita_speech_bubble_generator as package
            from krita_speech_bubble_generator.bubbles.settings import BubbleSettings
            from krita_speech_bubble_generator.bubbles.renderer import BubbleRenderer
            from krita_speech_bubble_generator.krita_host.gateway import KritaGateway
            assert not hasattr(package, "SpeechBubbleDocker")
            assert "krita_speech_bubble_generator.krita_speech_bubble_generator" not in sys.modules
            from PyQt5.QtWidgets import QApplication
            app = QApplication([])
            assert BubbleRenderer().render(BubbleSettings()).svg.startswith("<svg")
            """)

    def test_packaged_subpackages_import_from_the_installable_zip(self):
        with TemporaryDirectory() as temporary:
            archive = str(Path(temporary) / "plugin.zip")
            builder = str(ROOT / "scripts" / "build_zip.py")
            self.run_script(f"""
                import importlib
                import pkgutil
                import runpy
                import sys
                sys.argv = [{builder!r}, "--output", {archive!r}]
                runpy.run_path({builder!r}, run_name="__main__")
                sys.modules["krita"] = None
                sys.path.insert(0, {archive!r})
                import krita_speech_bubble_generator as package
                assert package.__file__.startswith({archive!r})
                for name in ("bubbles", "editor", "krita_host"):
                    subpackage = importlib.import_module(package.__name__ + "." + name)
                    assert subpackage.__file__.startswith({archive!r})
                    modules = list(pkgutil.walk_packages(
                        subpackage.__path__, subpackage.__name__ + "."))
                    assert modules, name
                    for module in modules:
                        imported = importlib.import_module(module.name)
                        assert imported.__file__.startswith({archive!r}), module.name
                assert not hasattr(package, "SpeechBubbleDocker")
                """)

    def test_host_import_registers_existing_factory_exactly_once_even_on_package_reload(self):
        self.run_script("""
            import importlib
            import sys
            import types
            from PyQt5.QtWidgets import QDockWidget
            factories = []
            class Host:
                @classmethod
                def instance(cls):
                    return cls
                @classmethod
                def addDockWidgetFactory(cls, factory):
                    factories.append(factory)
            host = types.ModuleType("krita")
            host.Krita = Host
            host.DockWidget = QDockWidget
            host.DockWidgetFactory = lambda *args: args
            host.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=2)
            sys.modules["krita"] = host
            import krita_speech_bubble_generator as package
            from krita_speech_bubble_generator.krita_speech_bubble_generator import (
                SpeechBubbleDocker, register)
            importlib.reload(package)
            register()
            assert len(factories) == 1
            assert factories[0] == ("Krita Speech Bubble Generator", 2, SpeechBubbleDocker)
            assert package.SpeechBubbleDocker is SpeechBubbleDocker
            """)

    def test_missing_dependency_inside_host_is_not_misreported_as_hostless(self):
        self.run_script("""
            import importlib.abc
            import sys
            class BrokenHost(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "krita":
                        raise ModuleNotFoundError("Host dependency missing", name="native_dependency")
            sys.meta_path.insert(0, BrokenHost())
            try:
                import krita_speech_bubble_generator
            except ModuleNotFoundError as error:
                assert error.name == "native_dependency"
            else:
                raise AssertionError("Broken native host import was silently hidden")
            """)

    def test_missing_plugin_dependency_inside_host_is_not_hidden(self):
        self.run_script("""
            import importlib.abc
            import sys
            import types
            from PyQt5.QtWidgets import QDockWidget
            host = types.ModuleType("krita")
            host.Krita = object
            host.DockWidget = QDockWidget
            host.DockWidgetFactory = object
            host.DockWidgetFactoryBase = object
            sys.modules["krita"] = host
            class BrokenPlugin(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "krita_speech_bubble_generator.editor.presenter":
                        raise ModuleNotFoundError("Plugin dependency missing", name="plugin_dependency")
            sys.meta_path.insert(0, BrokenPlugin())
            try:
                import krita_speech_bubble_generator
            except ModuleNotFoundError as error:
                assert error.name == "plugin_dependency"
            else:
                raise AssertionError("Broken plugin import was silently hidden")
            """)
