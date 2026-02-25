"""Tests for decay configuration loading."""

import pytest
import os
import json
import tempfile
from pathlib import Path

from remind.config import load_config, RemindConfig, CONFIG_FILE, REMIND_DIR


class TestDecayConfigDefaults:
    """Test that decay config defaults are correct."""

    def test_default_decay_enabled(self):
        """Default decay_enabled should be True."""
        config = RemindConfig()
        assert config.decay_enabled is True

    def test_default_decay_threshold(self):
        """Default decay_threshold should be 10."""
        config = RemindConfig()
        assert config.decay_threshold == 10

    def test_default_decay_rate(self):
        """Default decay_rate should be 0.95."""
        config = RemindConfig()
        assert config.decay_rate == 0.95


class TestDecayConfigFromFile:
    """Test that decay config loads correctly from config file."""

    def test_config_file_override_decay_enabled(self, tmp_path):
        """Config file should override decay_enabled."""
        config_file = tmp_path / "remind.config.json"
        config_file.write_text(json.dumps({
            "decay_enabled": False
        }))

        # Temporarily replace CONFIG_FILE
        original_config_file = CONFIG_FILE
        import remind.config
        remind.config.CONFIG_FILE = config_file
        remind.config.REMIND_DIR = tmp_path

        try:
            config = load_config()
            assert config.decay_enabled is False
        finally:
            remind.config.CONFIG_FILE = original_config_file
            remind.config.REMIND_DIR = REMIND_DIR

    def test_config_file_override_decay_threshold(self, tmp_path):
        """Config file should override decay_threshold."""
        config_file = tmp_path / "remind.config.json"
        config_file.write_text(json.dumps({
            "decay_threshold": 20
        }))

        original_config_file = CONFIG_FILE
        import remind.config
        remind.config.CONFIG_FILE = config_file
        remind.config.REMIND_DIR = tmp_path

        try:
            config = load_config()
            assert config.decay_threshold == 20
        finally:
            remind.config.CONFIG_FILE = original_config_file
            remind.config.REMIND_DIR = REMIND_DIR

    def test_config_file_override_decay_rate(self, tmp_path):
        """Config file should override decay_rate."""
        config_file = tmp_path / "remind.config.json"
        config_file.write_text(json.dumps({
            "decay_rate": 0.90
        }))

        original_config_file = CONFIG_FILE
        import remind.config
        remind.config.CONFIG_FILE = config_file
        remind.config.REMIND_DIR = tmp_path

        try:
            config = load_config()
            assert config.decay_rate == 0.90
        finally:
            remind.config.CONFIG_FILE = original_config_file
            remind.config.REMIND_DIR = REMIND_DIR

    def test_config_file_override_all_decay_settings(self, tmp_path):
        """Config file should override all decay settings at once."""
        config_file = tmp_path / "remind.config.json"
        config_file.write_text(json.dumps({
            "decay_enabled": False,
            "decay_threshold": 25,
            "decay_rate": 0.92
        }))

        original_config_file = CONFIG_FILE
        import remind.config
        remind.config.CONFIG_FILE = config_file
        remind.config.REMIND_DIR = tmp_path

        try:
            config = load_config()
            assert config.decay_enabled is False
            assert config.decay_threshold == 25
            assert config.decay_rate == 0.92
        finally:
            remind.config.CONFIG_FILE = original_config_file
            remind.config.REMIND_DIR = REMIND_DIR


class TestDecayConfigFromEnv:
    """Test that decay config loads correctly from environment variables."""

    def test_env_override_decay_enabled(self, monkeypatch):
        """Environment variable should override decay_enabled."""
        monkeypatch.setenv("DECAY_ENABLED", "false")
        config = load_config()
        assert config.decay_enabled is False

    def test_env_override_decay_enabled_true(self, monkeypatch):
        """Environment variable DECAY_ENABLED=true should enable decay."""
        monkeypatch.setenv("DECAY_ENABLED", "true")
        config = load_config()
        assert config.decay_enabled is True

    def test_env_override_decay_enabled_1(self, monkeypatch):
        """Environment variable DECAY_ENABLED=1 should enable decay."""
        monkeypatch.setenv("DECAY_ENABLED", "1")
        config = load_config()
        assert config.decay_enabled is True

    def test_env_override_decay_threshold(self, monkeypatch):
        """Environment variable should override decay_threshold."""
        monkeypatch.setenv("DECAY_THRESHOLD", "15")
        config = load_config()
        assert config.decay_threshold == 15

    def test_env_override_decay_rate(self, monkeypatch):
        """Environment variable should override decay_rate."""
        monkeypatch.setenv("DECAY_RATE", "0.88")
        config = load_config()
        assert config.decay_rate == 0.88

    def test_env_override_all_decay_settings(self, monkeypatch):
        """Environment variables should override all decay settings."""
        monkeypatch.setenv("DECAY_ENABLED", "false")
        monkeypatch.setenv("DECAY_THRESHOLD", "30")
        monkeypatch.setenv("DECAY_RATE", "0.99")
        config = load_config()
        assert config.decay_enabled is False
        assert config.decay_threshold == 30
        assert config.decay_rate == 0.99


class TestDecayConfigPriority:
    """Test that config priority is correct: env > file > defaults."""

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        """Environment variables should override config file settings."""
        config_file = tmp_path / "remind.config.json"
        config_file.write_text(json.dumps({
            "decay_enabled": False,
            "decay_threshold": 20,
            "decay_rate": 0.90
        }))

        original_config_file = CONFIG_FILE
        import remind.config
        remind.config.CONFIG_FILE = config_file
        remind.config.REMIND_DIR = tmp_path

        try:
            # Env vars should win over config file
            monkeypatch.setenv("DECAY_ENABLED", "true")
            monkeypatch.setenv("DECAY_THRESHOLD", "50")
            monkeypatch.setenv("DECAY_RATE", "0.99")

            config = load_config()
            assert config.decay_enabled is True
            assert config.decay_threshold == 50
            assert config.decay_rate == 0.99
        finally:
            remind.config.CONFIG_FILE = original_config_file
            remind.config.REMIND_DIR = REMIND_DIR

    def test_file_overrides_defaults(self, tmp_path):
        """Config file should override defaults."""
        config_file = tmp_path / "remind.config.json"
        config_file.write_text(json.dumps({
            "decay_enabled": False
        }))

        original_config_file = CONFIG_FILE
        import remind.config
        remind.config.CONFIG_FILE = config_file
        remind.config.REMIND_DIR = tmp_path

        try:
            config = load_config()
            assert config.decay_enabled is False
            # Other settings should remain at defaults
            assert config.decay_threshold == 10
            assert config.decay_rate == 0.95
        finally:
            remind.config.CONFIG_FILE = original_config_file
            remind.config.REMIND_DIR = REMIND_DIR

    def test_partial_env_override(self, tmp_path, monkeypatch):
        """Only env vars set should override; others from file."""
        config_file = tmp_path / "remind.config.json"
        config_file.write_text(json.dumps({
            "decay_enabled": False,
            "decay_threshold": 20,
            "decay_rate": 0.90
        }))

        original_config_file = CONFIG_FILE
        import remind.config
        remind.config.CONFIG_FILE = config_file
        remind.config.REMIND_DIR = tmp_path

        try:
            # Only override decay_enabled via env
            monkeypatch.setenv("DECAY_ENABLED", "true")

            config = load_config()
            assert config.decay_enabled is True  # From env
            assert config.decay_threshold == 20  # From file
            assert config.decay_rate == 0.90     # From file
        finally:
            remind.config.CONFIG_FILE = original_config_file
            remind.config.REMIND_DIR = REMIND_DIR