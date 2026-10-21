"""CLI command tests."""

import json
from pathlib import Path

import pytest

from click.testing import CliRunner

from remind.cli import main
from remind.config import DEFAULT_EPISODE_TYPES


def test_cli_default_store_stays_in_workspace_and_serves_subfolders(tmp_path, monkeypatch):
    from remind import config

    monkeypatch.setattr(config, "REMIND_DIR", tmp_path / "home/.remind")
    monkeypatch.setattr(config, "CONFIG_FILE", config.REMIND_DIR / "remind.config.json")
    config.REMIND_DIR.mkdir(parents=True)
    workspace = tmp_path / "home/Documents/workspace"
    nested = workspace / "notes"
    nested.mkdir(parents=True)
    runner = CliRunner()

    monkeypatch.chdir(workspace)
    first = runner.invoke(main, ["--embedding", "deterministic", "snapshot", "stats"])
    assert first.exit_code == 0, first.output
    assert (workspace / ".remind/memory/schema.json").is_file()
    assert not (config.REMIND_DIR / "memory").exists()

    monkeypatch.chdir(nested)
    second = runner.invoke(main, ["--embedding", "deterministic", "snapshot", "stats"])
    assert second.exit_code == 0, second.output
    assert not (nested / ".remind").exists()


@pytest.mark.parametrize("agent,relative_dir", [
    (None, ".agents/skills"),
    ("agents", ".agents/skills"),
    ("claude", ".claude/skills"),
    ("cursor", ".cursor/skills"),
    ("codex", ".agents/skills"),
    ("opencode", ".opencode/skills"),
])
def test_skill_install_destinations(tmp_path, monkeypatch, agent, relative_dir):
    from remind.cli import SKILL_NAMES, _read_skill

    monkeypatch.chdir(tmp_path)
    args = ["skill-install"]
    if agent:
        args += ["--agent", agent]
    result = CliRunner().invoke(main, args)

    assert result.exit_code == 0, result.output
    for name in SKILL_NAMES:
        installed = tmp_path / relative_dir / name / "SKILL.md"
        assert installed.read_text(encoding="utf-8") == _read_skill(name)
    assert not (tmp_path / ".remind").exists()


@pytest.mark.parametrize("directory", ["another project", "~/another project", "~"])
def test_skill_install_custom_directory(tmp_path, monkeypatch, directory):
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    result = CliRunner().invoke(main, [
        "skill-install", "remind-context", "--agent", "claude", "--dir", directory,
    ])

    assert result.exit_code == 0, result.output
    destination = Path(directory).expanduser().resolve() / ".claude/skills"
    assert (destination / "remind-context/SKILL.md").is_file()
    assert not (destination / "remind-capture").exists()
    assert not (tmp_path / ".agents").exists()


def test_skill_install_opencode_home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    result = CliRunner().invoke(main, [
        "skill-install", "--agent", "opencode", "--dir", "~",
    ])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "home/.config/opencode/skills/remind-context/SKILL.md").is_file()
    assert not (tmp_path / "home/.opencode").exists()


def test_skill_install_overwrite_and_scoped_legacy_cleanup(tmp_path, monkeypatch):
    from remind.cli import _read_skill

    monkeypatch.chdir(tmp_path)
    for relative in [".agents/skills/remind", ".claude/skills/remind",
                     ".agents/skills/remind-context", ".agents/skills/custom"]:
        folder = tmp_path / relative
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("old", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["skill-install", "remind-context"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".agents/skills/remind/SKILL.md").exists()
    assert (tmp_path / ".agents/skills/remind-context/SKILL.md").read_text() == _read_skill("remind-context")

    result = runner.invoke(main, ["skill-install"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".agents/skills/remind").exists()
    assert (tmp_path / ".claude/skills/remind/SKILL.md").exists()
    assert (tmp_path / ".agents/skills/custom/SKILL.md").read_text() == "old"


@pytest.mark.parametrize("args", [
    ["--agent", "unknown"],
    ["remind-context", "unknown"],
    ["--dir", "existing-file"],
])
def test_skill_install_invalid_arguments_do_not_write(tmp_path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "existing-file").write_text("keep")
    result = CliRunner().invoke(main, ["skill-install", *args])

    assert result.exit_code != 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["existing-file"]


class _FakeConfig:
    llm_provider = "openai"
    embedding_provider = "openai"
    db_url = None
    logging_enabled = False
    cli_output_mode = "table"
    episode_types = list(DEFAULT_EPISODE_TYPES)


class _FakeMemory:
    def __init__(self):
        self.plan_calls = []
        self.reembed_calls = []

    async def get_reembed_plan(
        self,
        include_episodes: bool,
        include_concepts: bool,
        include_entities: bool = True,
        include_facts: bool = True,
    ):
        self.plan_calls.append({
            "include_episodes": include_episodes,
            "include_concepts": include_concepts,
            "include_entities": include_entities,
            "include_facts": include_facts,
        })
        return {
            "episodes": 4,
            "concepts": 3,
            "entities": 2,
            "facts": 1,
            "stored_dimensions": 3072,
            "target_dimensions": 1536,
        }

    async def reembed(
        self,
        include_episodes: bool,
        include_concepts: bool,
        include_entities: bool = True,
        include_facts: bool = True,
        batch_size: int = 50,
    ):
        self.reembed_calls.append({
            "include_episodes": include_episodes,
            "include_concepts": include_concepts,
            "include_entities": include_entities,
            "include_facts": include_facts,
            "batch_size": batch_size,
        })
        return {
            "concepts_embedded": 3,
            "episodes_embedded": 4,
            "entities_embedded": 2,
            "facts_embedded": 1,
            "concepts_cleared": 3,
            "episodes_cleared": 4,
            "entities_cleared": 2,
            "facts_cleared": 1,
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
        ["--db", "test", "--embedding", "openai", "re-embed", "--yes"],
    )

    assert result.exit_code == 0
    assert fake_memory.plan_calls == [{
        "include_episodes": True,
        "include_concepts": True,
        "include_entities": True,
        "include_facts": True,
    }]
    assert fake_memory.reembed_calls == [{
        "include_episodes": True,
        "include_concepts": True,
        "include_entities": True,
        "include_facts": True,
        "batch_size": 50,
    }]
    assert "Re-embedded facts: 1" in result.output


def test_re_embed_facts_only(monkeypatch):
    fake_memory = _FakeMemory()
    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: fake_memory)

    result = CliRunner().invoke(
        main,
        ["--db", "test", "--embedding", "openai", "re-embed", "--facts", "--yes"],
    )

    assert result.exit_code == 0
    assert fake_memory.plan_calls[0] == {
        "include_episodes": False,
        "include_concepts": False,
        "include_entities": False,
        "include_facts": True,
    }


def test_clear_embeddings_clears_all_record_types(monkeypatch):
    class FakeStore:
        def __init__(self):
            self.calls = 0

        def clear_embeddings(self):
            self.calls += 1
            return {
                "concepts_cleared": 3,
                "episodes_cleared": 4,
                "entities_cleared": 2,
                "facts_cleared": 1,
            }

    class FakeMemory:
        def __init__(self):
            self.store = FakeStore()

    memory = FakeMemory()
    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: memory)

    result = CliRunner().invoke(
        main,
        ["--db", "test", "--embedding", "openai", "clear-embeddings", "--yes"],
    )

    assert result.exit_code == 0
    assert memory.store.calls == 1
    assert "Cleared facts: 1" in result.output


def test_re_embed_requires_tty_or_yes_flag(monkeypatch):
    """In non-TTY mode, re-embed requires --yes flag to proceed."""
    fake_memory = _FakeMemory()
    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: fake_memory)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--db", "test", "--embedding", "openai", "re-embed"],
    )

    # In non-TTY mode, should fail with helpful message
    assert result.exit_code == 1
    assert "Use -y/--yes flag" in result.output
    assert len(fake_memory.plan_calls) == 1
    assert fake_memory.reembed_calls == []


def test_types_json_output(monkeypatch):
    _patch_cli_config(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--db", "test", "--embedding", "openai", "types", "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "configured" in data
    assert "disabled_defaults" in data
    assert isinstance(data["configured"], list)


def test_cli_output_flags_mutually_exclusive(monkeypatch):
    _patch_cli_config(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--db", "test", "--embedding", "openai", "types", "--json", "--table"],
    )
    assert result.exit_code != 0
    assert "only one of" in result.output.lower()

    r2 = runner.invoke(
        main,
        [
            "--db",
            "test",
            "--embedding",
            "openai",
            "types",
            "--json",
            "--compact-json",
        ],
    )
    assert r2.exit_code != 0
    assert "only one of" in r2.output.lower()


def test_types_compact_json_output(monkeypatch):
    _patch_cli_config(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--db", "test", "--embedding", "openai", "types", "--compact-json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data.get("format") == "compact-json"
    assert "configured" in data
    assert "disabled_defaults" in data
    assert isinstance(data["configured"], list)
    if data["configured"]:
        row = data["configured"][0]
        assert set(row.keys()) == {"id", "title", "summary"}


def test_export_writes_interface_payload(monkeypatch, tmp_path):
    class FileMemory:
        def export_memory(self):
            return {"version": 3, "concepts": [{"id": "concept-1"}], "episodes": [{"id": "episode-1"}]}

    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: FileMemory())
    export_path = tmp_path / "backup.json"

    result = CliRunner().invoke(
        main,
        ["--db", "test", "--embedding", "openai", "export", str(export_path)],
    )

    assert result.exit_code == 0
    assert json.loads(export_path.read_text())["concepts"] == [{"id": "concept-1"}]
    assert "Exported 1 concepts and 1 episodes" in result.output


def test_import_reads_file_before_calling_interface(monkeypatch, tmp_path):
    class FileMemory:
        imported_data = None

        def import_memory(self, data):
            self.imported_data = data
            return {"concepts_imported": 1, "episodes_imported": 1}

    memory = FileMemory()
    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: memory)
    import_path = tmp_path / "backup.json"
    import_path.write_text(json.dumps({"concepts": [], "episodes": []}))

    result = CliRunner().invoke(
        main,
        ["--db", "test", "--embedding", "openai", "import", str(import_path)],
    )

    assert result.exit_code == 0
    assert memory.imported_data == {"concepts": [], "episodes": []}


def test_deleted_json_and_purge_episode_use_storage_compatible_api(monkeypatch):
    class DeletedMemory:
        def __init__(self):
            self.episode_limits = []
            self.purged_episode_ids = []

        def get_deleted_episodes(self, limit):
            self.episode_limits.append(limit)
            return []

        def get_deleted_concepts(self):
            return []

        def purge_episode(self, episode_id, expected_revision):
            self.purged_episode_ids.append(episode_id)
            return True

    memory = DeletedMemory()
    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: memory)
    runner = CliRunner()

    deleted = runner.invoke(
        main,
        ["--db", "test", "--embedding", "openai", "deleted", "--json"],
    )
    purged = runner.invoke(
        main,
        ["--db", "test", "--embedding", "openai", "purge-episode", "-y", "episode-1", "--expected-revision", "observed-revision"],
    )

    assert deleted.exit_code == 0
    assert json.loads(deleted.output) == {"episodes": [], "concepts": []}
    assert memory.episode_limits == [20]
    assert purged.exit_code == 0
    assert memory.purged_episode_ids == ["episode-1"]


def test_events_command_polls_change_feed(monkeypatch):
    class EventsStore:
        def __init__(self):
            self.calls = []

        def get_events(self, since_seq=0, limit=100, kind=None):
            self.calls.append({"since_seq": since_seq, "limit": limit, "kind": kind})
            return [
                {"seq": 43, "ts": "2026-01-01T00:00:00", "kind": "remembered",
                 "subject_type": "episode", "subject_id": "ep1", "payload": None},
            ]

    class EventsMemory:
        def __init__(self):
            self.store = EventsStore()

    memory = EventsMemory()
    _patch_cli_config(monkeypatch)
    monkeypatch.setattr("remind.cli.get_memory", lambda *_args, **_kwargs: memory)

    result = CliRunner().invoke(
        main,
        ["--db", "test", "--embedding", "openai", "events", "--since", "42"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["since_seq"] == 42
    assert data["count"] == 1
    assert data["next_since_seq"] == 43
    assert memory.store.calls == [{"since_seq": 42, "limit": 200, "kind": None}]
