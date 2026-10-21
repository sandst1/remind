"""Store selection, configuration precedence, and portable path handling."""

from dataclasses import asdict
import json
import logging
import os

import pytest

from remind import config
from remind.storage import default_store_url, open_store


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REMIND_DIR", tmp_path / "global" / ".remind")
    monkeypatch.setattr(config, "CONFIG_FILE", config.REMIND_DIR / "remind.config.json")
    # Keep machine credentials and local preferences out of config assertions.
    for name in list(os.environ):
        if name.startswith(("REMIND_", "OPENAI_", "AZURE_OPENAI_", "OLLAMA_", "LOCAL_EMBEDDING_")) or name == "EMBEDDING_PROVIDER":
            monkeypatch.delenv(name)


def write_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_global_project_environment_precedence(tmp_path, monkeypatch):
    write_config(config.CONFIG_FILE, {"openai": {"api_key": "test-global", "embedding_model": "global-model"},
                                    "hybrid_keyword_weight": .1, "recall_initial_candidates": 12})
    project = tmp_path / "project"
    write_config(project / ".remind/remind.config.json", {"openai": {"embedding_model": "project-model"},
                                                         "hybrid_keyword_weight": .2})
    monkeypatch.setenv("REMIND_HYBRID_KEYWORD_WEIGHT", ".7")
    loaded = config.load_config(project)
    assert loaded.hybrid_keyword_weight == .7
    assert loaded.recall_initial_candidates == 12
    assert loaded.openai.api_key == "test-global"
    assert loaded.openai.embedding_model == "project-model"


def test_all_file_options_round_trip(tmp_path):
    settings = asdict(config.RemindConfig())
    settings.update(embedding_provider="deterministic", store_url="file:///tmp/example",
                    episode_types=[" DECISION ", "", "custom"], recall_max_chars=1200,
                    recall_min_score=.2, recall_timeout_ms=500, cli_output_mode="compactjson")
    write_config(config.CONFIG_FILE, settings)
    loaded = config.load_config()
    for name in settings:
        if name not in {"store_url", "db_url", "episode_types", "cli_output_mode"}:
            assert asdict(loaded)[name] == settings[name]
    assert loaded.episode_types == ["decision", "custom"]
    assert loaded.cli_output_mode == "compact-json"


@pytest.mark.parametrize("key,value,path,expected", [
    ("EMBEDDING_PROVIDER", "deterministic", "embedding_provider", "deterministic"),
    ("LOCAL_EMBEDDING_MODEL", "model", "local.embedding_model", "model"),
    ("OPENAI_API_KEY", "test-key", "openai.api_key", "test-key"),
    ("OPENAI_BASE_URL", "http://example.invalid", "openai.base_url", "http://example.invalid"),
    ("OPENAI_EMBEDDING_MODEL", "model", "openai.embedding_model", "model"),
    ("OPENAI_EMBEDDING_SIZE", "256", "openai.embedding_size", 256),
    ("AZURE_OPENAI_API_KEY", "test-key", "azure_openai.api_key", "test-key"),
    ("AZURE_OPENAI_API_BASE_URL", "http://example.invalid", "azure_openai.base_url", "http://example.invalid"),
    ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "embed", "azure_openai.embedding_deployment_name", "embed"),
    ("AZURE_OPENAI_EMBEDDING_SIZE", "256", "azure_openai.embedding_size", 256),
    ("OLLAMA_URL", "http://example.invalid", "ollama.url", "http://example.invalid"),
    ("OLLAMA_EMBEDDING_MODEL", "model", "ollama.embedding_model", "model"),
    ("REMIND_DECAY_ENABLED", "false", "decay.enabled", False),
    ("REMIND_DECAY_INTERVAL", "5", "decay.decay_interval", 5),
    ("REMIND_DECAY_RATE", ".2", "decay.decay_rate", .2),
    ("REMIND_EPISODE_TYPES", "fact, custom, ", "episode_types", ["fact", "custom"]),
    ("REMIND_STORE", "file:///tmp/store", "db_url", "file:///tmp/store"),
    ("REMIND_DB_URL", "sqlite://", "db_url", "sqlite://"),
    ("REMIND_HYBRID_KEYWORD_WEIGHT", ".6", "hybrid_keyword_weight", .6),
    ("REMIND_RECALL_INITIAL_CANDIDATES", "25", "recall_initial_candidates", 25),
    ("REMIND_LEXICAL_ENABLED", "false", "lexical_enabled", False),
    ("REMIND_RRF_K", "90", "rrf_k", 90),
    ("REMIND_RECALL_MAX_CHARS", "200", "recall_max_chars", 200),
    ("REMIND_RECALL_MIN_SCORE", ".2", "recall_min_score", .2),
    ("REMIND_RECALL_TIMEOUT_MS", "100", "recall_timeout_ms", 100),
    ("REMIND_RERANKING_ENABLED", "true", "reranking_enabled", True),
    ("REMIND_RERANKING_MODEL", "reranker", "reranking_model", "reranker"),
    ("REMIND_CLI_RECALL_WORKER_ENABLED", "false", "cli_recall_worker_enabled", False),
    ("REMIND_CLI_RECALL_WORKER_IDLE_SECONDS", "50", "cli_recall_worker_idle_seconds", 50),
    ("REMIND_FACT_CLUSTER_JACCARD_THRESHOLD", ".8", "fact_cluster_jaccard_threshold", .8),
    ("REMIND_REMEMBER_NEARBY_K", "0", "remember_nearby_k", 0),
    ("REMIND_LOGGING_ENABLED", "yes", "logging_enabled", True),
    ("REMIND_CLI_OUTPUT_MODE", "compact_json", "cli_output_mode", "compact-json"),
])
def test_environment_options(key, value, path, expected, monkeypatch):
    monkeypatch.setenv(key, value)
    loaded = config.load_config()
    actual = loaded
    for part in path.split("."):
        actual = getattr(actual, part)
    assert actual == expected


@pytest.mark.parametrize("key", [
    "OPENAI_EMBEDDING_SIZE", "AZURE_OPENAI_EMBEDDING_SIZE", "REMIND_DECAY_INTERVAL",
    "REMIND_DECAY_RATE", "REMIND_HYBRID_KEYWORD_WEIGHT", "REMIND_RECALL_INITIAL_CANDIDATES",
    "REMIND_RRF_K", "REMIND_RECALL_MAX_CHARS", "REMIND_RECALL_MIN_SCORE", "REMIND_RECALL_TIMEOUT_MS",
    "REMIND_CLI_RECALL_WORKER_IDLE_SECONDS", "REMIND_FACT_CLUSTER_JACCARD_THRESHOLD", "REMIND_REMEMBER_NEARBY_K",
])
def test_invalid_numeric_environment_preserves_defaults(key, monkeypatch):
    monkeypatch.setenv(key, "invalid-number")
    assert config.load_config() == config.RemindConfig()


@pytest.mark.parametrize("value,expected", [(" JSON ", "json"), ("compactjson", "compact-json"),
    ("compact_json", "compact-json"), ("invalid", "table"), (None, "table")])
def test_cli_output_mode(value, expected):
    assert config.normalize_cli_output_mode(value) == expected


@pytest.mark.parametrize("key", ["cliOutputMode", "compactJson"])
def test_legacy_output_mode_keys(key):
    write_config(config.CONFIG_FILE, {key: "compactjson"})
    assert config.load_config().cli_output_mode == "compact-json"


def test_invalid_config_file_is_ignored():
    config.CONFIG_FILE.parent.mkdir(parents=True)
    config.CONFIG_FILE.write_text("{invalid")
    assert config.load_config() == config.RemindConfig()


def test_default_store_starts_in_workdir_then_follows_project_marker(tmp_path, monkeypatch):
    project = tmp_path / "project with spaces"
    (project / ".git").mkdir(parents=True)
    nested = project / "src/deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(project)
    assert config.resolve_db_url(project_aware=True) == (project / ".remind/memory").as_uri()
    monkeypatch.chdir(nested)
    # A Git root alone does not redirect the first call from an unmarked subfolder.
    assert default_store_url(nested) == (nested / ".remind/memory").as_uri()
    (project / ".remind").mkdir()
    assert default_store_url(nested) == (project / ".remind/memory").as_uri()
    assert config.resolve_db_url(project_aware=True) == default_store_url(nested)
    # A nearer store marker takes precedence.
    (nested.parent / ".remind").mkdir()
    assert default_store_url(nested) == (nested.parent / ".remind/memory").as_uri()


def test_default_store_non_git_tree_and_unmarked_subfolder(tmp_path, monkeypatch):
    project = tmp_path / "documents"
    nested = project / "subfolder"
    nested.mkdir(parents=True)
    monkeypatch.chdir(project)
    assert config.resolve_db_url(project_aware=True) == (project / ".remind/memory").as_uri()
    monkeypatch.chdir(nested)
    assert config.resolve_db_url(project_aware=True) == (nested / ".remind/memory").as_uri()
    (project / ".remind").mkdir()
    assert config.resolve_db_url(project_aware=True) == (project / ".remind/memory").as_uri()


def test_global_remind_is_not_an_implicit_parent_store(tmp_path, monkeypatch):
    home = tmp_path / "global"
    project = home / "Documents/workdocs/fidelix"
    project.mkdir(parents=True)
    config.REMIND_DIR.mkdir(parents=True)
    monkeypatch.chdir(project)
    assert config.resolve_db_url(project_aware=True) == (project / ".remind/memory").as_uri()
    monkeypatch.chdir(home)
    assert config.resolve_db_url(project_aware=True) == (home / ".remind/memory").as_uri()


def test_store_url_and_migration_paths(tmp_path):
    from remind.models import Episode
    legacy = tmp_path / "old store.db"
    sql = open_store(f"sqlite:///{legacy}")
    sql.add_episode(Episode(id="legacy", content="Migrated content"))
    sql.engine.dispose()
    selector = config.resolve_db_url(str(legacy))
    assert selector == legacy.with_suffix(".memory").as_uri()
    files = open_store(selector)
    try:
        assert files.get_episode("legacy").content == "Migrated content"
        assert (files.runtime / "legacy-backup.db").exists()
    finally:
        files.engine.dispose()
    assert config.resolve_db_url("named.db") == (config.REMIND_DIR / "named.memory").as_uri()
    assert config.resolve_db_url("named") == (config.REMIND_DIR / "named.memory").as_uri()
    assert config.resolve_db_url() == (config.REMIND_DIR / "memory.memory").as_uri()
    for selector in ("postgresql://example/db", "mysql+pymysql://example/db", "sqlite://", "file:///tmp/store"):
        assert config.resolve_db_url(selector) == selector


def test_infer_project_directory_decodes_file_uri(tmp_path):
    project = tmp_path / "project with spaces"
    assert config.infer_project_dir_from_db_url((project / ".remind/memory").as_uri()) == project
    assert config.infer_project_dir_from_db_url((project / "custom").as_uri()) == project
    assert config.infer_project_dir_from_db_url((config.REMIND_DIR / "named.memory").as_uri()) is None
    assert config.infer_project_dir_from_db_url(f"sqlite:///{project}/.remind/old.db") == project
    assert config.infer_project_dir_from_db_url(f"sqlite:///{config.REMIND_DIR}/old.db") is None
    for value in (None, "postgresql://example/db", "sqlite:///", f"sqlite:///{project}/other.db"):
        assert config.infer_project_dir_from_db_url(value) is None


def test_file_logging_decodes_uri_and_is_idempotent(tmp_path):
    root = tmp_path / "project with spaces" / ".remind"
    logger = logging.getLogger("remind")
    previous_handlers, previous_level = logger.handlers[:], logger.level
    previous_configured = set(config._file_logging_configured)
    try:
        selector = (root / "memory").as_uri()
        config.setup_file_logging(selector)
        config.setup_file_logging(selector)
        assert len(logger.handlers) == len(previous_handlers) + 1
        logger.warning("Logging path regression")
        assert "Logging path regression" in (root / "runtime/remind.log").read_text()
    finally:
        for handler in logger.handlers[:]:
            if handler not in previous_handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(previous_level)
        config._file_logging_configured.clear()
        config._file_logging_configured.update(previous_configured)
