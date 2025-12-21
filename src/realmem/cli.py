"""
CLI for RealMem - testing and experimentation interface.

Commands:
    realmem remember "text"     - Add an episode
    realmem recall "query"      - Retrieve relevant concepts
    realmem consolidate         - Run consolidation
    realmem inspect [id]        - View concepts/relations
    realmem stats               - Show memory statistics
    realmem export <file>       - Export memory to JSON
    realmem import <file>       - Import memory from JSON
"""

import asyncio
import json
import sys
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


def get_memory(db_path: str, llm: str, embedding: str):
    """Create a MemoryInterface with the given settings."""
    from realmem.interface import create_memory
    return create_memory(
        llm_provider=llm,
        embedding_provider=embedding,
        db_path=db_path,
    )


def run_async(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


@click.group()
@click.option("--db", default="memory.db", help="Path to memory database")
@click.option("--llm", default=None, type=click.Choice(["anthropic", "openai", "azure_openai", "ollama"]))
@click.option("--embedding", default=None, type=click.Choice(["openai", "azure_openai", "ollama"]))
@click.pass_context
def main(ctx, db: str, llm: str, embedding: str):
    """RealMem - Generalization-capable memory for LLMs."""
    import os
    
    # Resolve providers (CLI > Env var > Default)
    llm = llm or os.environ.get("LLM_PROVIDER", "openai")
    embedding = embedding or os.environ.get("EMBEDDING_PROVIDER", "openai")
    
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["llm"] = llm
    ctx.obj["embedding"] = embedding


@main.command()
@click.argument("content")
@click.option("--metadata", "-m", help="JSON metadata to attach")
@click.option("--type", "-t", "episode_type", 
              type=click.Choice(["observation", "decision", "question", "meta", "preference"]),
              help="Episode type (auto-detected if not provided)")
@click.option("--entity", "-e", "entities", multiple=True, 
              help="Entity IDs (e.g., file:src/auth.ts, person:alice)")
@click.option("--no-extract", is_flag=True, help="Disable auto-extraction")
@click.pass_context
def remember(ctx, content: str, metadata: Optional[str], episode_type: Optional[str], 
             entities: tuple, no_extract: bool):
    """Add an episode to memory."""
    from realmem.models import EpisodeType
    
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    meta = json.loads(metadata) if metadata else None
    ep_type = EpisodeType(episode_type) if episode_type else None
    entity_list = list(entities) if entities else None
    
    async def _remember():
        episode_id = await memory.remember(
            content, 
            metadata=meta,
            episode_type=ep_type,
            entities=entity_list,
            auto_extract=not no_extract,
        )
        # Get the episode to show extraction results
        episode = memory.store.get_episode(episode_id)
        return episode_id, episode
    
    with console.status("[bold cyan]Remembering...") if not no_extract else console.status(""):
        episode_id, episode = run_async(_remember())
    
    console.print(f"[green]✓[/green] Remembered as episode [cyan]{episode_id}[/cyan]")
    
    # Show extracted info
    if episode and episode.entities_extracted:
        console.print(f"  Type: [yellow]{episode.episode_type.value}[/yellow]")
        if episode.entity_ids:
            console.print(f"  Entities: {', '.join(episode.entity_ids)}")
    
    # Show unconsolidated count
    stats = memory.get_stats()
    unconsolidated = stats.get("unconsolidated_episodes", 0)
    if unconsolidated >= 5:
        console.print(f"[yellow]→[/yellow] {unconsolidated} episodes pending consolidation. Run [bold]realmem consolidate[/bold]")


@main.command()
@click.argument("query")
@click.option("-k", default=5, help="Number of concepts to retrieve")
@click.option("--context", "-c", help="Additional context for search")
@click.option("--entity", "-e", help="Retrieve by entity ID instead of semantic search")
@click.option("--raw", is_flag=True, help="Show raw concept data")
@click.pass_context
def recall(ctx, query: str, k: int, context: Optional[str], entity: Optional[str], raw: bool):
    """Retrieve relevant concepts for a query.
    
    By default, does semantic search across concepts. 
    Use --entity to retrieve by entity ID instead.
    
    Examples:
        realmem recall "authentication issues"
        realmem recall "auth" --entity file:src/auth.ts
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
            console.print(Panel(result, title=f"Memory: {entity}", border_style="cyan"))
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
        # Show formatted output
        console.print(Panel(result, title="Retrieved Memory", border_style="cyan"))


@main.command()
@click.option("--force", "-f", is_flag=True, help="Force consolidation even with few episodes")
@click.pass_context
def consolidate(ctx, force: bool):
    """Run memory consolidation manually."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    stats_before = memory.get_stats()
    unconsolidated = stats_before.get("unconsolidated_episodes", 0)
    
    if unconsolidated == 0:
        console.print("[yellow]No episodes to consolidate[/yellow]")
        return
    
    console.print(f"[cyan]Consolidating {unconsolidated} episodes...[/cyan]")
    
    async def _consolidate():
        return await memory.consolidate(force=force)
    
    with console.status("[bold cyan]Running consolidation..."):
        result = run_async(_consolidate())
    
    console.print(f"\n[green]✓ Consolidation complete[/green]")
    console.print(f"  Episodes processed: {result.episodes_processed}")
    console.print(f"  Concepts created: {result.concepts_created}")
    console.print(f"  Concepts updated: {result.concepts_updated}")
    
    if result.contradictions_found:
        console.print(f"  [yellow]Contradictions found: {result.contradictions_found}[/yellow]")
        for contradiction in result.contradiction_details:
            console.print(f"    → {contradiction}")


@main.command("end-session")
@click.pass_context
def end_session(ctx):
    """End session and consolidate all pending episodes.
    
    Use this as a hook point in your agent workflow:
    - At end of conversation
    - After task completion
    - Before shutdown
    """
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    pending = memory.pending_episodes_count
    
    if pending == 0:
        console.print("[yellow]No pending episodes to consolidate[/yellow]")
        return
    
    console.print(f"[cyan]Ending session: consolidating {pending} pending episodes...[/cyan]")
    
    async def _end_session():
        return await memory.end_session()
    
    with console.status("[bold cyan]Running end-of-session consolidation..."):
        result = run_async(_end_session())
    
    console.print(f"\n[green]✓ Session ended[/green]")
    console.print(f"  Episodes processed: {result.episodes_processed}")
    console.print(f"  Concepts created: {result.concepts_created}")
    console.print(f"  Concepts updated: {result.concepts_updated}")


@main.command()
@click.argument("concept_id", required=False)
@click.option("--episodes", "-e", is_flag=True, help="Show recent episodes instead")
@click.option("--limit", "-n", default=10, help="Number of items to show")
@click.pass_context
def inspect(ctx, concept_id: Optional[str], episodes: bool, limit: int):
    """Inspect concepts or episodes."""
    from realmem.store import SQLiteMemoryStore
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
        table.add_column("Summary")
        table.add_column("Conf", justify="right")
        table.add_column("N", justify="right")
        table.add_column("Relations", justify="right")
        table.add_column("Tags", style="dim")
        
        for c in concepts:
            summary = c.summary[:50] + "..." if len(c.summary) > 50 else c.summary
            tags = ", ".join(c.tags[:3]) if c.tags else ""
            if len(c.tags) > 3:
                tags += "..."
            table.add_row(
                c.id,
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

[bold]Database:[/bold] {ctx.obj['db']}
""",
        title="Memory Stats",
        border_style="cyan"
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
@click.argument("prompt")
@click.pass_context
def reflect(ctx, prompt: str):
    """Let the LLM reflect on its memory."""
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    async def _reflect():
        return await memory.reflect(prompt)
    
    with console.status("[bold cyan]Reflecting..."):
        result = run_async(_reflect())
    
    console.print(Panel(result, title="Reflection", border_style="magenta"))


@main.command()
@click.argument("query")
@click.pass_context
def search(ctx, query: str):
    """Search concepts by tag or keyword."""
    from realmem.store import SQLiteMemoryStore
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
@click.option("--limit", "-n", default=100, help="Maximum episodes to process")
@click.pass_context
def backfill(ctx, limit: int):
    """Backfill entity extraction for existing episodes.
    
    Processes episodes that haven't had extraction performed yet.
    Useful for migrating existing databases to the v2 schema.
    """
    memory = get_memory(ctx.obj["db"], ctx.obj["llm"], ctx.obj["embedding"])
    
    stats = memory.get_stats()
    unextracted = stats.get("unextracted_episodes", 0)
    
    if unextracted == 0:
        console.print("[green]✓[/green] All episodes already have entity extraction")
        return
    
    console.print(f"[cyan]Found {unextracted} episodes needing extraction (processing up to {limit})...[/cyan]")
    
    async def _backfill():
        return await memory.backfill_extraction(limit=limit)
    
    with console.status("[bold cyan]Running entity extraction..."):
        result = run_async(_backfill())
    
    console.print(f"\n[green]✓ Backfill complete[/green]")
    console.print(f"  Episodes processed: {result.episodes_processed}")
    console.print(f"  Entities created: {result.entities_created}")
    
    if result.errors:
        console.print(f"  [yellow]Errors: {len(result.errors)}[/yellow]")
        for error in result.errors[:3]:
            console.print(f"    → {error}")


@main.command()
@click.argument("entity_id", required=False)
@click.option("--type", "-t", "entity_type", help="Filter by entity type (file, function, person, etc.)")
@click.pass_context
def entities(ctx, entity_id: Optional[str], entity_type: Optional[str]):
    """List entities or show details for a specific entity."""
    from realmem.store import SQLiteMemoryStore
    from realmem.models import EntityType
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
    from realmem.store import SQLiteMemoryStore
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
    from realmem.store import SQLiteMemoryStore
    from realmem.models import EpisodeType
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
    from realmem.store import SQLiteMemoryStore
    from realmem.models import EpisodeType
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


if __name__ == "__main__":
    main()

