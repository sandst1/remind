"""
CLI for Remind - testing and experimentation interface.

Commands:
    remind remember "text"       - Add an episode
    remind recall "query"        - Retrieve relevant concepts
    remind consolidate           - Run consolidation
    remind inspect [id]          - View concepts/relations
    remind stats                 - Show memory statistics
    remind status                - Show processing status (workers, queues)
    remind export <file>         - Export memory to JSON
    remind import <file>         - Import memory from JSON
    remind ingest "text"         - Auto-ingest with density scoring
    remind flush-ingest          - Force-flush ingestion buffer
"""

import asyncio
import importlib.resources
import json
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from rich.syntax import Syntax

console = Console()


SKILL_NAMES = ["remind", "remind-plan", "remind-spec", "remind-implement"]


def _read_skill(name: str) -> str:
    """Read a bundled skill file from package data."""
    ref = importlib.resources.files("remind") / "skills" / name / "SKILL.md"
    return ref.read_text(encoding="utf-8")


def get_memory(db_path: str, llm: str, embedding: str):
    """Create a MemoryInterface with the given settings."""
    from remind.interface import create_memory
    return create_memory(
        llm_provider=llm,
        embedding_provider=embedding,
        db_path=db_path,
    )


def run_async(coro):
    """Run an async function synchronously."""
    return asyncio.run(coro)


@click.group()
@click.version_option(version=version("remind-mcp"), prog_name="remind")
@click.option("--db", default=None, help="Database name (stored in ~/.remind/). If not provided, uses <cwd>/.remind/remind.db")
@click.option("--llm", default=None, type=click.Choice(["anthropic", "openai", "azure_openai", "ollama"]))
@click.option("--embedding", default=None, type=click.Choice(["openai", "azure_openai", "ollama"]))
@click.pass_context
def main(ctx, db: str, llm: str, embedding: str):
    """Remind - Generalization-capable memory for LLMs."""
    from remind.config import load_config, resolve_db_path, setup_file_logging

    # Load config (priority: env vars > config file > defaults)
    config = load_config()

    # Resolve providers (CLI > Config)
    llm = llm or config.llm_provider
    embedding = embedding or config.embedding_provider

    # Resolve database path
    # If --db provided: use ~/.remind/{name}.db
    # If not provided: use <cwd>/.remind/remind.db (project-aware)
    if db:
        db_path = resolve_db_path(db)
    else:
        db_path = resolve_db_path(None, project_aware=True)

    if config.logging_enabled:
        setup_file_logging(db_path)

    ctx.ensure_object(dict)
    ctx.obj["db"] = db_path
    ctx.obj["llm"] = llm
    ctx.obj["embedding"] = embedding


@main.command()
@click.argument("content")
@click.option("--metadata", "-m", help="JSON metadata to attach")
@click.option("--type", "-t", "episode_type", 
              type=click.Choice(["observation", "decision", "question", "meta", "preference", "spec", "plan", "task", "outcome"]),
              help="Episode type (detected during consolidation if not provided)")
@click.option("--entity", "-e", "entities", multiple=True, 
              help="Entity IDs (e.g., file:src/auth.ts, person:alice)")
@click.pass_context
def remember(ctx, content: str, metadata: Optional[str], episode_type: Optional[str], 
             entities: tuple):
    """Add an episode to memory.
    
    This is a fast operation - no LLM calls. Entity extraction and
    type classification happen during consolidation.
    """
    from remind.models import EpisodeType
    
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    meta = json.loads(metadata) if metadata else None
    ep_type = EpisodeType(episode_type) if episode_type else None
    entity_list = list(entities) if entities else None
    
    # remember() is now sync - no LLM call
    episode_id = memory.remember(
        content, 
        metadata=meta,
        episode_type=ep_type,
        entities=entity_list,
    )
    
    console.print(f"[green]✓[/green] Remembered as episode [cyan]{episode_id}[/cyan]")

    # Show explicit type/entities if provided
    if ep_type:
        console.print(f"  Type: [yellow]{ep_type.value}[/yellow]")
    if entity_list:
        console.print(f"  Entities: {', '.join(entity_list)}")

    # Check if background consolidation should run
    stats = memory.get_stats()
    unconsolidated = stats.get("unconsolidated_episodes", 0)

    if unconsolidated >= memory.consolidation_threshold:
        # Spawn background consolidation
        from remind.background import spawn_background_consolidation

        if spawn_background_consolidation(
            db_path=ctx.obj["db"],
            llm_provider=ctx.obj["llm"],
            embedding_provider=ctx.obj["embedding"],
        ):
            console.print(f"[dim]→ Background consolidation started ({unconsolidated} episodes)[/dim]")
        else:
            console.print(f"[dim]→ Consolidation already running[/dim]")
    elif unconsolidated >= 3:
        console.print(f"[dim]→ {unconsolidated} episodes pending consolidation[/dim]")


@main.command()
@click.argument("query")
@click.option("-k", default=3, help="Number of concepts to retrieve")
@click.option("--context", "-c", help="Additional context for search")
@click.option("--entity", "-e", help="Retrieve by entity ID instead of semantic search")
@click.option("--raw", is_flag=True, help="Show raw concept data")
@click.pass_context
def recall(ctx, query: str, k: int, context: Optional[str], entity: Optional[str], raw: bool):
    """Retrieve relevant concepts for a query.
    
    By default, does semantic search across concepts. 
    Use --entity to retrieve by entity ID instead.
    
    Examples:
        remindrecall "authentication issues"
        remindrecall "auth" --entity file:src/auth.ts
    """
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    async def _recall():
        return await memory.recall(query, k=k, context=context, entity=entity, raw=raw)
    
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
                table.add_row(ep.id, ep.episode_type.value, content)
            
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


@main.command()
@click.option("--force", "-f", is_flag=True, help="Force consolidation even with few episodes")
@click.option("--background", "-b", is_flag=True, help="Run consolidation in background")
@click.pass_context
def consolidate(ctx, force: bool, background: bool):
    """Run memory consolidation manually."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    stats_before = memory.get_stats()
    unconsolidated = stats_before.get("unconsolidated_episodes", 0)

    if unconsolidated == 0:
        console.print("[yellow]No episodes to consolidate[/yellow]")
        return

    from filelock import FileLock, Timeout
    from remind.background import (
        spawn_background_consolidation,
        get_consolidation_lock_path,
    )

    db_path = ctx.obj["db"]

    if background:
        llm = ctx.obj["llm"]
        embedding = ctx.obj["embedding"]

        if spawn_background_consolidation(db_path, llm, embedding):
            console.print(f"[green]✓ Background consolidation started ({unconsolidated} episodes)[/green]")
        else:
            console.print("[yellow]Consolidation already running[/yellow]")
        return

    lock_path = get_consolidation_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path), timeout=0)

    try:
        lock.acquire(blocking=False)
    except Timeout:
        console.print("[yellow]Consolidation already running (another process holds the lock)[/yellow]")
        return

    try:
        console.print(f"[cyan]Consolidating {unconsolidated} episodes...[/cyan]")

        batch_size = memory.consolidator.batch_size
        total_batches = (unconsolidated + batch_size - 1) // batch_size

        def on_batch(batch_num, batch_result):
            if total_batches > 1:
                console.print(
                    f"  [dim]Batch {batch_num}/{total_batches}:[/dim] "
                    f"{batch_result.episodes_processed} episodes → "
                    f"{batch_result.concepts_created} created, "
                    f"{batch_result.concepts_updated} updated"
                )

        async def _consolidate():
            return await memory.consolidate(force=True, on_batch_complete=on_batch)

        result = run_async(_consolidate())
    finally:
        lock.release()

    console.print(f"\n[green]✓ Consolidation complete[/green]")
    console.print(f"  Episodes processed: {result.episodes_processed}")
    console.print(f"  Concepts created: {result.concepts_created}")
    console.print(f"  Concepts updated: {result.concepts_updated}")

    if result.contradictions_found:
        console.print(f"  [yellow]Contradictions found: {result.contradictions_found}[/yellow]")
        for contradiction in result.contradiction_details:
            console.print(f"    → {contradiction}")


@main.command()
@click.confirmation_option(
    prompt="This will delete all concepts and entities and rebuild from episodes. Continue?"
)
@click.pass_context
def reconsolidate(ctx):
    """Reset database and consolidate from scratch.

    This operation:
    1. Deletes all concepts and relations
    2. Deletes all entities and mentions
    3. Resets episode consolidated/extracted flags
    4. Runs consolidation from scratch

    Useful when consolidation prompts change or to fix accumulated errors.
    Episodes are preserved - only derived data is cleared.
    """
    from remind.store import SQLiteMemoryStore

    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    store = SQLiteMemoryStore(ctx.obj["db"])

    console.print("[bold cyan]Reconsolidating memory...[/bold cyan]\n")

    # Step 1: Delete concepts
    with console.status("[bold cyan]Deleting concepts..."):
        concept_count = store.delete_all_concepts()
    console.print(f"  [green]✓[/green] Deleted {concept_count} concepts")

    # Step 2: Delete entities
    with console.status("[bold cyan]Deleting entities..."):
        entity_count = store.delete_all_entities()
    console.print(f"  [green]✓[/green] Deleted {entity_count} entities")

    # Step 3: Reset episode flags
    with console.status("[bold cyan]Resetting episode flags..."):
        episode_count = store.reset_episode_flags()
    console.print(f"  [green]✓[/green] Reset {episode_count} episodes")

    # Step 4: Run consolidation (loops through all batches internally)
    console.print(f"\n[cyan]Running consolidation on {episode_count} episodes...[/cyan]")

    batch_size = memory.consolidator.batch_size
    total_batches = (episode_count + batch_size - 1) // batch_size

    def on_batch(batch_num, batch_result):
        if total_batches > 1:
            console.print(
                f"  [dim]Batch {batch_num}/{total_batches}:[/dim] "
                f"{batch_result.episodes_processed} episodes → "
                f"{batch_result.concepts_created} created, "
                f"{batch_result.concepts_updated} updated"
            )

    async def _consolidate():
        return await memory.consolidate(force=True, on_batch_complete=on_batch)

    result = run_async(_consolidate())

    console.print(f"\n[green]✓ Reconsolidation complete[/green]")
    console.print(f"  Total concepts created: {result.concepts_created}")
    console.print(f"  Total concepts updated: {result.concepts_updated}")
    if result.contradictions_found:
        console.print(f"  [yellow]Contradictions found: {result.contradictions_found}[/yellow]")


@main.command("end-session")
@click.pass_context
def end_session(ctx):
    """End session: flush ingestion buffer, then consolidate in background.

    Use this as a hook point in your agent workflow:
    - At end of conversation
    - After task completion
    - Before shutdown
    """
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    # Flush ingestion buffer first
    if not memory._ingest_buffer.is_empty:
        buf_size = memory.ingest_buffer_size
        console.print(f"[blue]Flushing ingestion buffer ({buf_size} chars)...[/blue]")
        episode_ids = run_async(memory.flush_ingest())
        if episode_ids:
            console.print(f"[green]✓ Created {len(episode_ids)} episodes from buffer[/green]")

    pending = memory.pending_episodes_count

    if pending == 0:
        console.print("[yellow]No pending episodes to consolidate[/yellow]")
        return

    from remind.background import (
        spawn_background_consolidation,
        get_ingest_queue_dir,
        spawn_ingest_worker,
    )

    db_path = ctx.obj["db"]
    llm = ctx.obj["llm"]
    embedding = ctx.obj["embedding"]

    # Ensure any queued ingest chunks are being processed
    queue_dir = get_ingest_queue_dir(db_path)
    if queue_dir.is_dir() and any(queue_dir.glob("*.json")):
        if spawn_ingest_worker(db_path, llm, embedding):
            console.print("[dim]Started ingest worker for queued chunks.[/dim]")

    if spawn_background_consolidation(db_path, llm, embedding):
        console.print(f"[green]✓ Session ended — consolidating {pending} episodes in background[/green]")
    else:
        console.print(f"[yellow]Consolidation already running ({pending} episodes pending)[/yellow]")


@main.command()
@click.argument("content", required=False)
@click.option("--source", "-s", default="conversation", help="Source label for metadata")
@click.option("--foreground", "-f", is_flag=True, help="Run triage and consolidation in foreground (blocking)")
@click.pass_context
def ingest(ctx, content: Optional[str], source: str, foreground: bool):
    """Ingest raw text for automatic memory curation.

    By default, spawns triage and consolidation in a background process
    and returns immediately. Use --foreground to run synchronously.

    Accepts text as an argument or via stdin (for piping).

    Examples:
        remind ingest "User prefers dark mode and Vim keybindings"
        echo "conversation log" | remind ingest
        cat transcript.txt | remind ingest --source transcript
        remind ingest --foreground "important observation"
    """
    # Read from stdin if no argument provided
    if content is None:
        if not sys.stdin.isatty():
            content = sys.stdin.read().strip()
        if not content:
            console.print("[red]No content provided. Pass as argument or pipe via stdin.[/red]")
            return

    if foreground:
        from remind.interface import create_memory
        memory = create_memory(
            llm_provider=ctx.obj["llm"],
            embedding_provider=ctx.obj["embedding"],
            db_path=ctx.obj["db"],
            ingest_background=False,
        )
        with console.status("[bold cyan]Running triage and consolidation..."):
            episode_ids = run_async(memory.ingest(content, source=source))

        if episode_ids:
            console.print(f"[green]✓ Created {len(episode_ids)} episode(s) from ingest[/green]")
            for eid in episode_ids:
                console.print(f"  {eid}")
            console.print("[dim]Consolidation completed.[/dim]")
        else:
            console.print("[yellow]Triage found nothing memory-worthy (low density).[/yellow]")
    else:
        from remind.background import enqueue_ingest_chunk, spawn_ingest_worker

        enqueue_ingest_chunk(
            db_path=ctx.obj["db"],
            chunk=content,
            source=source,
        )
        spawned = spawn_ingest_worker(
            db_path=ctx.obj["db"],
            llm_provider=ctx.obj["llm"],
            embedding_provider=ctx.obj["embedding"],
        )
        console.print(f"[green]✓[/green] Ingest queued ({len(content)} chars)")
        if spawned:
            console.print("[dim]Background worker started.[/dim]")
        else:
            console.print("[dim]Worker already running — it will pick this up.[/dim]")


@main.command("flush-ingest")
@click.pass_context
def flush_ingest(ctx):
    """Force-flush the ingestion buffer.

    Processes whatever text is in the buffer immediately, regardless of
    whether the character threshold has been reached. Note: in CLI context,
    the buffer is per-process and typically empty. This is mainly useful
    when called from end-session or long-lived contexts.
    """
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    buf_size = memory.ingest_buffer_size
    if buf_size == 0:
        console.print("[yellow]Ingestion buffer is empty, nothing to flush.[/yellow]")
        return

    console.print(f"[blue]Flushing buffer ({buf_size} chars)...[/blue]")
    episode_ids = run_async(memory.flush_ingest())

    if episode_ids:
        console.print(f"[green]✓ Created {len(episode_ids)} episode(s)[/green]")
        for eid in episode_ids:
            console.print(f"  {eid}")
        console.print("[dim]Consolidation completed.[/dim]")
    else:
        console.print("[yellow]Triage found nothing memory-worthy.[/yellow]")


@main.command()
@click.argument("concept_id", required=False)
@click.option("--episodes", "-e", is_flag=True, help="Show recent episodes instead")
@click.option("--limit", "-n", default=10, help="Number of items to show")
@click.pass_context
def inspect(ctx, concept_id: Optional[str], episodes: bool, limit: int):
    """Inspect concepts or episodes."""
    from remind.store import SQLiteMemoryStore
    store = SQLiteMemoryStore(ctx.obj["db"])
    
    if episodes:
        # Show recent episodes
        recent = store.get_recent_episodes(limit=limit)
        
        if not recent:
            console.print("[yellow]No episodes in memory[/yellow]")
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
                ep.episode_type.value[:3],  # Shortened type
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
            console.print(f"[red]Concept {concept_id} not found[/red]")
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
            console.print("[yellow]No concepts in memory[/yellow]")
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
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
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


@main.command()
@click.pass_context
def status(ctx):
    """Show consolidation and ingestion processing status.

    Quick view of what's currently happening: running workers,
    pending episodes, queued ingest chunks.
    """
    from remind.background import (
        is_consolidation_running,
        is_ingest_running,
        get_ingest_queue_dir,
    )

    db_path = ctx.obj["db"]
    memory = get_memory(db_path, ctx.obj["llm"], ctx.obj["embedding"])
    stats_data = memory.get_stats()

    # Consolidation status
    consolidating = is_consolidation_running(db_path)
    pending = stats_data.get("unconsolidated_episodes", 0)
    unextracted = stats_data.get("unextracted_episodes", 0)
    threshold = stats_data.get("consolidation_threshold", 10)
    last = stats_data.get("last_consolidation") or "never"

    # Ingest status
    ingesting = is_ingest_running(db_path)
    queue_dir = get_ingest_queue_dir(db_path)
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
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    data = memory.export_memory(file)
    console.print(f"[green]✓[/green] Exported {data['stats']['concepts']} concepts and {data['stats']['episodes']} episodes to [cyan]{file}[/cyan]")


@main.command("import")
@click.argument("file")
@click.pass_context
def import_cmd(ctx, file: str):
    """Import memory from JSON file."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    result = memory.import_memory(file)
    console.print(f"[green]✓[/green] Imported {result['concepts_imported']} concepts, {result['episodes_imported']} episodes from [cyan]{file}[/cyan]")


@main.command()
@click.argument("query")
@click.pass_context
def search(ctx, query: str):
    """Search concepts by tag or keyword."""
    from remind.store import SQLiteMemoryStore
    store = SQLiteMemoryStore(ctx.obj["db"])
    
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
        console.print(f"[yellow]No concepts matching '{query}'[/yellow]")
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
@click.pass_context
def entities(ctx, entity_id: Optional[str], entity_type: Optional[str]):
    """List entities or show details for a specific entity."""
    from remind.store import SQLiteMemoryStore
    from remind.models import EntityType
    store = SQLiteMemoryStore(ctx.obj["db"])
    
    if entity_id:
        # Show specific entity and its mentions
        entity = store.get_entity(entity_id)
        
        if not entity:
            console.print(f"[red]Entity {entity_id} not found[/red]")
            return
        
        # Get episodes mentioning this entity
        episodes = store.get_episodes_mentioning(entity_id, limit=20)
        
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
            console.print("[yellow]No entities in memory[/yellow]")
            return
        
        # Filter by type if specified
        if entity_type:
            try:
                etype = EntityType(entity_type)
                entity_counts = [(e, c) for e, c in entity_counts if e.type == etype]
            except ValueError:
                console.print(f"[red]Unknown entity type: {entity_type}[/red]")
                console.print(f"Valid types: {', '.join(t.value for t in EntityType)}")
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
@click.pass_context
def mentions(ctx, entity_id: str):
    """Show all episodes mentioning an entity."""
    from remind.store import SQLiteMemoryStore
    store = SQLiteMemoryStore(ctx.obj["db"])
    
    episodes = store.get_episodes_mentioning(entity_id, limit=50)
    
    if not episodes:
        console.print(f"[yellow]No episodes mention '{entity_id}'[/yellow]")
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
            ep.episode_type.value,
            ep.timestamp.strftime("%Y-%m-%d %H:%M"),
            content,
        )
    
    console.print(table)


@main.command("decisions")
@click.option("--limit", "-n", default=20, help="Number of decisions to show")
@click.pass_context
def decisions(ctx, limit: int):
    """Show decision-type episodes."""
    from remind.store import SQLiteMemoryStore
    from remind.models import EpisodeType
    store = SQLiteMemoryStore(ctx.obj["db"])
    
    episodes = store.get_episodes_by_type(EpisodeType.DECISION, limit=limit)
    
    if not episodes:
        console.print("[yellow]No decisions recorded yet[/yellow]")
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
@click.pass_context
def questions(ctx, limit: int):
    """Show question-type episodes (open questions, uncertainties)."""
    from remind.store import SQLiteMemoryStore
    from remind.models import EpisodeType
    store = SQLiteMemoryStore(ctx.obj["db"])

    episodes = store.get_episodes_by_type(EpisodeType.QUESTION, limit=limit)

    if not episodes:
        console.print("[yellow]No questions recorded yet[/yellow]")
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


# ============================================================================
# Spec, Plan, and Task Commands
# ============================================================================

@main.command("specs")
@click.option("--limit", "-n", default=20, help="Number of specs to show")
@click.option("--entity", "-e", help="Filter by entity ID")
@click.option("--status", "-s", help="Filter by status (draft, approved, implemented, deprecated)")
@click.pass_context
def specs(ctx, limit: int, entity: Optional[str], status: Optional[str]):
    """Show spec-type episodes (requirements, acceptance criteria)."""
    from remind.store import SQLiteMemoryStore
    from remind.models import EpisodeType
    store = SQLiteMemoryStore(ctx.obj["db"])

    episodes = store.get_episodes_by_type(EpisodeType.SPEC, limit=1000)

    if entity:
        episodes = [ep for ep in episodes if entity in ep.entity_ids]
    if status:
        episodes = [ep for ep in episodes if (ep.metadata or {}).get("status") == status]

    episodes = episodes[:limit]

    if not episodes:
        console.print("[yellow]No specs recorded yet[/yellow]")
        return

    table = Table(title="Specs")
    table.add_column("ID", style="cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Content")
    table.add_column("Status", style="yellow")
    table.add_column("Entities", style="dim")

    for ep in episodes:
        content = ep.content[:60] + "..." if len(ep.content) > 60 else ep.content
        meta_status = (ep.metadata or {}).get("status", "-")
        entities_str = ", ".join(ep.entity_ids[:2]) if ep.entity_ids else ""
        if len(ep.entity_ids) > 2:
            entities_str += f" +{len(ep.entity_ids)-2}"
        table.add_row(ep.id, ep.timestamp.strftime("%Y-%m-%d %H:%M"), content,
                       meta_status, entities_str)

    console.print(table)


@main.command("plans")
@click.option("--limit", "-n", default=20, help="Number of plans to show")
@click.option("--entity", "-e", help="Filter by entity ID")
@click.option("--status", "-s", help="Filter by status (draft, active, completed, superseded)")
@click.pass_context
def plans(ctx, limit: int, entity: Optional[str], status: Optional[str]):
    """Show plan-type episodes (implementation plans, roadmaps)."""
    from remind.store import SQLiteMemoryStore
    from remind.models import EpisodeType
    store = SQLiteMemoryStore(ctx.obj["db"])

    episodes = store.get_episodes_by_type(EpisodeType.PLAN, limit=1000)

    if entity:
        episodes = [ep for ep in episodes if entity in ep.entity_ids]
    if status:
        episodes = [ep for ep in episodes if (ep.metadata or {}).get("status") == status]

    episodes = episodes[:limit]

    if not episodes:
        console.print("[yellow]No plans recorded yet[/yellow]")
        return

    table = Table(title="Plans")
    table.add_column("ID", style="cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Content")
    table.add_column("Status", style="yellow")
    table.add_column("Entities", style="dim")

    for ep in episodes:
        content = ep.content[:60] + "..." if len(ep.content) > 60 else ep.content
        meta_status = (ep.metadata or {}).get("status", "-")
        entities_str = ", ".join(ep.entity_ids[:2]) if ep.entity_ids else ""
        if len(ep.entity_ids) > 2:
            entities_str += f" +{len(ep.entity_ids)-2}"
        table.add_row(ep.id, ep.timestamp.strftime("%Y-%m-%d %H:%M"), content,
                       meta_status, entities_str)

    console.print(table)


@main.command("tasks")
@click.option("--status", "-s", help="Filter by status (todo, in_progress, done, blocked)")
@click.option("--entity", "-e", help="Filter by entity ID")
@click.option("--plan", "-p", help="Filter by plan episode ID")
@click.option("--all", "show_all", is_flag=True, help="Include completed tasks")
@click.pass_context
def tasks(ctx, status: Optional[str], entity: Optional[str], plan: Optional[str],
          show_all: bool):
    """Show task episodes grouped by status."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    task_list = memory.get_tasks(
        status=status,
        entity_id=entity,
        plan_id=plan,
    )

    if not show_all and not status:
        task_list = [t for t in task_list if (t.metadata or {}).get("status") != "done"]

    if not task_list:
        console.print("[yellow]No tasks found[/yellow]")
        return

    groups: dict[str, list] = {"todo": [], "in_progress": [], "blocked": [], "done": []}
    for t in task_list:
        s = (t.metadata or {}).get("status", "todo")
        groups.setdefault(s, []).append(t)

    status_styles = {
        "todo": "white",
        "in_progress": "cyan",
        "blocked": "red",
        "done": "green",
    }

    for group_status in ["in_progress", "blocked", "todo", "done"]:
        group_tasks = groups.get(group_status, [])
        if not group_tasks:
            continue

        style = status_styles.get(group_status, "white")
        table = Table(title=f"[{style}]{group_status.upper()}[/{style}] ({len(group_tasks)})")
        table.add_column("ID", style="cyan")
        table.add_column("Content")
        table.add_column("Priority", style="yellow", justify="center")
        table.add_column("Entities", style="dim")

        for t in group_tasks:
            meta = t.metadata or {}
            content = t.content[:55] + "..." if len(t.content) > 55 else t.content
            priority = meta.get("priority", "-")
            entities_str = ", ".join(t.entity_ids[:2]) if t.entity_ids else ""
            if len(t.entity_ids) > 2:
                entities_str += f" +{len(t.entity_ids)-2}"

            if group_status == "blocked":
                reason = meta.get("blocked_reason", "")
                if reason:
                    content += f" [red]({reason})[/red]"

            table.add_row(t.id, content, priority, entities_str)

        console.print(table)
        console.print()


@main.group("task")
def task_group():
    """Manage tasks (add, start, done, block, unblock)."""
    pass


main.add_command(task_group)


@task_group.command("add")
@click.argument("content")
@click.option("--entity", "-e", "entities", multiple=True, help="Entity IDs")
@click.option("--priority", "-p", default="p1", type=click.Choice(["p0", "p1", "p2"]),
              help="Priority (default: p1)")
@click.option("--plan", help="Plan episode ID this task implements")
@click.option("--spec", "spec_ids", multiple=True, help="Spec episode IDs this task implements")
@click.option("--depends-on", "depends_on", multiple=True, help="Task IDs this depends on")
@click.pass_context
def task_add(ctx, content: str, entities: tuple, priority: str, plan: Optional[str],
             spec_ids: tuple, depends_on: tuple):
    """Add a new task."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    meta = {"status": "todo", "priority": priority}
    if plan:
        meta["plan_id"] = plan
    if spec_ids:
        meta["spec_ids"] = list(spec_ids)
    if depends_on:
        meta["depends_on"] = list(depends_on)

    from remind.models import EpisodeType
    episode_id = memory.remember(
        content,
        metadata=meta,
        episode_type=EpisodeType.TASK,
        entities=list(entities) if entities else None,
    )

    console.print(f"[green]✓[/green] Created task [cyan]{episode_id}[/cyan]")
    console.print(f"  Priority: [yellow]{priority}[/yellow]")
    if entities:
        console.print(f"  Entities: {', '.join(entities)}")
    if plan:
        console.print(f"  Plan: {plan}")
    if depends_on:
        console.print(f"  Depends on: {', '.join(depends_on)}")


@task_group.command("update")
@click.argument("task_id")
@click.option("--plan", help="Plan episode ID to link")
@click.option("--spec", "spec_ids", multiple=True, help="Spec episode ID to link (repeatable)")
@click.option("--depends-on", "depends_on", multiple=True, help="Task ID this depends on (repeatable)")
@click.option("--priority", "-p", type=click.Choice(["p0", "p1", "p2"]), help="Priority")
@click.option("--content", "-c", help="New task description")
@click.option("--entity", "-e", "entities", multiple=True, help="New entity IDs (replaces existing)")
@click.pass_context
def task_update(ctx, task_id: str, plan: Optional[str], spec_ids: tuple, depends_on: tuple,
                priority: Optional[str], content: Optional[str], entities: tuple):
    """Update an existing task's linkage, priority, or description."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    meta: dict = {}
    if plan:
        meta["plan_id"] = plan
    if spec_ids:
        meta["spec_ids"] = list(spec_ids)
    if depends_on:
        meta["depends_on"] = list(depends_on)
    if priority:
        meta["priority"] = priority

    entity_list = list(entities) if entities else None

    updated = memory.update_episode(
        task_id,
        content=content,
        entities=entity_list,
        metadata=meta if meta else None,
    )

    if updated:
        console.print(f"[green]✓[/green] Updated task [cyan]{task_id}[/cyan]")
        if content:
            console.print(f"  [dim]Content updated - will be re-consolidated[/dim]")
        if entity_list:
            console.print(f"  Entities: {', '.join(entity_list)}")
        if plan:
            console.print(f"  Plan: {plan}")
        if spec_ids:
            console.print(f"  Specs: {', '.join(spec_ids)}")
        if depends_on:
            console.print(f"  Depends on: {', '.join(depends_on)}")
        if priority:
            console.print(f"  Priority: [yellow]{priority}[/yellow]")
    else:
        console.print(f"[red]Task {task_id} not found[/red]")


@task_group.command("start")
@click.argument("task_id")
@click.pass_context
def task_start(ctx, task_id: str):
    """Start a task (todo -> in_progress)."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    updated = memory.update_task_status(task_id, "in_progress")
    if updated:
        console.print(f"[green]✓[/green] Started task [cyan]{task_id}[/cyan]")
    else:
        console.print(f"[red]Task {task_id} not found[/red]")


@task_group.command("done")
@click.argument("task_id")
@click.pass_context
def task_done(ctx, task_id: str):
    """Complete a task (-> done)."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    updated = memory.update_task_status(task_id, "done")
    if updated:
        console.print(f"[green]✓[/green] Completed task [cyan]{task_id}[/cyan]")
    else:
        console.print(f"[red]Task {task_id} not found[/red]")


@task_group.command("block")
@click.argument("task_id")
@click.argument("reason", required=False, default="")
@click.pass_context
def task_block(ctx, task_id: str, reason: str):
    """Block a task with an optional reason."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    updated = memory.update_task_status(task_id, "blocked", reason=reason or None)
    if updated:
        msg = f"[green]✓[/green] Blocked task [cyan]{task_id}[/cyan]"
        if reason:
            msg += f" ([red]{reason}[/red])"
        console.print(msg)
    else:
        console.print(f"[red]Task {task_id} not found[/red]")


@task_group.command("unblock")
@click.argument("task_id")
@click.pass_context
def task_unblock(ctx, task_id: str):
    """Unblock a task (blocked -> todo)."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    updated = memory.update_task_status(task_id, "todo")
    if updated:
        console.print(f"[green]✓[/green] Unblocked task [cyan]{task_id}[/cyan]")
    else:
        console.print(f"[red]Task {task_id} not found[/red]")


@main.command("extract-relations")
@click.option("--batch-size", "-b", default=50, help="Number of episodes to process per batch")
@click.option("--force", "-f", is_flag=True, help="Re-extract relations for all episodes (including already extracted)")
@click.pass_context
def extract_relations(ctx, batch_size: int, force: bool):
    """Extract entity relationships from existing episodes.

    Processes episodes that have entities but haven't had relationship extraction.
    This is useful for backfilling entity relationships in existing databases.
    """
    from remind.extraction import EntityExtractor

    # Get memory interface (includes LLM provider)
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    # Create extractor using the memory's LLM and store
    extractor = EntityExtractor(memory.llm, memory.store)

    if force:
        # Get all episodes with 2+ entities
        console.print("[yellow]Force mode: re-extracting relations for all episodes with 2+ entities[/yellow]")
        episodes = memory.store.get_recent_episodes(limit=10000)
        episodes = [ep for ep in episodes if len(ep.entity_ids) >= 2]
    else:
        # Get episodes needing relation extraction
        episodes = memory.store.get_unextracted_relation_episodes(limit=batch_size)

    if not episodes:
        console.print("[yellow]No episodes need relation extraction[/yellow]")
        return

    console.print(f"[cyan]Extracting relations from {len(episodes)} episodes...[/cyan]")

    total_relations = 0
    processed = 0
    errors = 0

    async def _extract():
        nonlocal total_relations, processed, errors
        for ep in episodes:
            try:
                count = await extractor.extract_and_store_relations_only(ep)
                total_relations += count
                processed += 1
            except Exception as e:
                console.print(f"[red]Error processing {ep.id}: {e}[/red]")
                errors += 1

    with console.status("[bold cyan]Extracting relationships..."):
        run_async(_extract())

    console.print(f"\n[green]✓ Relation extraction complete[/green]")
    console.print(f"  Episodes processed: {processed}")
    console.print(f"  Relations extracted: {total_relations}")
    if errors:
        console.print(f"  [yellow]Errors: {errors}[/yellow]")


@main.command("entity-relations")
@click.argument("entity_id")
@click.pass_context
def entity_relations(ctx, entity_id: str):
    """Show relationships for a specific entity."""
    from remind.store import SQLiteMemoryStore
    store = SQLiteMemoryStore(ctx.obj["db"])

    entity = store.get_entity(entity_id)
    if not entity:
        console.print(f"[red]Entity {entity_id} not found[/red]")
        return

    relations = store.get_entity_relations(entity_id)

    if not relations:
        console.print(f"[yellow]No relationships found for '{entity_id}'[/yellow]")
        return

    # Separate outgoing and incoming relations
    outgoing = [r for r in relations if r.source_id == entity_id]
    incoming = [r for r in relations if r.target_id == entity_id]

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
    from urllib.parse import quote

    from remind.mcp_server import run_server_sse

    db_path = ctx.obj["db"]

    # URL-encode the database path for the query parameter
    db_param = quote(db_path, safe="")
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
    """Install Remind skills for Claude Code in the current project.

    Installs skill files to .claude/skills/<name>/SKILL.md from the
    bundled package data, keeping them in sync with the installed version.

    Available skills: remind, remind-plan, remind-spec, remind-implement

    With no arguments, installs all skills. Pass specific names to install
    only those (e.g., "remind skill-install remind remind-plan").
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

    console.print("\nClaude Code will now use Remind skills in this project.")


# ============================================================================
# Update/Delete/Restore Commands
# ============================================================================

@main.command("update-episode")
@click.argument("episode_id")
@click.option("--content", "-c", help="New content text")
@click.option("--type", "-t", "episode_type",
              type=click.Choice(["observation", "decision", "question", "meta", "preference", "spec", "plan", "task"]),
              help="New episode type")
@click.option("--entity", "-e", "entities", multiple=True, help="New entity IDs (replaces existing)")
@click.option("--plan", help="Plan episode ID to link")
@click.option("--spec", "spec_ids", multiple=True, help="Spec episode ID to link (repeatable)")
@click.option("--depends-on", "depends_on", multiple=True, help="Task ID this depends on (repeatable)")
@click.option("--priority", type=click.Choice(["p0", "p1", "p2"]), help="Priority")
@click.pass_context
def update_episode(ctx, episode_id: str, content: Optional[str],
                   episode_type: Optional[str], entities: tuple,
                   plan: Optional[str], spec_ids: tuple, depends_on: tuple,
                   priority: Optional[str]):
    """Update an existing episode."""
    from remind.models import EpisodeType

    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    ep_type = EpisodeType(episode_type) if episode_type else None
    entity_list = list(entities) if entities else None

    meta: dict = {}
    if plan:
        meta["plan_id"] = plan
    if spec_ids:
        meta["spec_ids"] = list(spec_ids)
    if depends_on:
        meta["depends_on"] = list(depends_on)
    if priority:
        meta["priority"] = priority

    updated = memory.update_episode(
        episode_id,
        content=content,
        episode_type=ep_type,
        entities=entity_list,
        metadata=meta if meta else None,
    )

    if updated:
        console.print(f"[green]✓[/green] Updated episode [cyan]{episode_id}[/cyan]")
        if content:
            console.print(f"  [dim]Content updated - will be re-consolidated[/dim]")
        if ep_type:
            console.print(f"  Type: [yellow]{ep_type.value}[/yellow]")
        if entity_list:
            console.print(f"  Entities: {', '.join(entity_list)}")
        if plan:
            console.print(f"  Plan: {plan}")
        if spec_ids:
            console.print(f"  Specs: {', '.join(spec_ids)}")
        if depends_on:
            console.print(f"  Depends on: {', '.join(depends_on)}")
        if priority:
            console.print(f"  Priority: [yellow]{priority}[/yellow]")
    else:
        console.print(f"[red]Episode {episode_id} not found[/red]")


@main.command("delete-episode")
@click.argument("episode_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def delete_episode(ctx, episode_id: str, yes: bool):
    """Soft delete an episode from memory."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    # Show episode content before deletion
    episode = memory.store.get_episode(episode_id)
    if not episode:
        console.print(f"[red]Episode {episode_id} not found[/red]")
        return

    if not yes:
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
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

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
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    if not yes:
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
@click.pass_context
def update_concept(ctx, concept_id: str, title: Optional[str], summary: Optional[str],
                   confidence: Optional[float], tags: tuple, relations: Optional[str]):
    """Update an existing concept."""
    import json as _json
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    tag_list = list(tags) if tags else None

    relations_list = None
    if relations:
        try:
            relations_list = _json.loads(relations)
        except _json.JSONDecodeError as e:
            console.print(f"[red]Invalid relations JSON: {e}[/red]")
            return

    updated = memory.update_concept(
        concept_id,
        title=title,
        summary=summary,
        confidence=confidence,
        tags=tag_list,
        relations=relations_list,
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
    else:
        console.print(f"[red]Concept {concept_id} not found[/red]")


@main.command("delete-concept")
@click.argument("concept_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def delete_concept(ctx, concept_id: str, yes: bool):
    """Soft delete a concept from memory."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    # Show concept content before deletion
    concept = memory.store.get_concept(concept_id)
    if not concept:
        console.print(f"[red]Concept {concept_id} not found[/red]")
        return

    if not yes:
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
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

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
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    if not yes:
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
@click.pass_context
def deleted(ctx, item_type: Optional[str], limit: int):
    """Show soft-deleted episodes and concepts."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

    show_episodes = item_type in (None, "episodes")
    show_concepts = item_type in (None, "concepts")

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
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])

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

