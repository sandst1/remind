"""CLI command tests."""

from click.testing import CliRunner

from remind.cli import main


class _FakeConfig:
    llm_provider = "openai"
    embedding_provider = "openai"
    db_url = None
    logging_enabled = False


class _FakeMemory:
    def __init__(self):
        self.plan_calls = []
        self.reembed_calls = []

    async def get_reembed_plan(self, include_episodes: bool, include_concepts: bool):
        self.plan_calls.append({
            "include_episodes": include_episodes,
            "include_concepts": include_concepts,
        })
        return {
            "episodes": 4,
            "concepts": 3,
            "stored_dimensions": 3072,
            "target_dimensions": 1536,
        }

    async def reembed(self, include_episodes: bool, include_concepts: bool, batch_size: int):
        self.reembed_calls.append({
            "include_episodes": include_episodes,
            "include_concepts": include_concepts,
            "batch_size": batch_size,
        })
        return {
            "concepts_embedded": 3,
            "episodes_embedded": 4,
            "concepts_cleared": 3,
            "episodes_cleared": 4,
            "stored_dimensions": 3072,
            "target_dimensions": 1536,
        }


def _patch_cli_config(monkeypatch):
    monkeypatch.setattr(
        "remind.config.load_config",
        lambda project_dir=None: _FakeConfig(),
    )
    monkeypatch.setattr(
        "remind.config.resolve_db_url",
        lambda db_name=None, project_aware=False: "sqlite:///:memory:",
    )
    monkeypatch.setattr("remind.config._is_db_url", lambda value: value and "://" in value)


def test_re_embed_defaults_to_all(monkeypatch):
    fake_memory = _FakeMemory()
    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: fake_memory)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--db", "test", "--llm", "openai", "--embedding", "openai", "re-embed", "--yes"],
    )

    assert result.exit_code == 0
    assert fake_memory.plan_calls == [{"include_episodes": True, "include_concepts": True}]
    assert fake_memory.reembed_calls == [{
        "include_episodes": True,
        "include_concepts": True,
        "batch_size": 50,
    }]


def test_re_embed_cancelled_on_prompt(monkeypatch):
    fake_memory = _FakeMemory()
    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: fake_memory)
    monkeypatch.setattr("remind.cli.click.confirm", lambda *_args, **_kwargs: False)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--db", "test", "--llm", "openai", "--embedding", "openai", "re-embed"],
    )

    assert result.exit_code == 0
    assert "Cancelled. No changes made." in result.output
    assert len(fake_memory.plan_calls) == 1
    assert fake_memory.reembed_calls == []
