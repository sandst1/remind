"""
Configuration management for Remind.

Config priority (highest to lowest):
1. Explicit function/CLI arguments
2. Environment variables
3. Config file (~/.remind/remind.config.json)
4. Hardcoded defaults
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json
import os
import logging

logger = logging.getLogger(__name__)

# Global paths
REMIND_DIR = Path.home() / ".remind"
CONFIG_FILE = REMIND_DIR / "remind.config.json"

# Default values
DEFAULT_CONSOLIDATION_THRESHOLD = 5
DEFAULT_LLM_PROVIDER = "anthropic"
DEFAULT_EMBEDDING_PROVIDER = "openai"


@dataclass
class AnthropicConfig:
    """Anthropic provider configuration."""

    api_key: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"


@dataclass
class OpenAIConfig:
    """OpenAI provider configuration."""

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "gpt-4.1"
    embedding_model: str = "text-embedding-3-small"


@dataclass
class AzureOpenAIConfig:
    """Azure OpenAI provider configuration."""

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    api_version: Optional[str] = None
    deployment_name: Optional[str] = None
    embedding_deployment_name: Optional[str] = None
    embedding_size: int = 1536


@dataclass
class OllamaConfig:
    """Ollama provider configuration."""

    url: str = "http://localhost:11434"
    llm_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"


@dataclass
class RemindConfig:
    """Configuration settings for Remind."""

    llm_provider: str = DEFAULT_LLM_PROVIDER
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
    consolidation_threshold: int = DEFAULT_CONSOLIDATION_THRESHOLD
    auto_consolidate: bool = True

    # Provider-specific configs
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    azure_openai: AzureOpenAIConfig = field(default_factory=AzureOpenAIConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)


def _load_provider_config(file_config: dict, key: str, config_class: type) -> object:
    """Load a provider config from file config dict."""
    provider_data = file_config.get(key, {})
    if not provider_data:
        return config_class()

    # Map JSON keys to dataclass fields (handle snake_case)
    kwargs = {}
    for field_name in config_class.__dataclass_fields__:
        if field_name in provider_data:
            kwargs[field_name] = provider_data[field_name]
    return config_class(**kwargs)


def load_config() -> RemindConfig:
    """
    Load configuration with priority: env vars > config file > defaults.

    Returns:
        RemindConfig with resolved settings.
    """
    config = RemindConfig()

    # Load from config file if exists
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                file_config = json.load(f)

            # Top-level settings
            if "llm_provider" in file_config:
                config.llm_provider = file_config["llm_provider"]
            if "embedding_provider" in file_config:
                config.embedding_provider = file_config["embedding_provider"]
            if "consolidation_threshold" in file_config:
                config.consolidation_threshold = int(file_config["consolidation_threshold"])
            if "auto_consolidate" in file_config:
                config.auto_consolidate = bool(file_config["auto_consolidate"])

            # Provider-specific settings
            config.anthropic = _load_provider_config(file_config, "anthropic", AnthropicConfig)
            config.openai = _load_provider_config(file_config, "openai", OpenAIConfig)
            config.azure_openai = _load_provider_config(file_config, "azure_openai", AzureOpenAIConfig)
            config.ollama = _load_provider_config(file_config, "ollama", OllamaConfig)

            logger.debug(f"Loaded config from {CONFIG_FILE}")
        except (json.JSONDecodeError, IOError, ValueError) as e:
            logger.warning(f"Failed to load config file {CONFIG_FILE}: {e}")

    # Override top-level with environment variables (highest priority)
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

    # Override provider settings with environment variables
    # Anthropic
    if api_key := os.environ.get("ANTHROPIC_API_KEY"):
        config.anthropic.api_key = api_key

    # OpenAI
    if api_key := os.environ.get("OPENAI_API_KEY"):
        config.openai.api_key = api_key
    if base_url := os.environ.get("OPENAI_BASE_URL"):
        config.openai.base_url = base_url

    # Azure OpenAI
    if api_key := os.environ.get("AZURE_OPENAI_API_KEY"):
        config.azure_openai.api_key = api_key
    if base_url := os.environ.get("AZURE_OPENAI_API_BASE_URL"):
        config.azure_openai.base_url = base_url
    if api_version := os.environ.get("AZURE_OPENAI_API_VERSION"):
        config.azure_openai.api_version = api_version
    if deployment := os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME"):
        config.azure_openai.deployment_name = deployment
    if embed_deployment := os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME"):
        config.azure_openai.embedding_deployment_name = embed_deployment
    if embed_size := os.environ.get("AZURE_OPENAI_EMBEDDING_SIZE"):
        try:
            config.azure_openai.embedding_size = int(embed_size)
        except ValueError:
            pass

    # Ollama
    if url := os.environ.get("OLLAMA_URL"):
        config.ollama.url = url
    if llm_model := os.environ.get("OLLAMA_LLM_MODEL"):
        config.ollama.llm_model = llm_model
    if embed_model := os.environ.get("OLLAMA_EMBEDDING_MODEL"):
        config.ollama.embedding_model = embed_model

    return config


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
