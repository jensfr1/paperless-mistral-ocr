"""Tests for reading the configuration from the environment."""

import pytest

from paperless_mistral_ocr.config import DEFAULT_SCORE
from paperless_mistral_ocr.config import MistralConfig

ALL_VARS = [
    "PAPERLESS_MISTRAL_OCR_API_KEY",
    "PAPERLESS_MISTRAL_OCR_ENDPOINT",
    "PAPERLESS_MISTRAL_OCR_MODEL",
    "PAPERLESS_MISTRAL_OCR_SCORE",
    "PAPERLESS_MISTRAL_OCR_PREPROCESS",
    "PAPERLESS_MISTRAL_OCR_FALLBACK",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ALL_VARS:
        monkeypatch.delenv(name, raising=False)


class TestValidity:
    def test_invalid_without_api_key(self):
        assert MistralConfig.from_env().is_valid() is False

    def test_valid_with_api_key(self, monkeypatch):
        monkeypatch.setenv("PAPERLESS_MISTRAL_OCR_API_KEY", "secret")
        assert MistralConfig.from_env().is_valid() is True

    def test_whitespace_only_key_is_invalid(self, monkeypatch):
        monkeypatch.setenv("PAPERLESS_MISTRAL_OCR_API_KEY", "   ")
        assert MistralConfig.from_env().is_valid() is False


class TestDefaults:
    def test_endpoint_and_model_have_defaults(self):
        config = MistralConfig.from_env()
        assert config.endpoint == "https://api.mistral.ai"
        assert config.model == "mistral-ocr-latest"

    def test_score_default(self):
        assert MistralConfig.from_env().score == DEFAULT_SCORE

    def test_preprocess_and_fallback_default_to_true(self):
        config = MistralConfig.from_env()
        assert config.preprocess is True
        assert config.fallback is True


class TestScore:
    def test_custom_score(self, monkeypatch):
        monkeypatch.setenv("PAPERLESS_MISTRAL_OCR_SCORE", "45")
        assert MistralConfig.from_env().score == 45

    def test_invalid_score_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("PAPERLESS_MISTRAL_OCR_SCORE", "not-a-number")
        assert MistralConfig.from_env().score == DEFAULT_SCORE


class TestBooleans:
    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off"])
    def test_falsy_spellings_disable(self, monkeypatch, value):
        monkeypatch.setenv("PAPERLESS_MISTRAL_OCR_PREPROCESS", value)
        assert MistralConfig.from_env().preprocess is False

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_truthy_spellings_enable(self, monkeypatch, value):
        monkeypatch.setenv("PAPERLESS_MISTRAL_OCR_FALLBACK", value)
        assert MistralConfig.from_env().fallback is True

    def test_unrecognised_value_keeps_default(self, monkeypatch):
        monkeypatch.setenv("PAPERLESS_MISTRAL_OCR_PREPROCESS", "vielleicht")
        assert MistralConfig.from_env().preprocess is True
