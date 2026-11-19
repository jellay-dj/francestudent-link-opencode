import unittest

from model_catalog import (
    default_agent,
    openai_model_entry,
    resolve_agent,
)


MODELS = [
    {
        "id": 64,
        "name": "gpt-5.6-sol",
        "model": "gpt-5.6-sol",
        "modelProvider": "openai",
        "isActive": True,
        "isDefault": True,
    },
    {
        "id": -1001,
        "name": "GPT 6 Sol",
        "model": "gpt-6-sol",
        "modelProvider": "openai",
        "isActive": True,
        "isDefault": False,
    },
]


class ModelCatalogTests(unittest.TestCase):
    def test_resolves_canonical_display_and_numeric_ids(self):
        self.assertEqual(resolve_agent("gpt-6-sol", MODELS), -1001)
        self.assertEqual(resolve_agent("GPT 6 Sol", MODELS), -1001)
        self.assertEqual(resolve_agent("-1001", MODELS), -1001)

    def test_resolves_deprecated_alias(self):
        self.assertEqual(resolve_agent("gpt-5.5", MODELS), 64)

    def test_unknown_model_returns_none(self):
        self.assertIsNone(resolve_agent("not-a-model", MODELS))

    def test_default_and_openai_entry(self):
        self.assertEqual(default_agent(MODELS), 64)
        entry = openai_model_entry(MODELS[0])
        self.assertEqual(entry["id"], "gpt-5.6-sol")
        self.assertEqual(entry["fs_agent_id"], 64)
        self.assertIn("gpt-5.5", entry["aliases"])


if __name__ == "__main__":
    unittest.main()
