import ast
from importlib.util import resolve_name
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1] / "krita_speech_bubble_generator"
EXTERNAL_MODULES = {
    "__future__", "abc", "collections", "contextlib", "dataclasses", "importlib",
    "json", "math", "random", "re", "sys", "typing", "uuid", "xml", "PyQt5", "krita",
}


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                package = ".".join(path.parent.relative_to(PACKAGE.parent).parts)
                module = resolve_name("." * node.level + module, package)
            yield module
            for alias in node.names:
                yield module + "." + alias.name


class ArchitectureTests(unittest.TestCase):
    def test_no_new_third_party_imports(self):
        for path in PACKAGE.rglob("*.py"):
            for module in imports(path):
                with self.subTest(file=path.name, module=module):
                    self.assertIn(module.split(".")[0],
                                  EXTERNAL_MODULES | {PACKAGE.name})

    def test_presenter_depends_on_contracts_not_concrete_services(self):
        path = PACKAGE / "editor" / "presenter.py"
        forbidden = {
            PACKAGE.name + ".editor.view",
            PACKAGE.name + ".bubbles.renderer",
            PACKAGE.name + ".krita_host",
            PACKAGE.name + ".krita_speech_bubble_generator",
            "krita", "PyQt5.QtWidgets",
        }
        for module in imports(path):
            with self.subTest(module=module):
                self.assertFalse(any(module == name or module.startswith(name + ".")
                                     for name in forbidden))

    def test_native_host_imports_stay_at_the_boundary(self):
        allowed = {"__init__.py", "krita_speech_bubble_generator.py",
                   "krita_host/gateway.py"}
        for path in PACKAGE.rglob("*.py"):
            if path.relative_to(PACKAGE).as_posix() in allowed:
                continue
            with self.subTest(file=path.name):
                self.assertNotIn("krita", {name.split(".")[0]
                                          for name in imports(path)})

    def test_geometry_and_codec_do_not_import_editor_or_widgets(self):
        for path in (PACKAGE / "bubbles").rglob("*.py"):
            for module in imports(path):
                with self.subTest(file=path.name, module=module):
                    self.assertFalse(module.startswith("PyQt5.QtWidgets"))
                    self.assertFalse(module.startswith(PACKAGE.name + ".editor"))
                    self.assertFalse(module.startswith(PACKAGE.name + ".krita_host"))

    def test_docker_is_a_composition_and_lifecycle_shell(self):
        tree = ast.parse(
            (PACKAGE / "krita_speech_bubble_generator.py").read_text(
                encoding="utf-8"))
        docker = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef)
                      and node.name == "SpeechBubbleDocker")
        allowed = {"__init__", "canvasChanged", "showEvent", "hideEvent",
                   "closeEvent"}
        self.assertLessEqual(
            {node.name for node in docker.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))},
            allowed)

    def test_consumers_do_not_dispatch_on_saved_style_names(self):
        identifiers = {"Oval", "Rounded", "Square", "Tracing", "Sharp", "Thought", "Shouting",
                       "Balanced", "Angular", "Punchy", "Expressive"}
        for filename in ("bubbles/renderer.py", "editor/presenter.py",
                         "editor/view.py", "krita_host/gateway.py"):
            tree = ast.parse((PACKAGE / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    literals = {
                        value.value
                        for value in ast.walk(node)
                        if isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    }
                    with self.subTest(file=filename, line=node.lineno):
                        self.assertFalse(literals & identifiers)
