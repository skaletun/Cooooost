import importlib.util
from pathlib import Path
import tempfile
import unittest

script = Path(__file__).resolve().parents[1] / "scripts" / "cooooost.py"
spec = importlib.util.spec_from_file_location("cooooost", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class CheckpointTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as project:
            module.init(project)
            module.update(project, "Build skill", "Run tests")
            module.checkpoint(project)
            self.assertEqual(module.verify(project), 1)
            self.assertEqual(module.load(project)["goal"], "Build skill")

    def test_corruption(self):
        with tempfile.TemporaryDirectory() as project:
            module.init(project)
            path = module.checkpoint(project)
            record = path.read_text(encoding="utf-8")
            path.write_text(record.replace('"goal": ""', '"goal": "changed"'), encoding="utf-8")
            with self.assertRaises(ValueError):
                module.verify(project)

if __name__ == "__main__":
    unittest.main()
