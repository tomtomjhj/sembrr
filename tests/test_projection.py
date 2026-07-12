from __future__ import annotations

import unittest

from spacy.lang.en import English

from sembrr.protect import inspect_inline


class ProjectionTests(unittest.TestCase):
    def test_projects_each_markdown_atom_as_one_nlp_token(self) -> None:
        projected = inspect_inline("Use `value` with [the guide](guide.md).").projected
        tokens = English().make_doc(projected.text)

        self.assertEqual(
            len([token for token in tokens if token.text.startswith("SEMBRRATOM")]),
            2,
        )

    def test_projected_atom_does_not_absorb_sentence_punctuation(self) -> None:
        projected = inspect_inline("Write to `M`. Next sentence.").projected
        tokens = English().make_doc(projected.text)
        atom = next(
            index for index, token in enumerate(tokens) if token.text.startswith("SEMBRRATOM")
        )

        self.assertEqual(tokens[atom + 1].text, ".")


if __name__ == "__main__":
    unittest.main()
