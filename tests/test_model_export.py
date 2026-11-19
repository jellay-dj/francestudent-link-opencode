import unittest
import json
import tempfile
from pathlib import Path

from unittest.mock import patch

from scripts.export_opencode_config import (
    MODEL_CATALOG_TIMEOUT_SECONDS,
    OPENCODE_CHUNK_TIMEOUT_MS,
    OPENCODE_HEADER_TIMEOUT_MS,
    OPENCODE_REQUEST_TIMEOUT_MS,
    apply_config,
    build_config,
    load_models,
)


class ModelExportTests(unittest.TestCase):
    def test_config_uses_canonical_ids_and_absolute_session_plugin(self):
        models = {
            "gpt-6-astra": {
                "modelID": "gpt-6-astra",
                "name": "GPT 6 Astra",
                "capabilities": {
                    "tools": True,
                    "input": ["text"],
                    "output": ["text"],
                },
            }
        }
        config = build_config("http://127.0.0.1:8765", models, "plugins/session")
        provider = config["providers"]["france-student"]
        self.assertIn("gpt-6-astra", provider["models"])
        self.assertEqual(provider["models"]["gpt-6-astra"]["modelID"], "gpt-6-astra")
        self.assertEqual(provider["models"]["gpt-6-astra"]["name"], "GPT 6 Astra")
        self.assertEqual(provider["settings"]["baseURL"], "http://127.0.0.1:8765/v1")
        self.assertEqual(provider["settings"]["headerTimeout"], 20 * 60 * 1000)
        self.assertEqual(provider["settings"]["chunkTimeout"], 20 * 60 * 1000)
        self.assertEqual(provider["settings"]["timeout"], 30 * 60 * 1000)
        self.assertTrue(Path(config["plugins"][0]).is_absolute())

    def test_catalog_fetch_timeout_allows_slow_bridge(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"data":[{"id":"gpt-6-astra","fs_name":"GPT 6 Astra"}]}'

        with patch("scripts.export_opencode_config.urlopen", return_value=FakeResponse()) as request:
            result = load_models("http://127.0.0.1:8765")

        self.assertIn("gpt-6-astra", result)
        self.assertEqual(request.call_args.kwargs["timeout"], MODEL_CATALOG_TIMEOUT_SECONDS)
        self.assertGreater(MODEL_CATALOG_TIMEOUT_SECONDS, 10)

    def test_config_refuses_empty_catalog(self):
        with self.assertRaisesRegex(RuntimeError, "no active models"):
            build_config("http://127.0.0.1:8765", {}, "plugins/session")

    def test_apply_replaces_only_fs_provider_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "opencode.json"
            original = {
                "model": "openai/keep-me",
                "mcp": {"local": {"enabled": True}},
                "plugins": ["other-plugin"],
                "providers": {
                    "other": {"name": "Other"},
                    "france-student": {"models": {"retired-model": {}}},
                },
            }
            target.write_text(json.dumps(original), encoding="utf-8")
            generated = build_config(
                "http://127.0.0.1:8765",
                {"new-model": {"modelID": "new-model", "name": "New model"}},
                temporary_directory,
            )

            apply_config(target, generated)
            updated = json.loads(target.read_text(encoding="utf-8"))

            self.assertEqual(updated["model"], "openai/keep-me")
            self.assertEqual(updated["mcp"], original["mcp"])
            self.assertEqual(updated["providers"]["other"], original["providers"]["other"])
            self.assertEqual(list(updated["providers"]["france-student"]["models"]), ["new-model"])
            self.assertEqual(updated["plugins"][0], "other-plugin")
            self.assertEqual(updated["plugins"][1], generated["plugins"][0])


if __name__ == "__main__":
    unittest.main()
