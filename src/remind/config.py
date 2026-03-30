"""
Configuration management for Remind.

Config priority (highest to lowest):
1. Explicit function/CLI arguments
2. Environment variables
3. Project-local config file (<project_dir>/.remind/remind.config.json)
4. Global config file (~/.remind/remind.config.json)
5. Hardcoded defaults
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json
import os
import logging

# Built-in episode types (always valid, used as defaults)
DEFAULT_EPISODE_TYPES = [
    "observation", "decision", "question", "meta", "preference",
    "spec", "plan", "task", "outcome", "fact",
]

logger = logging.getLogger(__name__)

# Global paths
REMIND_DIR = Path.home() / ".remind"
CONFIG_FILE = REMIND_DIR / "remind.config.json"

# Default values
DEFAULT_CONSOLIDATION_THRESHOLD = 5
DEFAULT_CONSOLIDATION_CONCEPTS_PER_PASS = 64
DEFAULT_LLM_PROVIDER = "anthropic"
DEFAULT_EMBEDDING_PROVIDER = "openai"


@dataclass
class AnthropicConfig:
    """Anthropic provider configuration."""

    api_key: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"
    ingest_model: Optional[str] = None


@dataclass
class OpenAIConfig:
    """OpenAI provider configuration."""

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "gpt-4.1"
    embedding_model: str = "text-embedding-3-small"
    ingest_model: Optional[str] = None


@dataclass
class AzureOpenAIConfig:
    """Azure OpenAI provider configuration."""

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    deployment_name: Optional[str] = None
    embedding_deployment_name: Optional[str] = None
    embedding_size: int = 1536
    ingest_deployment_name: Optional[str] = None


@dataclass
class OllamaConfig:
    """Ollama provider configuration."""

    url: str = "http://localhost:11434"
    llm_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    ingest_model: Optional[str] = None


@dataclass
class DecayConfig:
    """Memory decay configuration."""

    enabled: bool = True
    decay_interval: int = 20
    decay_rate: float = 0.1


@dataclass
class RemindConfig:
    """Configuration settings for Remind."""

    llm_provider: str = DEFAULT_LLM_PROVIDER
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
    consolidation_threshold: int = DEFAULT_CONSOLIDATION_THRESHOLD
    consolidation_concepts_per_pass: int = DEFAULT_CONSOLIDATION_CONCEPTS_PER_PASS
    auto_consolidate: bool = True

    # Provider-specific configs
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    azure_openai: AzureOpenAIConfig = field(default_factory=AzureOpenAIConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)

    # Decay config
    decay: DecayConfig = field(default_factory=DecayConfig)

    # Auto-ingest config
    ingest_buffer_size: int = 4000
    ingest_min_density: float = 0.4

    # Episode types
    episode_types: list[str] = field(default_factory=lambda: list(DEFAULT_EPISODE_TYPES))

    # Database URL (overrides db_path when set)
    db_url: Optional[str] = None

    # Logging
    logging_enabled: bool = False


def _apply_provider_config(
    config_obj: object, file_config: dict, key: str, config_class: type
) -> None:
    """Overlay provider settings from a file config dict onto an existing config object."""
    provider_data = file_config.get(key, {})
    if not provider_data:
        return

    current = getattr(config_obj, key)
    for field_name in config_class.__dataclass_fields__:
        if field_name in provider_data:
            setattr(current, field_name, provider_data[field_name])


def _apply_file_config(config: RemindConfig, file_config: dict) -> None:
    """Apply settings from a parsed config file dict onto an existing RemindConfig.

    Only keys present in file_config are applied; missing keys leave the
    existing value untouched.  This allows layering global → project-local
    configs by calling the function twice.
    """
    if "llm_provider" in file_config:
        config.llm_provider = file_config["llm_provider"]
    if "embedding_provider" in file_config:
        config.embedding_provider = file_config["embedding_provider"]
    if "consolidation_threshold" in file_config:
        config.consolidation_threshold = int(file_config["consolidation_threshold"])
    if "consolidation_concepts_per_pass" in file_config:
        config.consolidation_concepts_per_pass = int(
            file_config["consolidation_concepts_per_pass"]
        )
    if "auto_consolidate" in file_config:
        config.auto_consolidate = bool(file_config["auto_consolidate"])

    # Provider-specific settings (overlay, not replace)
    _apply_provider_config(config, file_config, "anthropic", AnthropicConfig)
    _apply_provider_config(config, file_config, "openai", OpenAIConfig)
    _apply_provider_config(config, file_config, "azure_openai", AzureOpenAIConfig)
    _apply_provider_config(config, file_config, "ollama", OllamaConfig)

    # Decay settings
    if "decay" in file_config:
        decay_data = file_config["decay"]
        if "enabled" in decay_data:
            config.decay.enabled = bool(decay_data["enabled"])
        if "decay_interval" in decay_data:
            config.decay.decay_interval = int(decay_data["decay_interval"])
        if "decay_rate" in decay_data:
            config.decay.decay_rate = float(decay_data["decay_rate"])

    # Auto-ingest settings
    if "ingest_buffer_size" in file_config:
        config.ingest_buffer_size = int(file_config["ingest_buffer_size"])
    if "ingest_min_density" in file_config:
        config.ingest_min_density = float(file_config["ingest_min_density"])

    # Episode types
    if "episode_types" in file_config:
        raw = file_config["episode_types"]
        if isinstance(raw, list):
            config.episode_types = [str(t).strip().lower() for t in raw if str(t).strip()]

    # Database URL
    if "db_url" in file_config:
        config.db_url = str(file_config["db_url"])

    # Logging
    if "logging_enabled" in file_config:
        config.logging_enabled = bool(file_config["logging_enabled"])


def _load_config_file(path: Path) -> Optional[dict]:
    """Read and parse a JSON config file, returning None on failure."""
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        logger.debug(f"Loaded config from {path}")
        return data
    except (json.JSONDecodeError, IOError, ValueError) as e:
        logger.warning(f"Failed to load config file {path}: {e}")
        return None


def load_config(project_dir: Optional[Path] = None) -> RemindConfig:
    """
    Load configuration with priority:
      env vars > project-local config > global config > defaults.

    Args:
        project_dir: Optional project directory. When provided, also reads
            ``<project_dir>/.remind/remind.config.json`` (takes precedence
            over the global config but is overridden by env vars).

    Returns:
        RemindConfig with resolved settings.
    """
    config = RemindConfig()

    # Layer 1: global config file (~/.remind/remind.config.json)
    global_data = _load_config_file(CONFIG_FILE)
    if global_data:
        _apply_file_config(config, global_data)

    # Layer 2: project-local config file (<project_dir>/.remind/remind.config.json)
    if project_dir is not None:
        project_config_file = Path(project_dir) / ".remind" / "remind.config.json"
        project_data = _load_config_file(project_config_file)
        if project_data:
            _apply_file_config(config, project_data)

    # Layer 3: environment variables (highest priority)
    _apply_env_vars(config)

    return config


def _apply_env_vars(config: RemindConfig) -> None:
    """Override config values from environment variables."""
    # Top-level
    if llm := os.environ.get("LLM_PROVIDER"):
        config.llm_provider = llm
    if embedding := os.environ.get("EMBEDDING_PROVIDER"):
        config.embedding_provider = embedding
    if threshold := os.environ.get("CONSOLIDATION_THRESHOLD"):
        try:
            config.consolidation_threshold = int(threshold)
        except ValueError:
            logger.warning(f"Invalid CONSOLIDATION_THRESHOLD: {threshold}")
    if auto_consolidate := os.environ.get("AUTO_CONSOLIDATE"):
        config.auto_consolidate = auto_consolidate.lower() in ("true", "1", "yes")
    if concepts_per_pass := os.environ.get("CONSOLIDATION_CONCEPTS_PER_PASS"):
        try:
            config.consolidation_concepts_per_pass = int(concepts_per_pass)
        except ValueError:
            logger.warning(f"Invalid CONSOLIDATION_CONCEPTS_PER_PASS: {concepts_per_pass}")

    # Anthropic
    if api_key := os.environ.get("ANTHROPIC_API_KEY"):
        config.anthropic.api_key = api_key
    if model := os.environ.get("ANTHROPIC_MODEL"):
        config.anthropic.model = model
    if ingest_model := os.environ.get("ANTHROPIC_INGEST_MODEL"):
        config.anthropic.ingest_model = ingest_model

    # OpenAI
    if api_key := os.environ.get("OPENAI_API_KEY"):
        config.openai.api_key = api_key
    if base_url := os.environ.get("OPENAI_BASE_URL"):
        config.openai.base_url = base_url
    if model := os.environ.get("OPENAI_MODEL"):
        config.openai.model = model
    if embed_model := os.environ.get("OPENAI_EMBEDDING_MODEL"):
        config.openai.embedding_model = embed_model
    if ingest_model := os.environ.get("OPENAI_INGEST_MODEL"):
        config.openai.ingest_model = ingest_model

    # Azure OpenAI
    if api_key := os.environ.get("AZURE_OPENAI_API_KEY"):
        config.azure_openai.api_key = api_key
    if base_url := os.environ.get("AZURE_OPENAI_API_BASE_URL"):
        config.azure_openai.base_url = base_url
    if deployment := os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME"):
        config.azure_openai.deployment_name = deployment
    if embed_deployment := os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME"):
        config.azure_openai.embedding_deployment_name = embed_deployment
    if embed_size := os.environ.get("AZURE_OPENAI_EMBEDDING_SIZE"):
        try:
            config.azure_openai.embedding_size = int(embed_size)
        except ValueError:
            pass
    if ingest_deployment := os.environ.get("AZURE_OPENAI_INGEST_DEPLOYMENT_NAME"):
        config.azure_openai.ingest_deployment_name = ingest_deployment

    # Ollama
    if url := os.environ.get("OLLAMA_URL"):
        config.ollama.url = url
    if llm_model := os.environ.get("OLLAMA_LLM_MODEL"):
        config.ollama.llm_model = llm_model
    if embed_model := os.environ.get("OLLAMA_EMBEDDING_MODEL"):
        config.ollama.embedding_model = embed_model
    if ingest_model := os.environ.get("OLLAMA_INGEST_MODEL"):
        config.ollama.ingest_model = ingest_model

    # Auto-ingest
    if buf_size := os.environ.get("INGEST_BUFFER_SIZE"):
        try:
            config.ingest_buffer_size = int(buf_size)
        except ValueError:
            logger.warning(f"Invalid INGEST_BUFFER_SIZE: {buf_size}")
    if min_density := os.environ.get("INGEST_MIN_DENSITY"):
        try:
            config.ingest_min_density = float(min_density)
        except ValueError:
            logger.warning(f"Invalid INGEST_MIN_DENSITY: {min_density}")

    # Decay
    if decay_enabled := os.environ.get("REMIND_DECAY_ENABLED"):
        config.decay.enabled = decay_enabled.lower() in ("true", "1", "yes")
    if decay_interval := os.environ.get("REMIND_DECAY_INTERVAL"):
        try:
            config.decay.decay_interval = int(decay_interval)
        except ValueError:
            logger.warning(f"Invalid REMIND_DECAY_INTERVAL: {decay_interval}")
    if decay_rate := os.environ.get("REMIND_DECAY_RATE"):
        try:
            config.decay.decay_rate = float(decay_rate)
        except ValueError:
            logger.warning(f"Invalid REMIND_DECAY_RATE: {decay_rate}")

    # Episode types
    if episode_types := os.environ.get("REMIND_EPISODE_TYPES"):
        parsed = [t.strip().lower() for t in episode_types.split(",") if t.strip()]
        if parsed:
            config.episode_types = parsed

    # Database URL
    if db_url := os.environ.get("REMIND_DB_URL"):
        config.db_url = db_url

    # Logging
    if logging_enabled := os.environ.get("REMIND_LOGGING_ENABLED"):
        config.logging_enabled = logging_enabled.lower() in ("true", "1", "yes")


def resolve_db_path(db_name: Optional[str], project_aware: bool = False) -> str:
    """
    Resolve a database name to a full path.

    Args:
        db_name: Database name or absolute path. If a simple name, resolves to ~/.remind/{name}.db.
                 If an absolute path (starting with /), uses it directly.
        project_aware: If True and db_name is None, uses <cwd>/.remind/remind.db

    Returns:
        Absolute path to database file.

    Raises:
        ValueError: If db_name is a relative path or parent directory doesn't exist.

    Examples:
        resolve_db_path("myproject") → ~/.remind/myproject.db
        resolve_db_path("myproject.db") → ~/.remind/myproject.db
        resolve_db_path("/path/to/memory.db") → /path/to/memory.db
        resolve_db_path(None, project_aware=True) → <cwd>/.remind/remind.db
        resolve_db_path(None, project_aware=False) → ~/.remind/memory.db
    """
    if db_name:
        db_name = db_name.strip()

        # Accept absolute paths as-is
        if db_name.startswith("/"):
            # Ensure .db extension
            if not db_name.endswith(".db"):
                db_name = f"{db_name}.db"
            path = Path(db_name)
            # Create parent directory if it doesn't exist
            path.parent.mkdir(parents=True, exist_ok=True)
            return str(path)

        # Reject relative paths - only simple names allowed
        if "/" in db_name or db_name.startswith("~") or db_name.startswith("."):
            raise ValueError(
                f"Invalid database name '{db_name}'. "
                "Use a simple name like 'myproject', or an absolute path."
            )

        # Ensure the ~/.remind directory exists
        REMIND_DIR.mkdir(parents=True, exist_ok=True)

        # Add .db extension if not present
        if not db_name.endswith(".db"):
            db_name = f"{db_name}.db"

        return str(REMIND_DIR / db_name)

    elif project_aware:
        # No name, project-aware mode: use <cwd>/.remind/remind.db
        project_remind_dir = Path.cwd() / ".remind"
        project_remind_dir.mkdir(parents=True, exist_ok=True)
        return str(project_remind_dir / "remind.db")

    else:
        # No name, not project-aware: use ~/.remind/memory.db (legacy behavior)
        REMIND_DIR.mkdir(parents=True, exist_ok=True)
        return str(REMIND_DIR / "memory.db")


_DB_URL_SCHEMES = ("sqlite://", "postgresql://", "postgresql+", "mysql://", "mysql+")


def _is_db_url(value: str) -> bool:
    """Check if a string looks like a database URL."""
    return any(value.startswith(s) for s in _DB_URL_SCHEMES)


def resolve_db_url(
    db_name: Optional[str] = None,
    project_aware: bool = False,
) -> str:
    """Resolve a database name, path, or URL to a SQLAlchemy database URL.

    If *db_name* is already a full database URL (e.g. ``postgresql://...``)
    it is returned as-is.  Otherwise it goes through the same resolution
    logic as ``resolve_db_path`` and wraps the result with ``sqlite:///``.

    Args:
        db_name: Database name, absolute file path, or full database URL.
        project_aware: If True and db_name is None, uses <cwd>/.remind/remind.db.

    Returns:
        A SQLAlchemy-compatible database URL string.

    Examples:
        resolve_db_url("myproject") → "sqlite:///~/.remind/myproject.db"
        resolve_db_url("/tmp/memory.db") → "sqlite:////tmp/memory.db"
        resolve_db_url("postgresql://u:p@host/db") → "postgresql://u:p@host/db"
        resolve_db_url(None, project_aware=True) → "sqlite:///<cwd>/.remind/remind.db"
    """
    if db_name and _is_db_url(db_name):
        return db_name

    file_path = resolve_db_path(db_name, project_aware=project_aware)
    return f"sqlite:///{file_path}"


_file_logging_configured: set[str] = set()


def setup_file_logging(db_path_or_url: str, project_dir: Optional[Path] = None) -> None:
    """Configure file logging to remind.log in the same directory as the database.

    Attaches a FileHandler to the ``remind`` package logger so all
    sub-module loggers (remind.interface, remind.consolidation, etc.)
    propagate their output to the log file at DEBUG level.

    For non-SQLite database URLs the log goes to <project_dir>/.remind/remind.log
    when *project_dir* is provided, otherwise falls back to ~/.remind/remind.log.

    Safe to call multiple times -- duplicate handlers for the same
    directory are skipped.
    """
    if _is_db_url(db_path_or_url) and not db_path_or_url.startswith("sqlite"):
        if project_dir is not None:
            log_dir = str(project_dir / ".remind")
        else:
            log_dir = str(REMIND_DIR)
    else:
        path = db_path_or_url
        if path.startswith("sqlite:///"):
            path = path[len("sqlite:///"):]
        log_dir = str(Path(path).parent)
    if log_dir in _file_logging_configured:
        return

    log_path = Path(log_dir) / "remind.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(str(log_path))
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    pkg_logger = logging.getLogger("remind")
    pkg_logger.addHandler(handler)
    pkg_logger.setLevel(logging.DEBUG)

    _file_logging_configured.add(log_dir)
    logger.info(f"File logging enabled: {log_path}")
