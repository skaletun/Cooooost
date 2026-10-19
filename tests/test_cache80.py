import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("cache80", Path(__file__).resolve().parents[1] / "scripts" / "cache80.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class CacheTests(unittest.TestCase):
    def test_exact_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = mod.ExactCache(tmp)
            key = mod.key_for("api", "model", "instructions", [{"role":"user","content":"hello"}])
            cache.put(key, {"text":"hello"})
            self.assertEqual(cache.get(key), {"text":"hello"})

    def test_model_isolation(self):
        self.assertNotEqual(mod.key_for("api","a","","x"), mod.key_for("api","b","","x"))

    def test_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = mod.ExactCache(tmp, ttl=-1)
            key = mod.key_for("api","a","","x")
            cache.put(key, "answer")
            self.assertIsNone(cache.get(key))

    def test_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = mod.ExactCache(tmp)
            key = mod.key_for("api","a","","x")
            cache.put(key, "answer")
            path = cache._path(key)
            path.write_text(path.read_text().replace('"answer"', '"tampered"'))
            self.assertIsNone(cache.get(key))

    def test_lossless_context(self):
        chunks = ["Привет", "\\nWorld"]
        manifest = mod.context_manifest(chunks)
        self.assertEqual(mod.restore(chunks, manifest), "".join(chunks))
        with self.assertRaises(ValueError):
            mod.restore(["other", chunks[1]], manifest)

if __name__ == "__main__":
    unittest.main()
