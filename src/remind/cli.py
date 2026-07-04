"""
CLI for Remind - agent-driven memory layer.

Commands:
    remind remember "text"       - Add an episode
    remind recall "query"        - Retrieve relevant concepts
    remind snapshot <scopes>     - Read memory state as JSON
    remind apply <changeset>     - Apply batch changes transactionally
    remind inspect [id]          - View concepts/relations
    remind stats                 - Show memory statistics
    remind export <file>         - Export memory to JSON
    remind import <file>         - Import memory from JSON
    remind re-embed              - Recompute embeddings
"""

import asyncio
import importlib.resources
import json
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any, Optional

import click
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.tree import Tree
from rich.syntax import Syntax

console = Console()


def _resolve_cli_output_format(
    ctx: click.Context,
    as_table: bool,
    as_json: bool,
    as_compact_json: bool,
) -> str:
    """Return 'table', 'json', or 'compact_json'. Flags override ctx.obj cli_output_mode."""
    if int(as_table) + int(as_json) + int(as_compact_json) > 1:
        raise click.UsageError("Use only one of --table, --json, or --compact-json.")
    if as_table:
        return "table"
    if as_json:
        return "json"
    if as_compact_json:
        return "compact_json"
    mode = str((ctx.obj or {}).get("cli_output_mode") or "table").strip().lower().replace("_", "-")
    if mode == "compactjson":
        mode = "compact-json"
    if mode == "compact-json":
        return "compact_json"
    if mode == "json":
        return "json"
    return "table"


def _emit_cli_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def _concept_to_json_dict(concept: Any) -> dict:
    """Concept.to_dict() without large embedding vectors."""
    d = concept.to_dict()
    d.pop("embedding", None)
    return d


def _episode_compact_summary(ep: Any, max_len: int = 240) -> Optional[str]:
    """Prefer episode.summary; else trimmed content for compact JSON."""
    if getattr(ep, "summary", None):
        return ep.summary
    raw = (getattr(ep, "content", None) or "").strip()
    if not raw:
        return None
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 3] + "..."


def _compact_episode(ep: Any) -> dict[str, Any]:
    return {
        "id": ep.id,
        "title": ep.title,
        "summary": _episode_compact_summary(ep),
    }


def _compact_concept(c: Any) -> dict[str, Any]:
    return {"id": c.id, "title": c.title, "summary": c.summary}


def _compact_topic_row(t: dict) -> dict[str, Any]:
    return {
        "id": t["id"],
        "title": t.get("name") or "",
        "summary": (t.get("description") or "") or "",
    }


def _compact_entity(e: Any) -> dict[str, Any]:
    eid = e.id
    if ":" in eid:
        _type, name = eid.split(":", 1)
    else:
        _type, name = "id", eid
    return {
        "id": e.id,
        "title": e.display_name,
        "summary": f"{e.type.value}:{name}",
    }


def _compact_relation_out(rel: Any, store: Any) -> dict[str, Any]:
    tgt = store.get_entity(rel.target_id)
    title = tgt.display_name if tgt else None
    sm = f"{rel.relation_type} ({rel.strength:.0%})"
    ctx = rel.context or ""
    if ctx:
        sm += " — " + (ctx[:120] + ("..." if len(ctx) > 120 else ""))
    return {
        "target_id": rel.target_id,
        "relation_type": rel.relation_type,
        "title": title,
        "summary": sm,
    }


def _compact_relation_in(rel: Any, store: Any) -> dict[str, Any]:
    src = store.get_entity(rel.source_id)
    title = src.display_name if src else None
    sm = f"{rel.relation_type} ({rel.strength:.0%})"
    ctx = rel.context or ""
    if ctx:
        sm += " — " + (ctx[:120] + ("..." if len(ctx) > 120 else ""))
    return {
        "source_id": rel.source_id,
        "relation_type": rel.relation_type,
        "title": title,
        "summary": sm,
    }


SKILL_NAMES = ["remind-capture", "remind-context", "remind-curate"]

# Old monolithic skill, replaced by the three above. Cleaned up on install.
LEGACY_SKILL_NAMES = ["remind"]


def _read_skill(name: str) -> str:
    """Read a bundled skill file from package data."""
    ref = importlib.resources.files("remind") / "skills" / name / "SKILL.md"
    return ref.read_text(encoding="utf-8")


def get_memory(db_path: str, embedding: str, project_dir: Optional[Path] = None):
    """Create a MemoryInterface with the given settings."""
    from remind.interface import create_memory
    return create_memory(
        embedding_provider=embedding,
        db_url=db_path,
        project_dir=project_dir or Path.cwd(),
    )


def run_async(coro):
    """Run an async function synchronously."""
    return asyncio.run(coro)


def _recall_config_fingerprint(config: Any) -> str:
    """Build stable fingerprint for recall worker identity."""
    payload = asdict(config)
    # Fingerprint does not need secrets in cleartext; hash happens in background helpers.
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _deserialize_worker_raw_result(result_type: str, payload: list[dict[str, Any]]):
    """Convert worker JSON payload back to rich Python objects used by CLI output."""
    if result_type == "entity_raw":
        from remind.models import Episode

        return [Episode.from_dict(item) for item in payload]

    if result_type == "semantic_raw":
        from remind.models import Concept
        from remind.retrieval import ActivatedConcept

        output = []
        for item in payload:
            concept_data = item.get("concept") or {}
            output.append(ActivatedConcept(
                concept=Concept.from_dict(concept_data),
                activation=float(item.get("activation", 0.0)),
                source=str(item.get("source", "embedding")),
                hops=int(item.get("hops", 0)),
            ))
        return output

    return payload


def _run_recall_via_worker(
    ctx,
    *,
    query: Optional[str],
    k: int,
    episode_k: int,
    context: Optional[str],
    entity: Optional[str],
    topic: Optional[str],
    raw: bool,
):
    """Run recall over persistent worker, with one-shot fallback on failure."""
    from remind.background import (
        DEFAULT_RECALL_WORKER_IDLE_SECONDS,
        build_recall_worker_key,
        ensure_recall_worker,
        request_recall_worker,
    )
    from remind.config import load_config

    config = load_config(project_dir=Path.cwd())
    worker_key = build_recall_worker_key(
        db_url=ctx.obj["db"],
        llm_provider=ctx.obj["llm"],
        embedding_provider=ctx.obj["embedding"],
        config_fingerprint=_recall_config_fingerprint(config),
    )
    socket_path = ensure_recall_worker(
        db_url=ctx.obj["db"],
        llm_provider=ctx.obj["llm"],
        embedding_provider=ctx.obj["embedding"],
        worker_key=worker_key,
        idle_seconds=getattr(config, "cli_recall_worker_idle_seconds", DEFAULT_RECALL_WORKER_IDLE_SECONDS),
        remind_dir=ctx.obj.get("remind_dir"),
    )
    if socket_path is None:
        raise RuntimeError("Recall worker unavailable")

    response = request_recall_worker(
        socket_path,
        query=query,
        k=k,
        episode_k=episode_k,
        context=context,
        entity=entity,
        topic=topic,
        raw=raw,
    )
    if not response:
        raise RuntimeError("No response from recall worker")
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Recall worker request failed"))

    result_type = str(response.get("result_type", "text"))
    result = response.get("result")
    if raw and isinstance(result, list):
        return _deserialize_worker_raw_result(result_type, result)
    return result


@click.group()
@click.version_option(version=version("remind-mcp"), prog_name="remind")
@click.option("--db", default=None, help="Database name, path, or URL (e.g. 'myproject', '/path/to/db.db', 'postgresql+psycopg://user:pass@host/db'). Default: <cwd>/.remind/remind.db")
@click.option("--embedding", default=None, type=click.Choice(["local", "openai", "azure_openai", "ollama"]))
@click.pass_context
def main(ctx, db: str, embedding: str):
    """Remind - Agent-driven memory layer for LLMs."""
    from remind.config import load_config, resolve_db_url, _is_db_url, setup_file_logging

    config = load_config(project_dir=Path.cwd())

    embedding = embedding or config.embedding_provider

    if db and _is_db_url(db):
        db_url = db
    elif config.db_url:
        db_url = config.db_url if not db else resolve_db_url(db)
    elif db:
        db_url = resolve_db_url(db)
    else:
        db_url = resolve_db_url(None, project_aware=True)

    # Determine the directory for locks/logs used by background workers.
    # - SQLite: use the directory containing the .db file (co-located with the db)
    # - Remote DB (postgres, mysql, …): use <cwd>/.remind (project-local)
    # - Anything else: None → falls back to ~/.remind
    project_remind_dir: Optional[Path]
    if db_url.startswith("sqlite:///"):
        db_file = Path(db_url[len("sqlite:///"):])
        project_remind_dir = db_file.parent
    elif "://" in db_url:
        project_remind_dir = Path.cwd() / ".remind"
    else:
        project_remind_dir = None

    if config.logging_enabled:
        setup_file_logging(db_url, project_dir=Path.cwd())

    ctx.ensure_object(dict)
    ctx.obj["db"] = db_url
    ctx.obj["embedding"] = embedding
    ctx.obj["remind_dir"] = project_remind_dir
    ctx.obj["cli_output_mode"] = config.cli_output_mode


@main.command()
@click.argument("content")
@click.option("--metadata", "-m", help="JSON metadata to attach")
@click.option("--type", "-t", "episode_type", 
              help="Episode type (detected during consolidation if not provided)")
@click.option("--entity", "-e", "entities", multiple=True, 
              help="Entity IDs (e.g., file:src/auth.ts, person:alice)")
@click.option("--topic", help="Knowledge area (e.g., architecture, product, infra)")
@click.option("--source-type", help="Origin of this memory (e.g., agent, slack, github, manual)")
@click.option("--asserted-by", help="Who asserted this information (e.g., alice, agent:cursor)")
@click.option("--source-ref", help="Link to the original artifact (URL/permalink)")
@click.option("--no-embed", is_flag=True, help="Skip embedding the episode (faster, no API call)")
@click.pass_context
def remember(ctx, content: str, metadata: Optional[str], episode_type: Optional[str], 
             entities: tuple, topic: Optional[str], source_type: Optional[str],
             asserted_by: Optional[str], source_ref: Optional[str], no_embed: bool):
    """Add an episode to memory.
    
    Embeds the episode by default for vector search during recall.
    Entity extraction and type classification happen during consolidation.
    """
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    
    meta = json.loads(metadata) if metadata else None
    entity_list = list(entities) if entities else None
    
    async def _remember():
        return await memory.remember(
            content, 
            metadata=meta,
            episode_type=episode_type,
            entities=entity_list,
            embed=not no_embed,
            topic=topic,
            source_type=source_type,
            asserted_by=asserted_by,
            source_ref=source_ref,
        )

    result = run_async(_remember())
    
    console.print(f"[green]✓[/green] Remembered as episode [cyan]{result.episode_id}[/cyan]")

    # Show explicit type/entities if provided
    if episode_type:
        console.print(f"  Type: [yellow]{episode_type}[/yellow]")
    if entity_list:
        console.print(f"  Entities: {', '.join(entity_list)}")
    if topic:
        console.print(f"  Topic: [blue]{topic}[/blue]")
    if source_type:
        console.print(f"  Source: {source_type}")
    if asserted_by:
        console.print(f"  Asserted by: {asserted_by}")
    if source_ref:
        console.print(f"  Source ref: {source_ref}")
    
    # For facts, show cluster and collision info
    if result.fact_id:
        console.print(f"  Fact ID: [cyan]{result.fact_id}[/cyan]")
        cluster_suffix = " [dim](new)[/dim]" if result.cluster_created else ""
        console.print(f"  Cluster: [cyan]{result.cluster_id}[/cyan]{cluster_suffix}")
        
        if result.has_collisions():
            console.print(f"\n[yellow]⚠ {len(result.collisions)} potential collision(s) in same cluster:[/yellow]")
            for collision in result.collisions:
                stmt = collision.statement[:60] + "..." if len(collision.statement) > 60 else collision.statement
                console.print(f"  - {collision.id}: {stmt}")
            console.print(f"\n[dim]→ If new fact supersedes an old one:[/dim]")
            for collision in result.collisions:
                console.print(f'[dim]  remind apply \'supersede old={collision.id} new={result.fact_id} note="reason"\'[/dim]')
            console.print(f"[dim]→ If both valid in different contexts: no action needed[/dim]")

    if result.has_nearby():
        console.print(f"\n[dim]Nearby ({len(result.nearby_episodes)} episodes, {len(result.nearby_concepts)} concepts) — review for conflicts:[/dim]")
        high_similarity_eps = []
        for ep, score in result.nearby_episodes:
            snippet = ep.content[:70] + "..." if len(ep.content) > 70 else ep.content
            console.print(f"  [dim][ep:{ep.id[:8]}] ({score:.2f}) {snippet}[/dim]")
            if score > 0.85:
                high_similarity_eps.append((ep, score))
        for concept, score in result.nearby_concepts:
            console.print(f"  [dim][concept:{concept.id}] ({score:.2f}) {concept.title}[/dim]")
        if high_similarity_eps:
            console.print(f"[dim]→ If nearby episode contradicts what you just stored:[/dim]")
            for ep, score in high_similarity_eps:
                console.print(f'[dim]  remind apply \'conflict a={ep.id} b={result.episode_id} note="reason"\'[/dim]')


@main.command()
@click.argument("changeset", required=False, default=None)
@click.option("--file", "-f", "input_file", type=click.Path(exists=True), 
              help="Read changeset from file instead of argument")
@click.option("--dry-run", is_flag=True, help="Validate only, don't execute")
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON")
@click.pass_context
def apply(ctx, changeset: Optional[str], input_file: Optional[str], dry_run: bool, as_json: bool):
    """Apply a batch changeset to memory.
    
    Accepts either JSON or compact line format (auto-detected).
    All operations execute in a single transaction (all-or-nothing).
    
    \b
    Compact line format (canonical):
        remember as=f1 t=fact e=concept:caching "Cache TTL is 600 seconds"
        supersede old=fact:a91c2 new=$f1
        concept as=c1 from=ep:11,ep:12 title="Pattern title" "Summary text"
        resolve id=conflict:7 winner=fact:b3d01 "confirmed by bob"
        processed ids=ep:11,ep:12
    
    \b
    JSON format:
        [{"op": "remember", "as": "f1", "t": "fact", "content": "..."}]
    
    \b
    Operations: remember, supersede, conflict, resolve, dismiss, concept,
                update, link, topic, set_topic, delete, restore, processed
    
    Examples:
        remind apply 'remember t=fact e=concept:cache "TTL is 600"'
        remind apply -f changes.txt
        cat changes.txt | remind apply -
        remind apply --dry-run 'remember t=fact "test"'
    """
    from remind.apply import ApplyEngine
    
    # Read changeset from stdin, file, or argument
    if changeset == "-":
        changeset = sys.stdin.read()
    elif input_file:
        changeset = Path(input_file).read_text()
    elif not changeset:
        # Try reading from stdin if nothing provided
        if not sys.stdin.isatty():
            changeset = sys.stdin.read()
        else:
            raise click.UsageError("Provide a changeset as argument, via --file, or pipe to stdin")
    
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    
    engine = ApplyEngine(
        store=memory.store,
        embedding=memory.embedding,
        fact_cluster_jaccard_threshold=memory.fact_cluster_jaccard_threshold,
    )
    
    async def _apply():
        return await engine.apply(changeset, dry_run=dry_run)
    
    result = run_async(_apply())
    
    if as_json:
        _emit_cli_json(result.to_dict())
        return
    
    if result.success:
        if dry_run:
            console.print(f"[green]✓[/green] Validation passed ({result.ops_executed} operations)")
        else:
            console.print(f"[green]✓[/green] Applied {result.ops_executed} operations")
            
            # Show created IDs
            for r in result.results:
                if r.id:
                    label = f" ({r.ref})" if r.ref else ""
                    console.print(f"  {r.op_type}: [cyan]{r.id}[/cyan]{label}")
                    
                    # Show collisions for remember ops
                    if r.collisions:
                        console.print(f"    [yellow]⚠ {len(r.collisions)} potential collision(s):[/yellow]")
                        for c in r.collisions:
                            console.print(f"      - {c['id']}: {c['statement'][:60]}...")
    else:
        console.print(f"[red]✗[/red] Apply failed")
        for err in result.errors:
            loc = f"line {err.line}" if err.line else f"op {err.op_index}"
            console.print(f"  [{loc}] {err.op_type}: {err.message}")


@main.command()
@click.argument("scopes", nargs=-1)
@click.option("--pretty", "-p", is_flag=True, help="Pretty-print JSON output")
@click.pass_context
def snapshot(ctx, scopes: tuple, pretty: bool):
    """Read a snapshot of memory state.
    
    Combines one or more scopes into a single JSON document.
    Output is always JSON (machine-readable).
    
    \b
    Core scopes:
        pending          - Unprocessed episodes with their entities
        conflicts        - Open conflicts with full fact details
        health           - Actionable memory issues summary
        stats            - Memory statistics
    \b
    Browse scopes:
        concepts[:<n>]   - All concepts (default 50)
        episodes[:<n>]   - Recent episodes (default 20)
        entities[:<type>]- All entities with mention counts
        topics           - All topics with stats
        decisions[:<n>]  - Recent decision episodes (default 20)
        questions[:<n>]  - Recent question episodes (default 20)
    \b
    Detail scopes:
        entity:<id>      - Episodes and concepts for an entity
        topic:<id>       - Episodes and concepts for a topic
        concept:<id>     - Concept detail with facts and supersession history
        recent:<n>       - N most recent episodes (default: 10)
        query:<text>     - Semantic search results
    
    Examples:
        remind snapshot pending conflicts health
        remind snapshot entity:concept:caching
        remind snapshot concepts episodes:10
        remind snapshot topics entities:person
        remind snapshot "query:authentication issues"
    """
    from remind.snapshot import SnapshotEngine
    
    if not scopes:
        scopes = ("stats",)
    
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    
    engine = SnapshotEngine(
        store=memory.store,
        embedding=memory.embedding,
    )
    
    async def _snapshot():
        return await engine.snapshot(list(scopes))
    
    result = run_async(_snapshot())
    
    if pretty:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, default=str))


@main.command()
@click.argument("query", required=False, default=None)
@click.option("-k", default=3, help="Number of concepts to retrieve")
@click.option("--episode-k", "-ek", default=5, help="Number of episodes to retrieve via direct vector search")
@click.option("--context", "-c", help="Additional context for search")
@click.option("--entity", "-e", help="Retrieve by entity ID instead of semantic search")
@click.option("--topic", help="Restrict recall to this topic")
@click.option("--as-of", "as_of", default=None,
              help="Show facts valid at this point in time (ISO date/datetime, e.g. 2026-01-15)")
@click.option("--raw", is_flag=True, help="Show raw concept data")
@click.pass_context
def recall(ctx, query: Optional[str], k: int, episode_k: int, context: Optional[str], 
           entity: Optional[str], topic: Optional[str], as_of: Optional[str], raw: bool):
    """Retrieve relevant concepts for a query.
    
    By default, does semantic search across concepts. 
    Use --entity to retrieve by entity ID instead.
    Use --episode-k to also include direct episode vector matches.
    Use --topic to restrict to a specific knowledge area.
    Use --as-of to see the facts that were valid at a past point in time.
    
    Examples:
        remind recall "authentication issues"
        remind recall --topic architecture "database design"
        remind recall --episode-k 10 "authentication issues"
        remind recall --as-of 2026-01-15 "cache configuration"
        remind recall --entity file:src/auth.ts
        remind recall -e "person:alice"
    """
    if not query and not entity:
        raise click.UsageError("Either QUERY or --entity must be provided.")

    if as_of:
        from datetime import datetime as _dt
        try:
            _dt.fromisoformat(as_of)
        except ValueError:
            raise click.UsageError(f"--as-of must be an ISO date/datetime, got: {as_of}")

    from remind.config import load_config

    config = load_config(project_dir=Path.cwd())
    # The persistent recall worker doesn't carry as_of; use one-shot recall for time-travel queries
    use_recall_worker = bool(
        config.reranking_enabled
        and getattr(config, "cli_recall_worker_enabled", True)
        and as_of is None
    )

    result = None
    if use_recall_worker:
        try:
            result = _run_recall_via_worker(
                ctx,
                query=query,
                k=k,
                episode_k=episode_k,
                context=context,
                entity=entity,
                topic=topic,
                raw=raw,
            )
        except Exception as e:
            reason = str(e).strip()
            if reason.lower() in {"recall worker unavailable", "no response from recall worker"}:
                console.print(
                    "[dim]Recall worker is still starting up; using one-shot recall for this request.[/dim]"
                )
            else:
                console.print(
                    f"[dim]Recall worker unavailable ({reason}); using one-shot recall for this request.[/dim]"
                )

    if result is None:
        memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

        async def _recall():
            return await memory.recall(
                query,
                k=k,
                context=context,
                entity=entity,
                raw=raw,
                episode_k=episode_k,
                topic=topic,
                as_of=as_of,
            )

        result = run_async(_recall())
    
    if entity:
        # Entity-based result
        if raw:
            # Show episodes as table
            table = Table(title=f"Episodes mentioning '{entity}'")
            table.add_column("ID", style="cyan")
            table.add_column("Type", style="yellow")
            table.add_column("Content")
            
            for ep in result:
                content = ep.content[:60] + "..." if len(ep.content) > 60 else ep.content
                table.add_row(ep.id, ep.episode_type, content)
            
            console.print(table)
        else:
            console.print(Panel(result, title=f"Memory: {entity}", border_style="cyan"), markup=False)
    elif raw:
        # Show detailed concept view
        for ac in result:
            c = ac.concept
            panel_content = f"""[bold]{c.summary}[/bold]

Confidence: {c.confidence:.2f}
Instances: {c.instance_count}
Activation: {ac.activation:.3f} ({ac.source})
Tags: {', '.join(c.tags) if c.tags else 'none'}
Conditions: {c.conditions or 'none'}
Exceptions: {', '.join(c.exceptions) if c.exceptions else 'none'}"""
            
            if c.relations:
                panel_content += "\n\nRelations:"
                for rel in c.relations[:5]:
                    panel_content += f"\n  → {rel.type.value} [{rel.target_id}] (str: {rel.strength:.2f})"
            
            console.print(Panel(panel_content, title=f"[cyan]{c.id}[/cyan]", border_style="dim"))
    else:
        # Show formatted output (markup=False so [observation] etc. aren't eaten by Rich)
        console.print(Panel(result, title="Retrieved Memory", border_style="cyan"), markup=False)


@main.group(invoke_without_command=True)
@click.pass_context
def conflicts(ctx):
    """Triage detected memory conflicts (contradictions).

    Without a subcommand, lists open conflicts.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(conflicts_list)


@conflicts.command("list")
@click.option("--status", default="open", type=click.Choice(["open", "resolved", "dismissed", "all"]),
              help="Filter by status (default: open)")
@click.option("--kind", default=None, type=click.Choice(["fact", "concept"]), help="Filter by kind")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def conflicts_list(ctx, status: str = "open", kind: Optional[str] = None,
                   as_json: bool = False, as_table: bool = False, as_compact_json: bool = False):
    """List conflicts (open by default)."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)
    conflict_list = memory.list_conflicts(status=None if status == "all" else status, kind=kind)

    def _fact_line(fact_id):
        if not fact_id:
            return None
        fact = memory.store.get_fact(fact_id)
        if not fact:
            return None
        prov = f" (by {fact.asserted_by})" if fact.asserted_by else ""
        return f"[{fact.id}] {fact.statement}{prov}"

    if out_fmt == "json":
        _emit_cli_json({"conflicts": [c.to_dict() for c in conflict_list]})
        return
    if out_fmt == "compact_json":
        _emit_cli_json({
            "format": "compact-json",
            "conflicts": [
                {"id": c.id, "title": f"{c.kind} conflict ({c.severity})", "summary": c.description}
                for c in conflict_list
            ],
        })
        return

    if not conflict_list:
        console.print(f"[dim]No {status} conflicts.[/dim]")
        return

    for c in conflict_list:
        lines = [f"[bold]{c.description}[/bold]"]
        lines.append(f"kind: {c.kind}  severity: {c.severity}  detected: {c.created_at.strftime('%Y-%m-%d')}")
        if c.kind == "fact":
            for label, fact_id in (("A", c.fact_a_id), ("B", c.fact_b_id)):
                line = _fact_line(fact_id)
                if line:
                    lines.append(f"{label}: {line}")
        if c.status != "open":
            resolution = f"status: {c.status}"
            if c.winning_fact_id:
                resolution += f"  winner: {c.winning_fact_id}"
            if c.resolution_note:
                resolution += f"  note: {c.resolution_note}"
            lines.append(resolution)
        console.print(Panel("\n".join(lines), title=f"[cyan]{c.id}[/cyan]", border_style="yellow" if c.status == "open" else "dim"))

    if status == "open" and conflict_list:
        console.print("[dim]Resolve with: remind conflicts resolve <id> <winning_fact_id>[/dim]")
        console.print("[dim]Dismiss with: remind conflicts dismiss <id> --note \"both true, different contexts\"[/dim]")


@conflicts.command("resolve")
@click.argument("conflict_id")
@click.argument("winning_fact_id", required=False, default=None)
@click.option("--note", default=None, help="Why this resolution is correct")
@click.option("--by", "resolved_by", default=None, help="Who decided (e.g. alice)")
@click.pass_context
def conflicts_resolve(ctx, conflict_id: str, winning_fact_id: Optional[str],
                      note: Optional[str], resolved_by: Optional[str]):
    """Resolve a conflict by naming the winning fact.

    The losing fact is superseded (kept as history) and the resolution
    is recorded as a decision episode.
    """
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    async def _resolve():
        return await memory.resolve_conflict(
            conflict_id, winning_fact_id=winning_fact_id, note=note, resolved_by=resolved_by,
        )

    try:
        conflict = run_async(_resolve())
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        return
    console.print(f"[green]✓[/green] Conflict [cyan]{conflict.id}[/cyan] resolved.")
    if winning_fact_id:
        console.print(f"  Winner: {winning_fact_id} (loser superseded, kept as history)")


@conflicts.command("dismiss")
@click.argument("conflict_id")
@click.option("--note", default=None, help="Why this isn't a real contradiction")
@click.option("--by", "resolved_by", default=None, help="Who decided")
@click.pass_context
def conflicts_dismiss(ctx, conflict_id: str, note: Optional[str], resolved_by: Optional[str]):
    """Dismiss a conflict: both claims valid (e.g. different contexts)."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    async def _dismiss():
        return await memory.dismiss_conflict(conflict_id, note=note, resolved_by=resolved_by)

    try:
        conflict = run_async(_dismiss())
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        return
    console.print(f"[green]✓[/green] Conflict [cyan]{conflict.id}[/cyan] dismissed. Both facts remain active.")


@main.group()
@click.pass_context
def topics(ctx):
    """Browse and manage knowledge topics."""
    pass


@topics.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def topics_list(ctx, as_json: bool, as_table: bool, as_compact_json: bool):
    """List all topics with stats."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)
    topic_list = memory.list_topics()

    if not topic_list:
        if out_fmt == "json":
            _emit_cli_json({"topics": []})
        elif out_fmt == "compact_json":
            _emit_cli_json({"format": "compact-json", "topics": []})
        else:
            console.print("[dim]No topics found. Use 'remind topics create' to add one.[/dim]")
        return

    if out_fmt == "json":
        _emit_cli_json({"topics": topic_list})
        return
    if out_fmt == "compact_json":
        _emit_cli_json(
            {
                "format": "compact-json",
                "topics": [_compact_topic_row(t) for t in topic_list],
            }
        )
        return

    table = Table(title="Topics")
    table.add_column("ID", style="blue")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Episodes", justify="right")
    table.add_column("Concepts", justify="right")
    table.add_column("Latest Activity")

    for t in topic_list:
        table.add_row(
            t["id"],
            t["name"],
            (t.get("description") or "")[:50],
            str(t["episode_count"]),
            str(t["concept_count"]),
            t.get("latest_activity") or "",
        )

    console.print(table)


@topics.command("create")
@click.argument("name")
@click.option("--description", "-d", default="", help="Description of the topic")
@click.pass_context
def topics_create(ctx, name: str, description: str):
    """Create a new topic."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    try:
        topic = memory.create_topic(name, description=description)
        console.print(f"[green]✓[/green] Created topic [blue]{topic.id}[/blue] ({topic.name})")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")


@topics.command("update")
@click.argument("topic_id")
@click.option("--name", "-n", default=None, help="New display name")
@click.option("--description", "-d", default=None, help="New description")
@click.pass_context
def topics_update(ctx, topic_id: str, name: Optional[str], description: Optional[str]):
    """Update an existing topic."""
    if name is None and description is None:
        raise click.UsageError("At least --name or --description must be provided.")
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    updated = memory.update_topic(topic_id, name=name, description=description)
    if not updated:
        console.print(f"[red]Topic '{topic_id}' not found.[/red]")
    else:
        console.print(f"[green]✓[/green] Updated topic [blue]{updated.id}[/blue] ({updated.name})")


@topics.command("delete")
@click.argument("topic_id")
@click.pass_context
def topics_delete(ctx, topic_id: str):
    """Delete a topic (only if no episodes/concepts reference it)."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    try:
        if memory.delete_topic(topic_id):
            console.print(f"[green]✓[/green] Deleted topic [blue]{topic_id}[/blue]")
        else:
            console.print(f"[red]Topic '{topic_id}' not found.[/red]")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")


@topics.command("overview")
@click.argument("topic_id")
@click.option("-k", default=5, help="Number of top concepts to show")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def topics_overview(ctx, topic_id: str, k: int, as_json: bool, as_table: bool, as_compact_json: bool):
    """Show top concepts for a topic."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)
    topic = memory.get_topic(topic_id)
    concepts = memory.get_topic_overview(topic_id, k=k)

    if out_fmt == "json":
        tdict = topic.to_dict() if topic else {"id": topic_id}
        _emit_cli_json(
            {
                "topic": tdict,
                "concepts": [_concept_to_json_dict(c) for c in concepts],
            }
        )
        return
    if out_fmt == "compact_json":
        t_compact = (
            {"id": topic.id, "title": topic.name, "summary": topic.description or ""}
            if topic
            else {"id": topic_id, "title": "", "summary": ""}
        )
        _emit_cli_json(
            {
                "format": "compact-json",
                "topic": t_compact,
                "concepts": [_compact_concept(c) for c in concepts],
            }
        )
        return

    if not concepts:
        console.print(f"[dim]No concepts found for topic '{topic_id}'.[/dim]")
        return

    label = topic.name if topic else topic_id
    console.print(f"\n[bold blue]Topic: {label}[/bold blue]\n")
    if topic and topic.description:
        console.print(f"  [dim]{topic.description}[/dim]\n")
    for c in concepts:
        updated = c.updated_at.strftime("%Y-%m-%d %H:%M")
        title = f" {c.title}" if c.title else ""
        console.print(
            f"  [cyan][{c.id}][/cyan]{title} "
            f"(confidence: {c.confidence:.2f}, instances: {c.instance_count}, updated: {updated})"
        )
        console.print(f"    {c.summary}")
        if c.conditions:
            console.print(f"    → Applies when: {c.conditions}")
        console.print()

@main.command("embed-episodes")
@click.option("--batch-size", default=50, help="Number of episodes to embed per batch")
@click.pass_context
def embed_episodes(ctx, batch_size: int):
    """Backfill embeddings for episodes that don't have them yet.

    Useful for vectorizing episodes in existing databases created before
    episode embedding was enabled.
    """
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    async def _embed():
        return await memory.embed_episodes(batch_size=batch_size)

    console.print("[cyan]Embedding un-embedded episodes...[/cyan]")
    count = run_async(_embed())
    console.print(f"[green]✓[/green] Embedded {count} episodes")


@main.command("re-embed")
@click.option("--episodes", is_flag=True, help="Re-embed episodes only")
@click.option("--concepts", is_flag=True, help="Re-embed concepts only")
@click.option("--entities", is_flag=True, help="Re-embed entities only")
@click.option("--all", "all_targets", is_flag=True, help="Re-embed episodes, concepts, and entities (default)")
@click.option("--batch-size", default=50, help="Number of records to embed per batch")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def re_embed(ctx, episodes: bool, concepts: bool, entities: bool, all_targets: bool, batch_size: int, yes: bool):
    """Recompute stored embeddings using the current embedding provider.

    Use this when embedding model or dimensions change and existing vectors
    need to be rewritten.
    """
    if batch_size <= 0:
        raise click.ClickException("--batch-size must be greater than 0.")

    if all_targets:
        include_episodes = True
        include_concepts = True
        include_entities = True
    elif episodes or concepts or entities:
        include_episodes = episodes
        include_concepts = concepts
        include_entities = entities
    else:
        include_episodes = True
        include_concepts = True
        include_entities = True

    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    plan = run_async(memory.get_reembed_plan(
        include_episodes=include_episodes,
        include_concepts=include_concepts,
        include_entities=include_entities,
    ))

    target_parts = []
    if include_episodes:
        target_parts.append(f"{plan['episodes']} episodes")
    if include_concepts:
        target_parts.append(f"{plan['concepts']} concepts")
    if include_entities:
        target_parts.append(f"{plan['entities']} entities")
    target_summary = ", ".join(target_parts)

    console.print("[bold cyan]Re-embed preview[/bold cyan]")
    console.print(f"  Targets: {target_summary}")
    console.print(f"  Dimensions: {plan['stored_dimensions']} -> {plan['target_dimensions']}")

    if not yes:
        if not sys.stdin.isatty():
            console.print("[red]Error: Use -y/--yes flag for non-interactive re-embedding[/red]")
            raise SystemExit(1)
        proceed = click.confirm("Proceed with re-embedding?", default=True)
        if not proceed:
            console.print("[yellow]Cancelled. No changes made.[/yellow]")
            return

    result = run_async(memory.reembed(
        include_episodes=include_episodes,
        include_concepts=include_concepts,
        include_entities=include_entities,
        batch_size=batch_size,
    ))
    console.print("[green]✓ Re-embed complete[/green]")
    console.print(f"  Re-embedded concepts: {result['concepts_embedded']}")
    console.print(f"  Re-embedded episodes: {result['episodes_embedded']}")
    console.print(f"  Re-embedded entities: {result['entities_embedded']}")
    console.print(f"  Dimensions: {result['stored_dimensions']} -> {result['target_dimensions']}")



@main.command()
@click.argument("concept_id", required=False)
@click.option("--episodes", "-e", is_flag=True, help="Show recent episodes instead")
@click.option("--limit", "-n", default=10, help="Number of items to show")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def inspect(
    ctx,
    concept_id: Optional[str],
    episodes: bool,
    limit: int,
    as_json: bool,
    as_table: bool,
    as_compact_json: bool,
):
    """Inspect concepts or episodes."""
    from remind.store import SQLAlchemyMemoryStore
    store = SQLAlchemyMemoryStore(ctx.obj["db"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)

    if episodes:
        # Show recent episodes
        recent = store.get_recent_episodes(limit=limit)

        if not recent:
            if out_fmt == "json":
                _emit_cli_json([])
            elif out_fmt == "compact_json":
                _emit_cli_json({"format": "compact-json", "items": []})
            else:
                console.print("[yellow]No episodes in memory[/yellow]")
            return

        if out_fmt == "json":
            _emit_cli_json([ep.to_dict() for ep in recent])
            return
        if out_fmt == "compact_json":
            _emit_cli_json(
                {
                    "format": "compact-json",
                    "items": [_compact_episode(ep) for ep in recent],
                }
            )
            return

        table = Table(title="Recent Episodes")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Timestamp", style="dim")
        table.add_column("Content")
        table.add_column("Entities", style="dim")
        table.add_column("Status", style="yellow")
        
        for ep in recent:
            status = "✓" if ep.consolidated else "pending"
            content = ep.content[:50] + "..." if len(ep.content) > 50 else ep.content
            entities = ", ".join(ep.entity_ids[:2]) if ep.entity_ids else ""
            if len(ep.entity_ids) > 2:
                entities += f" +{len(ep.entity_ids)-2}"
            table.add_row(
                ep.id, 
                ep.episode_type[:3],  # Shortened type
                ep.timestamp.strftime("%Y-%m-%d %H:%M"), 
                content, 
                entities,
                status
            )
        
        console.print(table)
        return

    if concept_id:
        # Show specific concept
        concept = store.get_concept(concept_id)

        if not concept:
            if out_fmt == "json" or out_fmt == "compact_json":
                _emit_cli_json(None)
            else:
                console.print(f"[red]Concept {concept_id} not found[/red]")
            return

        if out_fmt == "json":
            _emit_cli_json(_concept_to_json_dict(concept))
            return
        if out_fmt == "compact_json":
            _emit_cli_json({"format": "compact-json", "item": _compact_concept(concept)})
            return

        tree = Tree(f"[bold cyan]{concept_id}[/bold cyan]")
        if concept.title:
            tree.add(f"[bold]Title:[/bold] {concept.title}")
        tree.add(f"[bold]Summary:[/bold] {concept.summary}")
        tree.add(f"Confidence: {concept.confidence:.2f}")
        tree.add(f"Instances: {concept.instance_count}")
        tree.add(f"Created: {concept.created_at.strftime('%Y-%m-%d %H:%M')}")
        tree.add(f"Updated: {concept.updated_at.strftime('%Y-%m-%d %H:%M')}")
        
        if concept.conditions:
            tree.add(f"Conditions: {concept.conditions}")
        
        if concept.exceptions:
            exc_branch = tree.add("Exceptions")
            for exc in concept.exceptions:
                exc_branch.add(exc)
        
        if concept.tags:
            tree.add(f"Tags: {', '.join(concept.tags)}")
        
        if concept.relations:
            rel_branch = tree.add("Relations")
            for rel in concept.relations:
                target = store.get_concept(rel.target_id)
                target_summary = target.summary[:40] + "..." if target else "[unknown]"
                rel_branch.add(f"[yellow]{rel.type.value}[/yellow] → [{rel.target_id}] {target_summary} (str: {rel.strength:.2f})")
        
        if concept.source_episodes:
            src_branch = tree.add("Source Episodes")
            for ep_id in concept.source_episodes[:5]:
                src_branch.add(f"[dim]{ep_id}[/dim]")
            if len(concept.source_episodes) > 5:
                src_branch.add(f"[dim]... and {len(concept.source_episodes) - 5} more[/dim]")
        
        console.print(tree)
    else:
        # List all concepts
        concepts = store.get_all_concepts()

        if not concepts:
            if out_fmt == "json":
                _emit_cli_json([])
            elif out_fmt == "compact_json":
                _emit_cli_json({"format": "compact-json", "items": []})
            else:
                console.print("[yellow]No concepts in memory[/yellow]")
            return

        if out_fmt == "json":
            _emit_cli_json([_concept_to_json_dict(c) for c in concepts])
            return
        if out_fmt == "compact_json":
            _emit_cli_json(
                {
                    "format": "compact-json",
                    "items": [_compact_concept(c) for c in concepts],
                }
            )
            return

        table = Table(title=f"All Concepts ({len(concepts)})")
        table.add_column("ID", style="cyan")
        table.add_column("Title")
        table.add_column("Summary")
        table.add_column("Conf", justify="right")
        table.add_column("N", justify="right")
        table.add_column("Relations", justify="right")
        table.add_column("Tags", style="dim")

        for c in concepts:
            title = c.title or "-"
            summary = c.summary[:40] + "..." if len(c.summary) > 40 else c.summary
            tags = ", ".join(c.tags[:3]) if c.tags else ""
            if len(c.tags) > 3:
                tags += "..."
            table.add_row(
                c.id,
                title,
                summary,
                f"{c.confidence:.2f}",
                str(c.instance_count),
                str(len(c.relations)),
                tags,
            )
        
        console.print(table)


@main.command()
@click.pass_context
def stats(ctx):
    """Show memory statistics."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    stats = memory.get_stats()
    
    # Consolidation status
    pending = stats.get('unconsolidated_episodes', 0)
    unextracted = stats.get('unextracted_episodes', 0)
    threshold = stats.get('consolidation_threshold', 10)
    auto = "enabled" if stats.get('auto_consolidate') else "disabled"
    should_consolidate = "[green]ready[/green]" if stats.get('should_consolidate') else "[dim]not needed[/dim]"
    last_consolidation = stats.get('last_consolidation') or "never"
    
    # Entity info
    entity_count = stats.get('entities', 0)
    mention_count = stats.get('mentions', 0)
    entity_types = stats.get('entity_types', {})
    episode_types = stats.get('episode_types', {})
    
    console.print(Panel(
        f"""[bold]Memory Statistics[/bold]

[cyan]Concepts:[/cyan] {stats['concepts']}
[cyan]Episodes:[/cyan] {stats['episodes']}
[cyan]Relations:[/cyan] {stats['relations']}
[cyan]Entities:[/cyan] {entity_count}
[cyan]Mentions:[/cyan] {mention_count}

[bold]Consolidation[/bold]
[cyan]Pending episodes:[/cyan] {pending}
[cyan]Unextracted episodes:[/cyan] {unextracted}
[cyan]Threshold:[/cyan] {threshold}
[cyan]Auto-consolidate:[/cyan] {auto}
[cyan]Should consolidate:[/cyan] {should_consolidate}
[cyan]Last consolidation:[/cyan] {last_consolidation}

[bold]Episode Types:[/bold]
{json.dumps(episode_types, indent=2)}

[bold]Entity Types:[/bold]
{json.dumps(entity_types, indent=2)}

[bold]Relation Distribution:[/bold]
{json.dumps(stats.get('relation_types', {}), indent=2)}

[bold]Providers:[/bold]
  LLM: {stats.get('llm_provider', 'unknown')}
  Embedding: {stats.get('embedding_provider', 'unknown')}

[bold]Decay:[/bold]
  Enabled: {'yes' if stats.get('decay_enabled', True) else 'no'}
  Recall count: {stats.get('recall_count', 0)}
  Recalls since last decay: {stats.get('recalls_since_last_decay', 0)}
  Next decay at: {stats.get('next_decay_at', 'N/A')}
  Decay interval: {stats.get('decay_interval', 20)}
  Decay rate: {stats.get('decay_rate', 0.1)}
  Concepts with decay: {stats.get('concepts_with_decay', 0)}
  Avg decay factor: {stats.get('avg_decay_factor', 1.0)}
  Min decay factor: {stats.get('min_decay_factor', 1.0)}

[bold]Database:[/bold] {ctx.obj['db']}
""",
        title="Memory Stats",
        border_style="cyan"
    ))


@main.command("types")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def episode_types_cmd(ctx, as_json: bool, as_table: bool, as_compact_json: bool):
    """Show configured episode types.

    Lists the episode types enabled for this project/environment,
    resolved from env vars, project config, global config, or defaults.
    """
    from remind.config import load_config, DEFAULT_EPISODE_TYPES
    from remind.models import EpisodeType

    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)
    config = load_config(project_dir=Path.cwd())
    configured = config.episode_types
    builtin_values = {e.value for e in EpisodeType}
    disabled = [t for t in DEFAULT_EPISODE_TYPES if t not in configured]

    if out_fmt == "json":
        rows = [
            {"type": t, "builtin": t in builtin_values}
            for t in configured
        ]
        _emit_cli_json(
            {
                "configured": rows,
                "disabled_defaults": disabled,
            }
        )
        return
    if out_fmt == "compact_json":
        rows = [
            {
                "id": t,
                "title": t,
                "summary": "builtin" if t in builtin_values else "custom",
            }
            for t in configured
        ]
        _emit_cli_json(
            {
                "format": "compact-json",
                "configured": rows,
                "disabled_defaults": disabled,
            }
        )
        return

    table = Table(title="Configured Episode Types", box=box.SIMPLE_HEAVY)
    table.add_column("Type", style="cyan")
    table.add_column("Built-in", style="dim")

    for t in configured:
        is_builtin = "yes" if t in builtin_values else "custom"
        table.add_row(t, is_builtin)

    console.print(table)

    if disabled:
        console.print(f"\n[dim]Disabled defaults: {', '.join(disabled)}[/dim]")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Structured JSON with format marker")
@click.pass_context
def status(ctx, as_json: bool, as_table: bool, as_compact_json: bool):
    """Show consolidation and ingestion processing status.

    Quick view of what's currently happening: running workers,
    pending episodes, queued ingest chunks.
    """
    from remind.background import (
        build_recall_worker_key,
        is_consolidation_running,
        is_ingest_running,
        is_recall_running,
        get_ingest_queue_dir,
    )
    from remind.config import load_config

    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)
    db_path = ctx.obj["db"]
    memory = get_memory(db_path, ctx.obj["embedding"])
    stats_data = memory.get_stats()
    config = load_config(project_dir=Path.cwd())

    # Consolidation status
    remind_dir = ctx.obj.get("remind_dir")
    consolidating = is_consolidation_running(db_path, remind_dir=remind_dir)
    pending = stats_data.get("unconsolidated_episodes", 0)
    unextracted = stats_data.get("unextracted_episodes", 0)
    threshold = stats_data.get("consolidation_threshold", 10)
    last = stats_data.get("last_consolidation") or "never"

    # Ingest status
    ingesting = is_ingest_running(db_path, remind_dir=remind_dir)
    queue_dir = get_ingest_queue_dir(db_path, remind_dir=remind_dir)
    queued_chunks = sorted(queue_dir.glob("*.json")) if queue_dir.is_dir() else []
    queued_count = len(queued_chunks)

    # Build output
    lines = []

    # Workers
    if consolidating:
        lines.append("[bold green]● Consolidation[/bold green]  [green]running[/green]")
    elif ingesting:
        lines.append("[bold green]● Consolidation[/bold green]  [green]running[/green] [dim](via ingest)[/dim]")
    else:
        lines.append("[bold dim]○ Consolidation[/bold dim]  [dim]idle[/dim]")

    if ingesting:
        lines.append("[bold green]● Ingest worker[/bold green]  [green]running[/green]")
    else:
        lines.append("[bold dim]○ Ingest worker[/bold dim]  [dim]idle[/dim]")

    if config.reranking_enabled and getattr(config, "cli_recall_worker_enabled", True):
        worker_key = build_recall_worker_key(
            db_url=db_path,
            embedding_provider=ctx.obj["embedding"],
            config_fingerprint=_recall_config_fingerprint(config),
        )
        recall_running = is_recall_running(
            db_path,
            worker_key=worker_key,
            remind_dir=ctx.obj.get("remind_dir"),
        )
        if recall_running:
            lines.append("[bold green]● Recall worker[/bold green]  [green]running[/green]")
        else:
            lines.append("[bold dim]○ Recall worker[/bold dim]  [dim]idle[/dim] [dim](auto-starts on recall)[/dim]")
    elif config.reranking_enabled:
        lines.append("[bold dim]○ Recall worker[/bold dim]  [dim]disabled by config[/dim]")
    else:
        lines.append("[bold dim]○ Recall worker[/bold dim]  [dim]inactive (reranking disabled)[/dim]")

    lines.append("")

    # Episodes
    lines.append(f"[cyan]Pending consolidation:[/cyan]  {pending}")
    lines.append(f"[cyan]Pending extraction:[/cyan]    {unextracted}")
    lines.append(f"[cyan]Threshold:[/cyan]             {threshold}")
    if pending >= threshold:
        lines.append("[yellow]→ Ready to consolidate[/yellow]")
    lines.append(f"[cyan]Last consolidation:[/cyan]    {last}")

    lines.append("")

    # Ingest queue
    lines.append(f"[cyan]Queued ingest chunks:[/cyan]  {queued_count}")
    if queued_chunks:
        total_chars = 0
        for p in queued_chunks:
            try:
                data = json.loads(p.read_text())
                total_chars += len(data.get("chunk", ""))
            except Exception:
                pass
        if total_chars:
            lines.append(f"[cyan]Queued text:[/cyan]           ~{total_chars:,} chars")

    lines.append("")

    # Totals
    lines.append(f"[cyan]Total episodes:[/cyan]        {stats_data.get('episodes', 0)}")
    lines.append(f"[cyan]Total concepts:[/cyan]        {stats_data.get('concepts', 0)}")
    lines.append(f"[cyan]Total entities:[/cyan]        {stats_data.get('entities', 0)}")

    if out_fmt in ("json", "compact_json"):
        recall_json: Optional[dict] = None
        if config.reranking_enabled and getattr(config, "cli_recall_worker_enabled", True):
            worker_key = build_recall_worker_key(
                db_url=db_path,
                embedding_provider=ctx.obj["embedding"],
                config_fingerprint=_recall_config_fingerprint(config),
            )
            recall_json = {
                "enabled": True,
                "running": is_recall_running(
                    db_path,
                    worker_key=worker_key,
                    remind_dir=ctx.obj.get("remind_dir"),
                ),
            }
        elif config.reranking_enabled:
            recall_json = {"enabled": False, "reason": "disabled_by_config"}
        else:
            recall_json = {"enabled": False, "reason": "reranking_disabled"}

        queued_chars = 0
        if queued_chunks:
            for p in queued_chunks:
                try:
                    data = json.loads(p.read_text())
                    queued_chars += len(data.get("chunk", ""))
                except Exception:
                    pass

        payload: dict[str, Any] = {
            "database": db_path,
            "consolidation_running": consolidating or ingesting,
            "ingest_worker_running": ingesting,
            "recall_worker": recall_json,
            "pending_consolidation": pending,
            "pending_extraction": unextracted,
            "consolidation_threshold": threshold,
            "ready_to_consolidate": pending >= threshold,
            "last_consolidation": last,
            "queued_ingest_chunks": queued_count,
            "queued_ingest_chars_approx": queued_chars,
            "totals": {
                "episodes": stats_data.get("episodes", 0),
                "concepts": stats_data.get("concepts", 0),
                "entities": stats_data.get("entities", 0),
            },
        }
        if out_fmt == "compact_json":
            payload = {"format": "compact-json", **payload}
        _emit_cli_json(payload)
        return

    console.print(Panel(
        "\n".join(lines),
        title="Processing Status",
        subtitle=f"[dim]{db_path}[/dim]",
        border_style="cyan",
    ))


@main.command("export")
@click.argument("file")
@click.pass_context
def export_cmd(ctx, file: str):
    """Export memory to JSON file."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    
    data = memory.export_memory(file)
    console.print(f"[green]✓[/green] Exported {data['stats']['concepts']} concepts and {data['stats']['episodes']} episodes to [cyan]{file}[/cyan]")


@main.command("import")
@click.argument("file")
@click.pass_context
def import_cmd(ctx, file: str):
    """Import memory from JSON file."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    
    result = memory.import_memory(file)
    console.print(f"[green]✓[/green] Imported {result['concepts_imported']} concepts, {result['episodes_imported']} episodes from [cyan]{file}[/cyan]")


@main.command()
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def search(ctx, query: str, as_json: bool, as_table: bool, as_compact_json: bool):
    """Search concepts by tag or keyword."""
    from remind.store import SQLAlchemyMemoryStore
    store = SQLAlchemyMemoryStore(ctx.obj["db"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)

    concepts = store.get_all_concepts()
    query_lower = query.lower()

    matches = []
    for c in concepts:
        # Search in summary, tags, conditions
        score = 0
        if query_lower in c.summary.lower():
            score += 2
        if any(query_lower in tag.lower() for tag in c.tags):
            score += 3
        if c.conditions and query_lower in c.conditions.lower():
            score += 1

        if score > 0:
            matches.append((c, score))

    matches.sort(key=lambda x: x[1], reverse=True)

    if not matches:
        if out_fmt == "json":
            _emit_cli_json({"query": query, "matches": []})
        elif out_fmt == "compact_json":
            _emit_cli_json({"format": "compact-json", "query": query, "matches": []})
        else:
            console.print(f"[yellow]No concepts matching '{query}'[/yellow]")
        return

    if out_fmt == "json":
        _emit_cli_json(
            {
                "query": query,
                "matches": [
                    {"score": sc, "concept": _concept_to_json_dict(c)}
                    for c, sc in matches[:10]
                ],
            }
        )
        return
    if out_fmt == "compact_json":
        _emit_cli_json(
            {
                "format": "compact-json",
                "query": query,
                "matches": [
                    {"score": sc, "concept": _compact_concept(c)}
                    for c, sc in matches[:10]
                ],
            }
        )
        return

    table = Table(title=f"Search Results for '{query}'")
    table.add_column("ID", style="cyan")
    table.add_column("Summary")
    table.add_column("Score", justify="right")
    
    for c, score in matches[:10]:
        summary = c.summary[:60] + "..." if len(c.summary) > 60 else c.summary
        table.add_row(c.id, summary, str(score))
    
    console.print(table)


# ============================================================================
# Entity/Extraction Commands (v2 schema)
# ============================================================================

@main.command()
@click.argument("entity_id", required=False)
@click.option("--type", "-t", "entity_type", help="Filter by entity type (file, function, person, etc.)")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def entities(
    ctx,
    entity_id: Optional[str],
    entity_type: Optional[str],
    as_json: bool,
    as_table: bool,
    as_compact_json: bool,
):
    """List entities or show details for a specific entity."""
    from remind.store import SQLAlchemyMemoryStore
    from remind.models import EntityType
    store = SQLAlchemyMemoryStore(ctx.obj["db"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)

    if entity_id:
        # Show specific entity and its mentions
        entity = store.get_entity(entity_id)

        if not entity:
            if out_fmt == "json" or out_fmt == "compact_json":
                _emit_cli_json(None)
            else:
                console.print(f"[red]Entity {entity_id} not found[/red]")
            return

        # Get episodes mentioning this entity
        episodes = store.get_episodes_mentioning(entity_id, limit=20)

        if out_fmt == "json":
            _emit_cli_json(
                {
                    "entity": entity.to_dict(),
                    "episodes": [ep.to_dict() for ep in episodes],
                }
            )
            return
        if out_fmt == "compact_json":
            _emit_cli_json(
                {
                    "format": "compact-json",
                    "entity": _compact_entity(entity),
                    "episodes": [_compact_episode(ep) for ep in episodes],
                }
            )
            return

        tree = Tree(f"[bold cyan]{entity.id}[/bold cyan]")
        tree.add(f"[bold]Type:[/bold] {entity.type.value}")
        if entity.display_name:
            tree.add(f"[bold]Display Name:[/bold] {entity.display_name}")
        tree.add(f"Created: {entity.created_at.strftime('%Y-%m-%d %H:%M')}")
        
        if episodes:
            ep_branch = tree.add(f"Mentioned in {len(episodes)} episodes")
            for ep in episodes[:10]:
                content = ep.content[:50] + "..." if len(ep.content) > 50 else ep.content
                ep_branch.add(f"[dim]{ep.id}[/dim] {content}")
            if len(episodes) > 10:
                ep_branch.add(f"[dim]... and {len(episodes) - 10} more[/dim]")
        
        console.print(tree)
    else:
        # List all entities with mention counts
        entity_counts = store.get_entity_mention_counts()

        if not entity_counts:
            if out_fmt == "json":
                _emit_cli_json({"entities": []})
            elif out_fmt == "compact_json":
                _emit_cli_json({"format": "compact-json", "entities": []})
            else:
                console.print("[yellow]No entities in memory[/yellow]")
            return

        # Filter by type if specified
        if entity_type:
            try:
                etype = EntityType(entity_type)
                entity_counts = [(e, c) for e, c in entity_counts if e.type == etype]
            except ValueError:
                if out_fmt == "json":
                    _emit_cli_json({"error": f"Unknown entity type: {entity_type}"})
                elif out_fmt == "compact_json":
                    _emit_cli_json(
                        {
                            "format": "compact-json",
                            "error": f"Unknown entity type: {entity_type}",
                        }
                    )
                else:
                    console.print(f"[red]Unknown entity type: {entity_type}[/red]")
                    console.print(f"Valid types: {', '.join(t.value for t in EntityType)}")
                return

        if out_fmt == "json":
            _emit_cli_json(
                {
                    "entities": [
                        {"entity": e.to_dict(), "mention_count": c}
                        for e, c in entity_counts[:50]
                    ]
                }
            )
            return
        if out_fmt == "compact_json":
            rows = []
            for e, c in entity_counts[:50]:
                row = dict(_compact_entity(e))
                row["mention_count"] = c
                rows.append(row)
            _emit_cli_json({"format": "compact-json", "entities": rows})
            return

        table = Table(title=f"Entities ({len(entity_counts)})")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Name")
        table.add_column("Mentions", justify="right")
        
        for entity, count in entity_counts[:50]:
            table.add_row(
                entity.id,
                entity.type.value,
                entity.display_name or "",
                str(count),
            )
        
        console.print(table)


@main.command()
@click.argument("entity_id")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def mentions(ctx, entity_id: str, as_json: bool, as_table: bool, as_compact_json: bool):
    """Show all episodes mentioning an entity."""
    from remind.store import SQLAlchemyMemoryStore
    store = SQLAlchemyMemoryStore(ctx.obj["db"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)

    episodes = store.get_episodes_mentioning(entity_id, limit=50)

    if not episodes:
        if out_fmt == "json":
            _emit_cli_json({"episodes": []})
        elif out_fmt == "compact_json":
            _emit_cli_json({"format": "compact-json", "episodes": []})
        else:
            console.print(f"[yellow]No episodes mention '{entity_id}'[/yellow]")
        return

    if out_fmt == "json":
        _emit_cli_json({"episodes": [ep.to_dict() for ep in episodes]})
        return
    if out_fmt == "compact_json":
        _emit_cli_json(
            {
                "format": "compact-json",
                "episodes": [_compact_episode(ep) for ep in episodes],
            }
        )
        return

    table = Table(title=f"Episodes mentioning '{entity_id}'")
    table.add_column("ID", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Timestamp", style="dim")
    table.add_column("Content")
    
    for ep in episodes:
        content = ep.content[:60] + "..." if len(ep.content) > 60 else ep.content
        table.add_row(
            ep.id,
            ep.episode_type,
            ep.timestamp.strftime("%Y-%m-%d %H:%M"),
            content,
        )
    
    console.print(table)


@main.command("decisions")
@click.option("--limit", "-n", default=20, help="Number of decisions to show")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def decisions(ctx, limit: int, as_json: bool, as_table: bool, as_compact_json: bool):
    """Show decision-type episodes."""
    from remind.store import SQLAlchemyMemoryStore
    from remind.models import EpisodeType
    store = SQLAlchemyMemoryStore(ctx.obj["db"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)

    episodes = store.get_episodes_by_type(EpisodeType.DECISION.value, limit=limit)

    if not episodes:
        if out_fmt == "json":
            _emit_cli_json({"decisions": []})
        elif out_fmt == "compact_json":
            _emit_cli_json({"format": "compact-json", "decisions": []})
        else:
            console.print("[yellow]No decisions recorded yet[/yellow]")
        return

    if out_fmt == "json":
        _emit_cli_json({"decisions": [ep.to_dict() for ep in episodes]})
        return
    if out_fmt == "compact_json":
        _emit_cli_json(
            {
                "format": "compact-json",
                "decisions": [_compact_episode(ep) for ep in episodes],
            }
        )
        return

    table = Table(title="Decisions")
    table.add_column("ID", style="cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Content")
    table.add_column("Status", style="yellow")
    
    for ep in episodes:
        content = ep.content[:70] + "..." if len(ep.content) > 70 else ep.content
        status = "✓" if ep.consolidated else "pending"
        table.add_row(ep.id, ep.timestamp.strftime("%Y-%m-%d %H:%M"), content, status)
    
    console.print(table)


@main.command("questions")
@click.option("--limit", "-n", default=20, help="Number of questions to show")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def questions(ctx, limit: int, as_json: bool, as_table: bool, as_compact_json: bool):
    """Show question-type episodes (open questions, uncertainties)."""
    from remind.store import SQLAlchemyMemoryStore
    from remind.models import EpisodeType
    store = SQLAlchemyMemoryStore(ctx.obj["db"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)

    episodes = store.get_episodes_by_type(EpisodeType.QUESTION.value, limit=limit)

    if not episodes:
        if out_fmt == "json":
            _emit_cli_json({"questions": []})
        elif out_fmt == "compact_json":
            _emit_cli_json({"format": "compact-json", "questions": []})
        else:
            console.print("[yellow]No questions recorded yet[/yellow]")
        return

    if out_fmt == "json":
        _emit_cli_json({"questions": [ep.to_dict() for ep in episodes]})
        return
    if out_fmt == "compact_json":
        _emit_cli_json(
            {
                "format": "compact-json",
                "questions": [_compact_episode(ep) for ep in episodes],
            }
        )
        return

    table = Table(title="Open Questions")
    table.add_column("ID", style="cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Content")
    table.add_column("Status", style="yellow")

    for ep in episodes:
        content = ep.content[:70] + "..." if len(ep.content) > 70 else ep.content
        status = "✓" if ep.consolidated else "pending"
        table.add_row(ep.id, ep.timestamp.strftime("%Y-%m-%d %H:%M"), content, status)

    console.print(table)

@main.command("entity-relations")
@click.argument("entity_id")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal relation edges JSON")
@click.pass_context
def entity_relations(ctx, entity_id: str, as_json: bool, as_table: bool, as_compact_json: bool):
    """Show relationships for a specific entity."""
    from remind.store import SQLAlchemyMemoryStore
    store = SQLAlchemyMemoryStore(ctx.obj["db"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)

    entity = store.get_entity(entity_id)
    if not entity:
        if out_fmt == "json" or out_fmt == "compact_json":
            _emit_cli_json(None)
        else:
            console.print(f"[red]Entity {entity_id} not found[/red]")
        return

    relations = store.get_entity_relations(entity_id)

    if not relations:
        if out_fmt == "json":
            _emit_cli_json(
                {
                    "entity_id": entity_id,
                    "outgoing": [],
                    "incoming": [],
                }
            )
        elif out_fmt == "compact_json":
            _emit_cli_json(
                {
                    "format": "compact-json",
                    "entity_id": entity_id,
                    "outgoing": [],
                    "incoming": [],
                }
            )
        else:
            console.print(f"[yellow]No relationships found for '{entity_id}'[/yellow]")
        return

    # Separate outgoing and incoming relations
    outgoing = [r for r in relations if r.source_id == entity_id]
    incoming = [r for r in relations if r.target_id == entity_id]

    if out_fmt == "json":
        _emit_cli_json(
            {
                "entity_id": entity_id,
                "outgoing": [r.to_dict() for r in outgoing],
                "incoming": [r.to_dict() for r in incoming],
            }
        )
        return
    if out_fmt == "compact_json":
        _emit_cli_json(
            {
                "format": "compact-json",
                "entity_id": entity_id,
                "outgoing": [_compact_relation_out(r, store) for r in outgoing],
                "incoming": [_compact_relation_in(r, store) for r in incoming],
            }
        )
        return

    tree = Tree(f"[bold cyan]{entity_id}[/bold cyan]")

    if outgoing:
        out_branch = tree.add(f"[bold]Outgoing ({len(outgoing)})[/bold]")
        for rel in outgoing:
            target = store.get_entity(rel.target_id)
            target_name = target.display_name if target else rel.target_id
            out_branch.add(f"[green]→[/green] {rel.relation_type} [cyan]{target_name}[/cyan] ({rel.strength:.0%})")

    if incoming:
        in_branch = tree.add(f"[bold]Incoming ({len(incoming)})[/bold]")
        for rel in incoming:
            source = store.get_entity(rel.source_id)
            source_name = source.display_name if source else rel.source_id
            in_branch.add(f"[yellow]←[/yellow] {rel.relation_type} [cyan]{source_name}[/cyan] ({rel.strength:.0%})")

    console.print(tree)


@main.command()
@click.option("--port", "-p", default=8765, help="Port to run UI server on (default: 8765)")
@click.option("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
@click.option("--no-open", is_flag=True, help="Don't open browser automatically")
@click.pass_context
def ui(ctx, port: int, host: str, no_open: bool):
    """Launch the web UI with the current project's database.

    Opens a browser to the Remind web UI with the project-local database
    (<cwd>/.remind/remind.db) automatically selected.

    The UI provides:
    - Visual memory browser (concepts, episodes, entities)
    - Graph visualization of concept relationships
    - Search and recall interface
    - Memory statistics dashboard
    """
    import threading
    import time
    import webbrowser

    from remind.mcp_server import run_server_sse, register_db_alias

    db_path = ctx.obj["db"]

    register_db_alias("default", db_path)
    db_param = "default"
    ui_url = f"http://{host}:{port}/ui/?db={db_param}"

    console.print(f"[cyan]Starting Remind UI server...[/cyan]")
    console.print(f"  Database: [green]{db_path}[/green]")
    console.print(f"  URL: [link={ui_url}]{ui_url}[/link]")
    console.print()

    # Open browser after a short delay to let server start
    if not no_open:
        def open_browser():
            time.sleep(1.0)  # Wait for server to start
            webbrowser.open(ui_url)

        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()

    # Run the server (this blocks until Ctrl+C)
    try:
        run_server_sse(host=host, port=port)
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped.[/yellow]")


@main.command("skill-install")
@click.argument("names", nargs=-1)
def skill_install(names: tuple):
    """Install the Remind skills for Claude Code in the current project.

    Installs .claude/skills/<name>/SKILL.md from the bundled package data,
    keeping them in sync with the installed version. Without arguments,
    installs all skills (capture, context, curate) and removes the legacy
    monolithic 'remind' skill if present.
    """
    to_install = list(names) if names else SKILL_NAMES

    invalid = [n for n in to_install if n not in SKILL_NAMES]
    if invalid:
        console.print(f"[red]Unknown skill(s): {', '.join(invalid)}[/red]")
        console.print(f"Available: {', '.join(SKILL_NAMES)}")
        raise SystemExit(1)

    for name in to_install:
        skills_dir = Path.cwd() / ".claude" / "skills" / name
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skills_dir / "SKILL.md"
        skill_file.write_text(_read_skill(name))

        console.print(f"[green]✓[/green] Installed [cyan]{name}[/cyan] → {skill_file}")

    if not names:
        import shutil
        for legacy in LEGACY_SKILL_NAMES:
            legacy_dir = Path.cwd() / ".claude" / "skills" / legacy
            if (legacy_dir / "SKILL.md").exists():
                shutil.rmtree(legacy_dir)
                console.print(f"[dim]Removed legacy skill: {legacy}[/dim]")

    console.print("\nClaude Code will now use Remind skills in this project.")


# ============================================================================
# Session-End Capture Hook
# ============================================================================

# ============================================================================
# Update/Delete/Restore Commands
# ============================================================================

@main.command("update-episode")
@click.argument("episode_id")
@click.option("--content", "-c", help="New content text")
@click.option("--type", "-t", "episode_type",
              help="New episode type")
@click.option("--entity", "-e", "entities", multiple=True, help="New entity IDs (replaces existing)")
@click.option("--topic", default=None, help="Topic ID or name (same as remember)")
@click.option("--clear-topic", is_flag=True, help="Remove topic from this episode")
@click.pass_context
def update_episode(ctx, episode_id: str, content: Optional[str],
                   episode_type: Optional[str], entities: tuple,
                   topic: Optional[str], clear_topic: bool):
    """Update an existing episode."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    if topic is not None and clear_topic:
        console.print("[red]Use either --topic or --clear-topic, not both.[/red]")
        raise SystemExit(1)

    ep_type = episode_type or None
    entity_list = list(entities) if entities else None

    topic_kw: Optional[str] = None
    if clear_topic:
        topic_kw = ""
    elif topic is not None:
        topic_kw = topic

    updated = memory.update_episode(
        episode_id,
        content=content,
        episode_type=ep_type,
        entities=entity_list,
        topic=topic_kw,
    )

    if updated:
        console.print(f"[green]✓[/green] Updated episode [cyan]{episode_id}[/cyan]")
        if content:
            console.print(f"  [dim]Content updated - will be re-consolidated[/dim]")
        if ep_type:
            console.print(f"  Type: [yellow]{ep_type.value}[/yellow]")
        if entity_list:
            console.print(f"  Entities: {', '.join(entity_list)}")
        if clear_topic:
            console.print(f"  Topic: [dim]cleared[/dim]")
        elif topic is not None and updated.topic_id:
            names = memory._get_topic_names()
            tlabel = names.get(updated.topic_id, updated.topic_id)
            console.print(f"  Topic: [blue]{tlabel}[/blue] ({updated.topic_id})")
    else:
        console.print(f"[red]Episode {episode_id} not found[/red]")


@main.command("delete-episode")
@click.argument("episode_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def delete_episode(ctx, episode_id: str, yes: bool):
    """Soft delete an episode from memory."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    # Show episode content before deletion
    episode = memory.store.get_episode(episode_id)
    if not episode:
        console.print(f"[red]Episode {episode_id} not found[/red]")
        return

    if not yes:
        # Skip confirmation if stdin is not a TTY (automation-friendly)
        if not sys.stdin.isatty():
            console.print("[red]Error: Use -y/--yes flag for non-interactive deletion[/red]")
            raise SystemExit(1)
        console.print(f"Episode to delete:")
        console.print(f"  ID: [cyan]{episode.id}[/cyan]")
        console.print(f"  Content: {episode.content[:60]}...")
        if not click.confirm("Delete this episode?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    if memory.delete_episode(episode_id):
        console.print(f"[green]✓[/green] Deleted episode [cyan]{episode_id}[/cyan]")
        console.print(f"  [dim]Use 'remind restore-episode {episode_id}' to undelete[/dim]")
    else:
        console.print(f"[red]Failed to delete episode {episode_id}[/red]")


@main.command("restore-episode")
@click.argument("episode_id")
@click.pass_context
def restore_episode(ctx, episode_id: str):
    """Restore a deleted episode."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    if memory.restore_episode(episode_id):
        console.print(f"[green]✓[/green] Restored episode [cyan]{episode_id}[/cyan]")
    else:
        console.print(f"[red]Episode {episode_id} not found or not deleted[/red]")


@main.command("purge-episode")
@click.argument("episode_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def purge_episode(ctx, episode_id: str, yes: bool):
    """Permanently delete an episode. This cannot be undone."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    if not yes:
        if not sys.stdin.isatty():
            console.print("[red]Error: Use -y/--yes flag for non-interactive purge[/red]")
            raise SystemExit(1)
        console.print(f"[red]WARNING: This will PERMANENTLY delete episode {episode_id}[/red]")
        if not click.confirm("Are you sure?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    if memory.purge_episode(episode_id):
        console.print(f"[green]✓[/green] Permanently deleted episode [cyan]{episode_id}[/cyan]")
    else:
        console.print(f"[red]Episode {episode_id} not found[/red]")


@main.command("update-concept")
@click.argument("concept_id")
@click.option("--title", "-t", help="New title")
@click.option("--summary", "-s", help="New summary")
@click.option("--confidence", "-c", type=float, help="New confidence score (0.0-1.0)")
@click.option("--tag", "tags", multiple=True, help="New tags (replaces existing)")
@click.option("--relations", help='JSON array of relations, e.g. \'[{"type":"implies","target_id":"abc","strength":0.7}]\'')
@click.option("--topic", default=None, help="Topic ID or name (same as remember)")
@click.option("--clear-topic", is_flag=True, help="Remove topic from this concept")
@click.pass_context
def update_concept(ctx, concept_id: str, title: Optional[str], summary: Optional[str],
                   confidence: Optional[float], tags: tuple, relations: Optional[str],
                   topic: Optional[str], clear_topic: bool):
    """Update an existing concept."""
    import json as _json
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    if topic is not None and clear_topic:
        console.print("[red]Use either --topic or --clear-topic, not both.[/red]")
        raise SystemExit(1)

    tag_list = list(tags) if tags else None

    relations_list = None
    if relations:
        try:
            relations_list = _json.loads(relations)
        except _json.JSONDecodeError as e:
            console.print(f"[red]Invalid relations JSON: {e}[/red]")
            return

    topic_kw: Optional[str] = None
    if clear_topic:
        topic_kw = ""
    elif topic is not None:
        topic_kw = topic

    updated = memory.update_concept(
        concept_id,
        title=title,
        summary=summary,
        confidence=confidence,
        tags=tag_list,
        relations=relations_list,
        topic=topic_kw,
    )

    if updated:
        console.print(f"[green]✓[/green] Updated concept [cyan]{concept_id}[/cyan]")
        if title:
            console.print(f"  Title: {title}")
        if summary:
            console.print(f"  [dim]Summary updated - embedding will regenerate on next recall[/dim]")
        if confidence is not None:
            console.print(f"  Confidence: {confidence:.2f}")
        if tag_list:
            console.print(f"  Tags: {', '.join(tag_list)}")
        if relations_list is not None:
            console.print(f"  Relations: {len(relations_list)} set")
        if clear_topic:
            console.print(f"  Topic: [dim]cleared[/dim]")
        elif topic is not None and updated.topic_id:
            names = memory._get_topic_names()
            tlabel = names.get(updated.topic_id, updated.topic_id)
            console.print(f"  Topic: [blue]{tlabel}[/blue] ({updated.topic_id})")
    else:
        console.print(f"[red]Concept {concept_id} not found[/red]")


@main.command("delete-concept")
@click.argument("concept_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def delete_concept(ctx, concept_id: str, yes: bool):
    """Soft delete a concept from memory."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    # Show concept content before deletion
    concept = memory.store.get_concept(concept_id)
    if not concept:
        console.print(f"[red]Concept {concept_id} not found[/red]")
        return

    if not yes:
        if not sys.stdin.isatty():
            console.print("[red]Error: Use -y/--yes flag for non-interactive deletion[/red]")
            raise SystemExit(1)
        console.print(f"Concept to delete:")
        console.print(f"  ID: [cyan]{concept.id}[/cyan]")
        console.print(f"  Title: {concept.title or 'N/A'}")
        console.print(f"  Summary: {concept.summary[:60]}...")
        if not click.confirm("Delete this concept?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    if memory.delete_concept(concept_id):
        console.print(f"[green]✓[/green] Deleted concept [cyan]{concept_id}[/cyan]")
        console.print(f"  [dim]Use 'remind restore-concept {concept_id}' to undelete[/dim]")
    else:
        console.print(f"[red]Failed to delete concept {concept_id}[/red]")


@main.command("restore-concept")
@click.argument("concept_id")
@click.pass_context
def restore_concept(ctx, concept_id: str):
    """Restore a deleted concept."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    if memory.restore_concept(concept_id):
        console.print(f"[green]✓[/green] Restored concept [cyan]{concept_id}[/cyan]")
    else:
        console.print(f"[red]Concept {concept_id} not found or not deleted[/red]")


@main.command("purge-concept")
@click.argument("concept_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def purge_concept(ctx, concept_id: str, yes: bool):
    """Permanently delete a concept. This cannot be undone."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    if not yes:
        if not sys.stdin.isatty():
            console.print("[red]Error: Use -y/--yes flag for non-interactive purge[/red]")
            raise SystemExit(1)
        console.print(f"[red]WARNING: This will PERMANENTLY delete concept {concept_id}[/red]")
        if not click.confirm("Are you sure?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    if memory.purge_concept(concept_id):
        console.print(f"[green]✓[/green] Permanently deleted concept [cyan]{concept_id}[/cyan]")
    else:
        console.print(f"[red]Concept {concept_id} not found[/red]")


@main.command("deleted")
@click.option("--type", "-t", "item_type", type=click.Choice(["episodes", "concepts"]),
              help="Filter by type")
@click.option("--limit", "-n", default=20, help="Number of items to show")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (overrides cli_output_mode)")
@click.option("--table", "as_table", is_flag=True, help="Output human tables (overrides cli_output_mode=json)")
@click.option("--compact-json", "as_compact_json", is_flag=True, help="Minimal id/title/summary JSON")
@click.pass_context
def deleted(ctx, item_type: Optional[str], limit: int, as_json: bool, as_table: bool, as_compact_json: bool):
    """Show soft-deleted episodes and concepts."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])
    out_fmt = _resolve_cli_output_format(ctx, as_table, as_json, as_compact_json)

    show_episodes = item_type in (None, "episodes")
    show_concepts = item_type in (None, "concepts")

    if out_fmt == "json":
        out: dict[str, Any] = {}
        if show_episodes:
            eps = memory.get_deleted_episodes(limit=limit)
            out["episodes"] = [ep.to_dict() for ep in eps]
        if show_concepts:
            dconcepts = memory.get_deleted_concepts()
            out["concepts"] = [_concept_to_json_dict(c) for c in dconcepts[:limit]]
        _emit_cli_json(out)
        return
    if out_fmt == "compact_json":
        out_c: dict[str, Any] = {"format": "compact-json"}
        if show_episodes:
            eps = memory.get_deleted_episodes(limit=limit)
            out_c["episodes"] = [_compact_episode(ep) for ep in eps]
        if show_concepts:
            dconcepts = memory.get_deleted_concepts()
            out_c["concepts"] = [_compact_concept(c) for c in dconcepts[:limit]]
        _emit_cli_json(out_c)
        return

    if show_episodes:
        deleted_episodes = memory.get_deleted_episodes(limit=limit)
        if deleted_episodes:
            table = Table(title=f"Deleted Episodes ({len(deleted_episodes)})")
            table.add_column("ID", style="cyan")
            table.add_column("Content")
            table.add_column("Deleted At", style="dim")

            for ep in deleted_episodes:
                content = ep.content[:50] + "..." if len(ep.content) > 50 else ep.content
                deleted_at = ep.deleted_at.strftime('%Y-%m-%d %H:%M') if ep.deleted_at else "?"
                table.add_row(ep.id, content, deleted_at)

            console.print(table)
        else:
            console.print("[dim]No deleted episodes[/dim]")

    if show_concepts:
        if show_episodes:
            console.print()  # Space between tables
        deleted_concepts = memory.get_deleted_concepts()
        if deleted_concepts:
            table = Table(title=f"Deleted Concepts ({len(deleted_concepts)})")
            table.add_column("ID", style="cyan")
            table.add_column("Title")
            table.add_column("Summary")
            table.add_column("Deleted At", style="dim")

            for c in deleted_concepts[:limit]:
                title = c.title or "-"
                summary = c.summary[:40] + "..." if len(c.summary) > 40 else c.summary
                deleted_at = c.deleted_at.strftime('%Y-%m-%d %H:%M') if c.deleted_at else "?"
                table.add_row(c.id, title, summary, deleted_at)

            console.print(table)
        else:
            console.print("[dim]No deleted concepts[/dim]")


@main.command("purge-all")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def purge_all(ctx, yes: bool):
    """Permanently delete all soft-deleted items. This cannot be undone."""
    memory = get_memory(ctx.obj["db"], ctx.obj["embedding"])

    # Count deleted items
    deleted_episodes = memory.get_deleted_episodes(limit=1000)
    deleted_concepts = memory.get_deleted_concepts()

    if not deleted_episodes and not deleted_concepts:
        console.print("[yellow]No deleted items to purge[/yellow]")
        return

    console.print(f"Items to purge:")
    console.print(f"  Episodes: {len(deleted_episodes)}")
    console.print(f"  Concepts: {len(deleted_concepts)}")

    if not yes:
        if not sys.stdin.isatty():
            console.print("[red]Error: Use -y/--yes flag for non-interactive purge[/red]")
            raise SystemExit(1)
        console.print(f"\n[red]WARNING: This will PERMANENTLY delete all {len(deleted_episodes) + len(deleted_concepts)} items[/red]")
        if not click.confirm("Are you sure?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    # Purge all
    ep_count = 0
    c_count = 0

    for ep in deleted_episodes:
        if memory.purge_episode(ep.id):
            ep_count += 1

    for c in deleted_concepts:
        if memory.purge_concept(c.id):
            c_count += 1

    console.print(f"[green]✓[/green] Purged {ep_count} episodes and {c_count} concepts")


if __name__ == "__main__":
    main()

