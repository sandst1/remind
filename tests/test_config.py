"""Tests for configuration management."""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from remind.config import (
    RemindConfig,
    AnthropicConfig,
    OpenAIConfig,
    AzureOpenAIConfig,
    OllamaConfig,
    DecayConfig,
    load_config,
    normalize_cli_output_mode,
    _apply_file_config,
    _apply_env_vars,
    _load_config_file,
    resolve_db_path,
    infer_project_dir_from_db_url,
    REMIND_DIR,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_CONSOLIDATION_THRESHOLD,
    DEFAULT_CONCEPTS_PER_PASS,
)


# All env vars the config system reads, used to ensure clean test isolation
from remind.config import DEFAULT_EPISODE_TYPES

_ALL_CONFIG_ENV_VARS = [
    "LLM_PROVIDER",
    "EMBEDDING_PROVIDER",
    "CONSOLIDATION_THRESHOLD",
    "CONCEPTS_PER_PASS",
    "CONSOLIDATION_CONCEPTS_PER_PASS",
    "EXTRACTION_BATCH_SIZE",
    "EXTRACTION_LLM_BATCH_SIZE",
    "AUTO_CONSOLIDATE",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_INGEST_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_INGEST_MODEL",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_API_BASE_URL",
    "AZURE_OPENAI_DEPLOYMENT_NAME",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME",
    "AZURE_OPENAI_EMBEDDING_SIZE",
    "AZURE_OPENAI_INGEST_DEPLOYMENT_NAME",
    "OLLAMA_URL",
    "OLLAMA_LLM_MODEL",
    "OLLAMA_EMBEDDING_MODEL",
    "OLLAMA_INGEST_MODEL",
    "INGEST_BUFFER_SIZE",
    "INGEST_MIN_DENSITY",
    "REMIND_DECAY_ENABLED",
    "REMIND_DECAY_INTERVAL",
    "REMIND_DECAY_RATE",
    "REMIND_LOGGING_ENABLED",
    "REMIND_CLI_RECALL_WORKER_ENABLED",
    "REMIND_CLI_RECALL_WORKER_IDLE_SECONDS",
    "REMIND_CLI_OUTPUT_MODE",
    "REMIND_EPISODE_TYPES",
    "ENTITY_EXTRACTION_BATCH_SIZE",
    "LLM_CONCURRENCY",
    "CONSOLIDATION_LLM_CONCURRENCY",
]


@pytest.fixture(autouse=True)
def clean_env():
    """Remove all config-related env vars before and after each test."""
    saved = {}
    for var in _ALL_CONFIG_ENV_VARS:
        saved[var] = os.environ.pop(var, None)
    yield
    for var in _ALL_CONFIG_ENV_VARS:
        os.environ.pop(var, None)
        if saved[var] is not None:
            os.environ[var] = saved[var]


# =========================================================================
# Defaults
# =========================================================================


class TestDefaults:
    def test_remind_config_defaults(self):
        config = RemindConfig()
        assert config.llm_provider == "anthropic"
        assert config.embedding_provider == "openai"
        assert config.consolidation_threshold == 5
        assert config.concepts_per_pass == 64
        assert config.auto_consolidate is True
        assert config.extraction_batch_size == 50
        assert config.extraction_llm_batch_size == 10
        assert config.consolidation_batch_size == 25
        assert config.llm_concurrency == 3
        assert config.ingest_buffer_size == 4000
        assert config.cli_recall_worker_enabled is True
        assert config.cli_recall_worker_idle_seconds == 600
        assert config.logging_enabled is False

    def test_anthropic_defaults(self):
        c = AnthropicConfig()
        assert c.api_key is None
        assert c.model == "claude-sonnet-4-20250514"
        assert c.ingest_model is None

    def test_openai_defaults(self):
        c = OpenAIConfig()
        assert c.api_key is None
        assert c.base_url is None
        assert c.model == "gpt-4.1"
        assert c.embedding_model == "text-embedding-3-small"
        assert c.ingest_model is None

    def test_azure_openai_defaults(self):
        c = AzureOpenAIConfig()
        assert c.api_key is None
        assert c.base_url is None
        assert c.deployment_name is None
        assert c.embedding_deployment_name is None
        assert c.embedding_size == 1536
        assert c.ingest_deployment_name is None

    def test_ollama_defaults(self):
        c = OllamaConfig()
        assert c.url == "http://localhost:11434"
        assert c.llm_model == "llama3.2"
        assert c.embedding_model == "nomic-embed-text"
        assert c.ingest_model is None

    def test_decay_defaults(self):
        c = DecayConfig()
        assert c.enabled is True
        assert c.decay_interval == 20
        assert c.decay_rate == 0.1

    def test_episode_types_defaults(self):
        config = RemindConfig()
        assert config.episode_types == DEFAULT_EPISODE_TYPES
        assert "observation" in config.episode_types
        assert "outcome" in config.episode_types
        assert "fact" in config.episode_types

    def test_load_config_returns_defaults_when_no_files_or_env(self):
        with patch("remind.config.CONFIG_FILE", Path("/nonexistent/path/config.json")):
            config = load_config()
        assert config.llm_provider == DEFAULT_LLM_PROVIDER
        assert config.embedding_provider == DEFAULT_EMBEDDING_PROVIDER
        assert config.consolidation_threshold == DEFAULT_CONSOLIDATION_THRESHOLD


# =========================================================================
# CLI output mode
# =========================================================================


class TestNormalizeCliOutputMode:
    def test_valid_values(self):
        assert normalize_cli_output_mode("table") == "table"
        assert normalize_cli_output_mode("JSON") == "json"
        assert normalize_cli_output_mode("compact-json") == "compact-json"
        assert normalize_cli_output_mode("COMPACT_JSON") == "compact-json"
        assert normalize_cli_output_mode("compactjson") == "compact-json"

    def test_invalid_falls_back_to_table(self):
        assert normalize_cli_output_mode("wide") == "table"
        assert normalize_cli_output_mode("") == "table"


# =========================================================================
# _apply_file_config
# =========================================================================


class TestApplyFileConfig:
    def test_applies_top_level_fields(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "llm_provider": "openai",
            "embedding_provider": "ollama",
            "consolidation_threshold": 10,
            "concepts_per_pass": 128,
            "auto_consolidate": False,
            "ingest_buffer_size": 8000,
            "cli_recall_worker_enabled": False,
            "cli_recall_worker_idle_seconds": 120,
            "logging_enabled": True,
        })
        assert config.llm_provider == "openai"
        assert config.embedding_provider == "ollama"
        assert config.consolidation_threshold == 10
        assert config.concepts_per_pass == 128
        assert config.auto_consolidate is False
        assert config.ingest_buffer_size == 8000
        assert config.cli_recall_worker_enabled is False
        assert config.cli_recall_worker_idle_seconds == 120
        assert config.logging_enabled is True

    def test_applies_cli_output_mode_and_alias(self):
        config = RemindConfig()
        _apply_file_config(config, {"cli_output_mode": "json"})
        assert config.cli_output_mode == "json"
        config = RemindConfig()
        _apply_file_config(config, {"cliOutputMode": "JSON"})
        assert config.cli_output_mode == "json"
        config = RemindConfig()
        _apply_file_config(config, {"compactJson": "compact-json"})
        assert config.cli_output_mode == "compact-json"

    def test_partial_config_preserves_unset_fields(self):
        config = RemindConfig()
        _apply_file_config(config, {"llm_provider": "ollama"})
        assert config.llm_provider == "ollama"
        assert config.embedding_provider == DEFAULT_EMBEDDING_PROVIDER
        assert config.consolidation_threshold == DEFAULT_CONSOLIDATION_THRESHOLD

    def test_applies_anthropic_provider_config(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "anthropic": {
                "api_key": "sk-ant-test",
                "model": "claude-opus-5",
                "ingest_model": "claude-haiku-4",
            }
        })
        assert config.anthropic.api_key == "sk-ant-test"
        assert config.anthropic.model == "claude-opus-5"
        assert config.anthropic.ingest_model == "claude-haiku-4"

    def test_applies_openai_provider_config(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "openai": {
                "api_key": "sk-test",
                "base_url": "https://custom.api.com",
                "model": "gpt-5",
                "embedding_model": "text-embedding-4",
                "ingest_model": "gpt-4.1-mini",
            }
        })
        assert config.openai.api_key == "sk-test"
        assert config.openai.base_url == "https://custom.api.com"
        assert config.openai.model == "gpt-5"
        assert config.openai.embedding_model == "text-embedding-4"
        assert config.openai.ingest_model == "gpt-4.1-mini"

    def test_applies_azure_openai_provider_config(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "azure_openai": {
                "api_key": "az-key",
                "base_url": "https://myresource.openai.azure.com",
                "deployment_name": "gpt-4-deploy",
                "embedding_deployment_name": "embed-deploy",
                "embedding_size": 3072,
                "ingest_deployment_name": "ingest-deploy",
            }
        })
        assert config.azure_openai.api_key == "az-key"
        assert config.azure_openai.base_url == "https://myresource.openai.azure.com"
        assert config.azure_openai.deployment_name == "gpt-4-deploy"
        assert config.azure_openai.embedding_deployment_name == "embed-deploy"
        assert config.azure_openai.embedding_size == 3072
        assert config.azure_openai.ingest_deployment_name == "ingest-deploy"

    def test_applies_ollama_provider_config(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "ollama": {
                "url": "http://gpu-box:11434",
                "llm_model": "deepseek-v3",
                "embedding_model": "mxbai-embed-large",
                "ingest_model": "llama3.2:1b",
            }
        })
        assert config.ollama.url == "http://gpu-box:11434"
        assert config.ollama.llm_model == "deepseek-v3"
        assert config.ollama.embedding_model == "mxbai-embed-large"
        assert config.ollama.ingest_model == "llama3.2:1b"

    def test_applies_decay_config(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "decay": {
                "enabled": False,
                "decay_interval": 50,
                "decay_rate": 0.05,
            }
        })
        assert config.decay.enabled is False
        assert config.decay.decay_interval == 50
        assert config.decay.decay_rate == 0.05

    def test_partial_decay_preserves_unset(self):
        config = RemindConfig()
        _apply_file_config(config, {"decay": {"decay_rate": 0.2}})
        assert config.decay.enabled is True
        assert config.decay.decay_interval == 20
        assert config.decay.decay_rate == 0.2

    def test_applies_consolidation_parallelism_fields(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "extraction_batch_size": 40,
            "extraction_llm_batch_size": 5,
            "consolidation_batch_size": 50,
            "llm_concurrency": 4,
        })
        assert config.extraction_batch_size == 40
        assert config.extraction_llm_batch_size == 5
        assert config.consolidation_batch_size == 50
        assert config.llm_concurrency == 4

    def test_applies_consolidation_workers_legacy_key(self):
        config = RemindConfig()
        _apply_file_config(config, {"consolidation_workers": 4})
        assert config.llm_concurrency == 4

    def test_applies_episode_types(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "episode_types": ["observation", "decision", "custom_type"]
        })
        assert config.episode_types == ["observation", "decision", "custom_type"]

    def test_episode_types_normalizes_case(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "episode_types": ["OBSERVATION", "Custom_Type", "  fact  "]
        })
        assert config.episode_types == ["observation", "custom_type", "fact"]

    def test_episode_types_not_set_preserves_defaults(self):
        config = RemindConfig()
        _apply_file_config(config, {"llm_provider": "openai"})
        assert config.episode_types == DEFAULT_EPISODE_TYPES

    def test_provider_overlay_preserves_unset_fields(self):
        """Setting one provider field shouldn't clobber others."""
        config = RemindConfig()
        config.openai.api_key = "existing-key"
        _apply_file_config(config, {"openai": {"model": "gpt-5"}})
        assert config.openai.model == "gpt-5"
        assert config.openai.api_key == "existing-key"

    def test_layering_two_configs(self):
        """Calling _apply_file_config twice simulates global + project-local."""
        config = RemindConfig()

        # Global config sets provider and API key
        _apply_file_config(config, {
            "llm_provider": "anthropic",
            "anthropic": {"api_key": "global-key", "model": "claude-sonnet-4-20250514"},
            "openai": {"api_key": "openai-global"},
        })
        assert config.llm_provider == "anthropic"
        assert config.anthropic.api_key == "global-key"
        assert config.anthropic.model == "claude-sonnet-4-20250514"

        # Project-local overrides provider and model, but API key remains
        _apply_file_config(config, {
            "llm_provider": "openai",
            "anthropic": {"model": "claude-opus-5"},
        })
        assert config.llm_provider == "openai"
        assert config.anthropic.model == "claude-opus-5"
        assert config.anthropic.api_key == "global-key"
        assert config.openai.api_key == "openai-global"


# =========================================================================
# _load_config_file
# =========================================================================


class TestLoadConfigFile:
    def test_returns_none_for_missing_file(self):
        assert _load_config_file(Path("/nonexistent/file.json")) is None

    def test_loads_valid_json(self, tmp_path):
        cfg_file = tmp_path / "test.json"
        cfg_file.write_text('{"llm_provider": "openai"}')
        result = _load_config_file(cfg_file)
        assert result == {"llm_provider": "openai"}

    def test_returns_none_for_invalid_json(self, tmp_path):
        cfg_file = tmp_path / "bad.json"
        cfg_file.write_text("not valid json {{{")
        assert _load_config_file(cfg_file) is None


# =========================================================================
# Environment variable overrides
# =========================================================================


class TestEnvVarOverrides:
    """Verify every config-file field has a working env var counterpart."""

    def _config_with_env(self, **env_vars):
        for k, v in env_vars.items():
            os.environ[k] = v
        config = RemindConfig()
        _apply_env_vars(config)
        return config

    # -- Top-level --

    def test_llm_provider(self):
        c = self._config_with_env(LLM_PROVIDER="ollama")
        assert c.llm_provider == "ollama"

    def test_embedding_provider(self):
        c = self._config_with_env(EMBEDDING_PROVIDER="azure_openai")
        assert c.embedding_provider == "azure_openai"

    def test_consolidation_threshold(self):
        c = self._config_with_env(CONSOLIDATION_THRESHOLD="20")
        assert c.consolidation_threshold == 20

    def test_consolidation_threshold_invalid(self):
        c = self._config_with_env(CONSOLIDATION_THRESHOLD="abc")
        assert c.consolidation_threshold == DEFAULT_CONSOLIDATION_THRESHOLD

    def test_concepts_per_pass(self):
        c = self._config_with_env(CONCEPTS_PER_PASS="32")
        assert c.concepts_per_pass == 32

    def test_consolidation_concepts_per_pass_legacy_env(self):
        c = self._config_with_env(CONSOLIDATION_CONCEPTS_PER_PASS="31")
        assert c.concepts_per_pass == 31

    def test_auto_consolidate_true(self):
        for val in ("true", "True", "1", "yes"):
            c = self._config_with_env(AUTO_CONSOLIDATE=val)
            assert c.auto_consolidate is True, f"Failed for {val}"

    def test_auto_consolidate_false(self):
        for val in ("false", "0", "no", "anything"):
            c = self._config_with_env(AUTO_CONSOLIDATE=val)
            assert c.auto_consolidate is False, f"Failed for {val}"

    def test_ingest_buffer_size(self):
        c = self._config_with_env(INGEST_BUFFER_SIZE="8000")
        assert c.ingest_buffer_size == 8000

    def test_logging_enabled(self):
        c = self._config_with_env(REMIND_LOGGING_ENABLED="true")
        assert c.logging_enabled is True

    def test_cli_recall_worker_enabled(self):
        c = self._config_with_env(REMIND_CLI_RECALL_WORKER_ENABLED="false")
        assert c.cli_recall_worker_enabled is False

    def test_cli_recall_worker_idle_seconds(self):
        c = self._config_with_env(REMIND_CLI_RECALL_WORKER_IDLE_SECONDS="180")
        assert c.cli_recall_worker_idle_seconds == 180

    def test_extraction_batch_size(self):
        c = self._config_with_env(EXTRACTION_BATCH_SIZE="60")
        assert c.extraction_batch_size == 60

    def test_extraction_llm_batch_size(self):
        c = self._config_with_env(EXTRACTION_LLM_BATCH_SIZE="12")
        assert c.extraction_llm_batch_size == 12

    def test_entity_extraction_batch_size_legacy_env(self):
        c = self._config_with_env(ENTITY_EXTRACTION_BATCH_SIZE="11")
        assert c.extraction_llm_batch_size == 11

    def test_extraction_llm_batch_size_invalid(self):
        c = self._config_with_env(EXTRACTION_LLM_BATCH_SIZE="abc")
        assert c.extraction_llm_batch_size == 10  # unchanged default

    def test_consolidation_batch_size(self):
        c = self._config_with_env(CONSOLIDATION_BATCH_SIZE="50")
        assert c.consolidation_batch_size == 50

    def test_consolidation_batch_size_invalid(self):
        c = self._config_with_env(CONSOLIDATION_BATCH_SIZE="abc")
        assert c.consolidation_batch_size == 25  # unchanged default

    def test_llm_concurrency(self):
        c = self._config_with_env(LLM_CONCURRENCY="4")
        assert c.llm_concurrency == 4

    def test_consolidation_llm_concurrency_legacy_env(self):
        c = self._config_with_env(CONSOLIDATION_LLM_CONCURRENCY="5")
        assert c.llm_concurrency == 5

    def test_llm_concurrency_invalid(self):
        c = self._config_with_env(LLM_CONCURRENCY="abc")
        assert c.llm_concurrency == 3  # unchanged default

    # -- Episode types --

    def test_episode_types_from_env(self):
        c = self._config_with_env(REMIND_EPISODE_TYPES="observation,decision,custom")
        assert c.episode_types == ["observation", "decision", "custom"]

    def test_episode_types_env_trims_whitespace(self):
        c = self._config_with_env(REMIND_EPISODE_TYPES=" fact , custom_type ,  decision ")
        assert c.episode_types == ["fact", "custom_type", "decision"]

    def test_episode_types_env_empty_preserves_defaults(self):
        c = self._config_with_env(REMIND_EPISODE_TYPES="")
        assert c.episode_types == DEFAULT_EPISODE_TYPES

    # -- Anthropic --

    def test_anthropic_api_key(self):
        c = self._config_with_env(ANTHROPIC_API_KEY="sk-ant-test123")
        assert c.anthropic.api_key == "sk-ant-test123"

    def test_anthropic_model(self):
        c = self._config_with_env(ANTHROPIC_MODEL="claude-opus-5")
        assert c.anthropic.model == "claude-opus-5"

    def test_anthropic_ingest_model(self):
        c = self._config_with_env(ANTHROPIC_INGEST_MODEL="claude-haiku-4")
        assert c.anthropic.ingest_model == "claude-haiku-4"

    # -- OpenAI --

    def test_openai_api_key(self):
        c = self._config_with_env(OPENAI_API_KEY="sk-test")
        assert c.openai.api_key == "sk-test"

    def test_openai_base_url(self):
        c = self._config_with_env(OPENAI_BASE_URL="https://custom.openai.com")
        assert c.openai.base_url == "https://custom.openai.com"

    def test_openai_model(self):
        c = self._config_with_env(OPENAI_MODEL="gpt-5")
        assert c.openai.model == "gpt-5"

    def test_openai_embedding_model(self):
        c = self._config_with_env(OPENAI_EMBEDDING_MODEL="text-embedding-4")
        assert c.openai.embedding_model == "text-embedding-4"

    def test_openai_ingest_model(self):
        c = self._config_with_env(OPENAI_INGEST_MODEL="gpt-4.1-mini")
        assert c.openai.ingest_model == "gpt-4.1-mini"

    # -- Azure OpenAI --

    def test_azure_api_key(self):
        c = self._config_with_env(AZURE_OPENAI_API_KEY="az-key")
        assert c.azure_openai.api_key == "az-key"

    def test_azure_base_url(self):
        c = self._config_with_env(AZURE_OPENAI_API_BASE_URL="https://myresource.openai.azure.com")
        assert c.azure_openai.base_url == "https://myresource.openai.azure.com"

    def test_azure_deployment_name(self):
        c = self._config_with_env(AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4-deploy")
        assert c.azure_openai.deployment_name == "gpt-4-deploy"

    def test_azure_embedding_deployment_name(self):
        c = self._config_with_env(AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME="embed-deploy")
        assert c.azure_openai.embedding_deployment_name == "embed-deploy"

    def test_azure_embedding_size(self):
        c = self._config_with_env(AZURE_OPENAI_EMBEDDING_SIZE="3072")
        assert c.azure_openai.embedding_size == 3072

    def test_azure_embedding_size_invalid(self):
        c = self._config_with_env(AZURE_OPENAI_EMBEDDING_SIZE="not_a_number")
        assert c.azure_openai.embedding_size == 1536  # unchanged default

    def test_azure_ingest_deployment_name(self):
        c = self._config_with_env(AZURE_OPENAI_INGEST_DEPLOYMENT_NAME="ingest-deploy")
        assert c.azure_openai.ingest_deployment_name == "ingest-deploy"

    # -- Ollama --

    def test_ollama_url(self):
        c = self._config_with_env(OLLAMA_URL="http://gpu:11434")
        assert c.ollama.url == "http://gpu:11434"

    def test_ollama_llm_model(self):
        c = self._config_with_env(OLLAMA_LLM_MODEL="mistral")
        assert c.ollama.llm_model == "mistral"

    def test_ollama_embedding_model(self):
        c = self._config_with_env(OLLAMA_EMBEDDING_MODEL="mxbai-embed-large")
        assert c.ollama.embedding_model == "mxbai-embed-large"

    def test_ollama_ingest_model(self):
        c = self._config_with_env(OLLAMA_INGEST_MODEL="llama3.2:1b")
        assert c.ollama.ingest_model == "llama3.2:1b"

    # -- Decay --

    def test_decay_enabled(self):
        c = self._config_with_env(REMIND_DECAY_ENABLED="false")
        assert c.decay.enabled is False

    def test_decay_interval(self):
        c = self._config_with_env(REMIND_DECAY_INTERVAL="50")
        assert c.decay.decay_interval == 50

    def test_decay_interval_invalid(self):
        c = self._config_with_env(REMIND_DECAY_INTERVAL="xyz")
        assert c.decay.decay_interval == 20  # unchanged default

    def test_decay_rate(self):
        c = self._config_with_env(REMIND_DECAY_RATE="0.25")
        assert c.decay.decay_rate == 0.25

    def test_decay_rate_invalid(self):
        c = self._config_with_env(REMIND_DECAY_RATE="nope")
        assert c.decay.decay_rate == 0.1  # unchanged default


# =========================================================================
# load_config — full integration (file + env layering)
# =========================================================================


class TestLoadConfig:
    def test_global_config_file_only(self, tmp_path):
        cfg = tmp_path / "remind.config.json"
        cfg.write_text(json.dumps({
            "llm_provider": "ollama",
            "consolidation_threshold": 12,
            "ollama": {"llm_model": "deepseek-v3"},
        }))
        with patch("remind.config.CONFIG_FILE", cfg):
            config = load_config()
        assert config.llm_provider == "ollama"
        assert config.consolidation_threshold == 12
        assert config.ollama.llm_model == "deepseek-v3"
        assert config.embedding_provider == DEFAULT_EMBEDDING_PROVIDER

    def test_project_local_overrides_global(self, tmp_path):
        global_cfg = tmp_path / "global" / "remind.config.json"
        global_cfg.parent.mkdir()
        global_cfg.write_text(json.dumps({
            "llm_provider": "anthropic",
            "consolidation_threshold": 10,
            "anthropic": {"api_key": "global-key"},
        }))

        proj_dir = tmp_path / "project"
        proj_cfg = proj_dir / ".remind" / "remind.config.json"
        proj_cfg.parent.mkdir(parents=True)
        proj_cfg.write_text(json.dumps({
            "llm_provider": "ollama",
            "consolidation_threshold": 3,
        }))

        with patch("remind.config.CONFIG_FILE", global_cfg):
            config = load_config(project_dir=proj_dir)

        assert config.llm_provider == "ollama"
        assert config.consolidation_threshold == 3
        # Global API key still present (project config didn't touch it)
        assert config.anthropic.api_key == "global-key"

    def test_env_overrides_project_local(self, tmp_path):
        proj_dir = tmp_path / "project"
        proj_cfg = proj_dir / ".remind" / "remind.config.json"
        proj_cfg.parent.mkdir(parents=True)
        proj_cfg.write_text(json.dumps({
            "llm_provider": "ollama",
            "consolidation_threshold": 3,
        }))

        os.environ["LLM_PROVIDER"] = "openai"
        os.environ["CONSOLIDATION_THRESHOLD"] = "99"

        with patch("remind.config.CONFIG_FILE", Path("/nonexistent/path.json")):
            config = load_config(project_dir=proj_dir)

        assert config.llm_provider == "openai"
        assert config.consolidation_threshold == 99

    def test_full_priority_chain(self, tmp_path):
        """Global sets A, project overrides A and sets B, env overrides B."""
        global_cfg = tmp_path / "global.json"
        global_cfg.write_text(json.dumps({
            "llm_provider": "anthropic",
            "embedding_provider": "openai",
            "anthropic": {"model": "global-model"},
        }))

        proj_dir = tmp_path / "proj"
        proj_cfg = proj_dir / ".remind" / "remind.config.json"
        proj_cfg.parent.mkdir(parents=True)
        proj_cfg.write_text(json.dumps({
            "llm_provider": "ollama",
            "anthropic": {"model": "project-model"},
        }))

        os.environ["ANTHROPIC_MODEL"] = "env-model"

        with patch("remind.config.CONFIG_FILE", global_cfg):
            config = load_config(project_dir=proj_dir)

        # llm_provider: global=anthropic, project=ollama, env=unset → ollama
        assert config.llm_provider == "ollama"
        # embedding_provider: global=openai, project=unset, env=unset → openai
        assert config.embedding_provider == "openai"
        # anthropic.model: global=global-model, project=project-model, env=env-model → env-model
        assert config.anthropic.model == "env-model"

    def test_no_project_dir_skips_project_config(self, tmp_path):
        global_cfg = tmp_path / "global.json"
        global_cfg.write_text(json.dumps({"llm_provider": "anthropic"}))

        with patch("remind.config.CONFIG_FILE", global_cfg):
            config = load_config()  # no project_dir

        assert config.llm_provider == "anthropic"

    def test_missing_project_config_file_is_fine(self, tmp_path):
        """Passing a project_dir with no .remind/ dir should not error."""
        proj_dir = tmp_path / "empty_project"
        proj_dir.mkdir()

        with patch("remind.config.CONFIG_FILE", Path("/nonexistent.json")):
            config = load_config(project_dir=proj_dir)

        assert config.llm_provider == DEFAULT_LLM_PROVIDER

    def test_malformed_global_config_falls_back_to_defaults(self, tmp_path):
        cfg = tmp_path / "bad.json"
        cfg.write_text("not json!!!")

        with patch("remind.config.CONFIG_FILE", cfg):
            config = load_config()

        assert config.llm_provider == DEFAULT_LLM_PROVIDER

    def test_malformed_project_config_preserves_global(self, tmp_path):
        global_cfg = tmp_path / "global.json"
        global_cfg.write_text(json.dumps({"llm_provider": "openai"}))

        proj_dir = tmp_path / "proj"
        bad_proj_cfg = proj_dir / ".remind" / "remind.config.json"
        bad_proj_cfg.parent.mkdir(parents=True)
        bad_proj_cfg.write_text("{broken")

        with patch("remind.config.CONFIG_FILE", global_cfg):
            config = load_config(project_dir=proj_dir)

        assert config.llm_provider == "openai"


# =========================================================================
# resolve_db_path
# =========================================================================


class TestResolveDbPath:
    def test_simple_name(self):
        path = resolve_db_path("myproject")
        assert path == str(REMIND_DIR / "myproject.db")

    def test_name_with_extension(self):
        path = resolve_db_path("myproject.db")
        assert path == str(REMIND_DIR / "myproject.db")

    def test_absolute_path(self, tmp_path):
        abs_path = str(tmp_path / "custom.db")
        result = resolve_db_path(abs_path)
        assert result == abs_path

    def test_absolute_path_adds_extension(self, tmp_path):
        abs_path = str(tmp_path / "custom")
        result = resolve_db_path(abs_path)
        assert result == abs_path + ".db"

    def test_relative_path_rejected(self):
        with pytest.raises(ValueError, match="Invalid database name"):
            resolve_db_path("some/relative/path")

    def test_tilde_path_rejected(self):
        with pytest.raises(ValueError, match="Invalid database name"):
            resolve_db_path("~/something")

    def test_dot_path_rejected(self):
        with pytest.raises(ValueError, match="Invalid database name"):
            resolve_db_path("./local")

    def test_project_aware_no_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = resolve_db_path(None, project_aware=True)
        assert path == str(tmp_path / ".remind" / "remind.db")
        assert (tmp_path / ".remind").is_dir()

    def test_no_name_not_project_aware(self):
        path = resolve_db_path(None, project_aware=False)
        assert path == str(REMIND_DIR / "memory.db")

    def test_whitespace_stripped(self):
        path = resolve_db_path("  myproject  ")
        assert path == str(REMIND_DIR / "myproject.db")


# =========================================================================
# Parity: every config-file key has a working env var
# =========================================================================


class TestEnvFileParity:
    """Verify that every field settable via config file is also settable via env var."""

    def test_all_top_level_fields_have_env_vars(self, tmp_path):
        file_config = {
            "llm_provider": "file_val",
            "embedding_provider": "file_val",
            "consolidation_threshold": 99,
            "concepts_per_pass": 99,
            "auto_consolidate": False,
            "ingest_buffer_size": 9999,
            "logging_enabled": True,
        }
        env_overrides = {
            "LLM_PROVIDER": "env_val",
            "EMBEDDING_PROVIDER": "env_val",
            "CONSOLIDATION_THRESHOLD": "77",
            "CONCEPTS_PER_PASS": "77",
            "AUTO_CONSOLIDATE": "true",
            "INGEST_BUFFER_SIZE": "7777",
            "REMIND_LOGGING_ENABLED": "false",
        }

        config = RemindConfig()
        _apply_file_config(config, file_config)

        for k, v in env_overrides.items():
            os.environ[k] = v
        _apply_env_vars(config)

        assert config.llm_provider == "env_val"
        assert config.embedding_provider == "env_val"
        assert config.consolidation_threshold == 77
        assert config.concepts_per_pass == 77
        assert config.auto_consolidate is True
        assert config.ingest_buffer_size == 7777
        assert config.logging_enabled is False

    def test_all_anthropic_fields_have_env_vars(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "anthropic": {"api_key": "file", "model": "file", "ingest_model": "file"}
        })
        os.environ["ANTHROPIC_API_KEY"] = "env"
        os.environ["ANTHROPIC_MODEL"] = "env"
        os.environ["ANTHROPIC_INGEST_MODEL"] = "env"
        _apply_env_vars(config)
        assert config.anthropic.api_key == "env"
        assert config.anthropic.model == "env"
        assert config.anthropic.ingest_model == "env"

    def test_all_openai_fields_have_env_vars(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "openai": {
                "api_key": "file", "base_url": "file", "model": "file",
                "embedding_model": "file", "ingest_model": "file",
            }
        })
        os.environ["OPENAI_API_KEY"] = "env"
        os.environ["OPENAI_BASE_URL"] = "env"
        os.environ["OPENAI_MODEL"] = "env"
        os.environ["OPENAI_EMBEDDING_MODEL"] = "env"
        os.environ["OPENAI_INGEST_MODEL"] = "env"
        _apply_env_vars(config)
        assert config.openai.api_key == "env"
        assert config.openai.base_url == "env"
        assert config.openai.model == "env"
        assert config.openai.embedding_model == "env"
        assert config.openai.ingest_model == "env"

    def test_all_azure_fields_have_env_vars(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "azure_openai": {
                "api_key": "file", "base_url": "file",
                "deployment_name": "file", "embedding_deployment_name": "file",
                "embedding_size": 999, "ingest_deployment_name": "file",
            }
        })
        os.environ["AZURE_OPENAI_API_KEY"] = "env"
        os.environ["AZURE_OPENAI_API_BASE_URL"] = "env"
        os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"] = "env"
        os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME"] = "env"
        os.environ["AZURE_OPENAI_EMBEDDING_SIZE"] = "777"
        os.environ["AZURE_OPENAI_INGEST_DEPLOYMENT_NAME"] = "env"
        _apply_env_vars(config)
        assert config.azure_openai.api_key == "env"
        assert config.azure_openai.base_url == "env"
        assert config.azure_openai.deployment_name == "env"
        assert config.azure_openai.embedding_deployment_name == "env"
        assert config.azure_openai.embedding_size == 777
        assert config.azure_openai.ingest_deployment_name == "env"

    def test_all_ollama_fields_have_env_vars(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "ollama": {
                "url": "file", "llm_model": "file",
                "embedding_model": "file", "ingest_model": "file",
            }
        })
        os.environ["OLLAMA_URL"] = "env"
        os.environ["OLLAMA_LLM_MODEL"] = "env"
        os.environ["OLLAMA_EMBEDDING_MODEL"] = "env"
        os.environ["OLLAMA_INGEST_MODEL"] = "env"
        _apply_env_vars(config)
        assert config.ollama.url == "env"
        assert config.ollama.llm_model == "env"
        assert config.ollama.embedding_model == "env"
        assert config.ollama.ingest_model == "env"

    def test_all_decay_fields_have_env_vars(self):
        config = RemindConfig()
        _apply_file_config(config, {
            "decay": {"enabled": True, "decay_interval": 100, "decay_rate": 0.5}
        })
        os.environ["REMIND_DECAY_ENABLED"] = "false"
        os.environ["REMIND_DECAY_INTERVAL"] = "10"
        os.environ["REMIND_DECAY_RATE"] = "0.01"
        _apply_env_vars(config)
        assert config.decay.enabled is False
        assert config.decay.decay_interval == 10
        assert config.decay.decay_rate == 0.01

    def test_remind_cli_output_mode_env(self):
        config = RemindConfig()
        _apply_file_config(config, {"cli_output_mode": "table"})
        os.environ["REMIND_CLI_OUTPUT_MODE"] = "json"
        _apply_env_vars(config)
        assert config.cli_output_mode == "json"
        os.environ["REMIND_CLI_OUTPUT_MODE"] = "compact-json"
        _apply_env_vars(config)
        assert config.cli_output_mode == "compact-json"


class TestInferProjectDirFromDbUrl:
    """infer_project_dir_from_db_url picks project roots for web UI config loading."""

    def test_none_for_database_under_global_remind(self, tmp_path, monkeypatch):
        fake_global = tmp_path / "global_dot_remind"
        fake_global.mkdir()
        monkeypatch.setattr("remind.config.REMIND_DIR", fake_global)
        db_file = fake_global / "eduskunta-2026.db"
        db_file.write_bytes(b"")
        url = f"sqlite:///{db_file}"
        assert infer_project_dir_from_db_url(url) is None

    def test_project_root_for_dot_remind_outside_global(self, tmp_path, monkeypatch):
        fake_global = tmp_path / "global_dot_remind"
        fake_global.mkdir()
        monkeypatch.setattr("remind.config.REMIND_DIR", fake_global)
        project = tmp_path / "ingest-parliament"
        remind = project / ".remind"
        remind.mkdir(parents=True)
        db_file = remind / "eduskunta-2026.db"
        db_file.write_bytes(b"")
        url = f"sqlite:///{db_file}"
        assert infer_project_dir_from_db_url(url) == project.resolve()

    def test_non_sqlite_returns_none(self):
        assert infer_project_dir_from_db_url("postgresql://localhost/db") is None
