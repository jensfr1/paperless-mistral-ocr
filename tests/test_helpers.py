"""Tests for the framework-independent helpers."""

import pytest

from paperless_mistral_ocr.helpers import _mistral_pages_to_text
from paperless_mistral_ocr.helpers import strip_image_placeholders


class TestStripImagePlaceholders:
    def test_removes_markdown_image_reference(self):
        assert strip_image_placeholders("A ![img-0.jpeg](img-0.jpeg) B") == "A B"

    def test_removes_multiple_references(self):
        text = "![a](a.jpeg) middle ![b](b.jpeg)"
        assert strip_image_placeholders(text) == "middle"

    def test_keeps_regular_links(self):
        text = "see [the docs](https://example.org) for details"
        assert strip_image_placeholders(text) == text

    def test_collapses_blank_lines_left_behind(self):
        assert strip_image_placeholders("a\n\n\n\n![x](x.png)\n\n\nb") == "a\n\nb"

    @pytest.mark.parametrize("value", ["", None])
    def test_handles_empty_input(self, value):
        assert strip_image_placeholders(value) == ""


class TestMistralPagesToText:
    def test_joins_pages_with_blank_line(self):
        pages = [{"markdown": "one"}, {"markdown": "two"}]
        assert _mistral_pages_to_text(pages) == "one\n\ntwo"

    def test_drops_blank_pages(self):
        pages = [{"markdown": "one"}, {"markdown": "   "}, {"markdown": "two"}]
        assert _mistral_pages_to_text(pages) == "one\n\ntwo"

    def test_handles_missing_markdown_key(self):
        assert _mistral_pages_to_text([{}, {"markdown": "x"}]) == "x"

    def test_empty_page_list(self):
        assert _mistral_pages_to_text([]) == ""
