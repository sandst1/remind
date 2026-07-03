<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { currentDb, openConflictCount, currentView, conceptPath } from '../lib/stores';
  import { fetchConflicts, resolveConflict, dismissConflict, fetchConcept } from '../lib/api';
  import type { Conflict, ConflictStatus, Fact } from '../lib/types';
  import { AlertTriangle, Check, X, User, Link2 } from 'lucide-svelte';

  type StatusFilter = ConflictStatus | 'all';

  let conflicts: Conflict[] = [];
  let loading = false;
  let error: string | null = null;
  let statusFilter: StatusFilter = 'open';

  // Per-conflict action state
  let notes: Record<string, string> = {};
  let resolvedBy: Record<string, string> = {};
  let acting: Record<string, boolean> = {};

  let mounted = false;

  $: if (mounted && $currentDb) {
    loadConflicts(statusFilter);
  }

  onMount(() => {
    mounted = true;
  });

  async function loadConflicts(status: StatusFilter) {
    loading = true;
    error = null;
    try {
      const res = await fetchConflicts({ status });
      conflicts = res.conflicts;
      $openConflictCount = res.open_count;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function setFilter(status: StatusFilter) {
    statusFilter = status;
    loadConflicts(status);
  }

  async function handleResolve(conflict: Conflict, winningFactId?: string) {
    acting[conflict.id] = true;
    error = null;
    try {
      await resolveConflict(conflict.id, {
        winning_fact_id: winningFactId,
        note: notes[conflict.id]?.trim() || undefined,
        resolved_by: resolvedBy[conflict.id]?.trim() || undefined,
      });
      await loadConflicts(statusFilter);
    } catch (e: any) {
      error = e.message;
    } finally {
      acting[conflict.id] = false;
    }
  }

  async function handleDismiss(conflict: Conflict) {
    acting[conflict.id] = true;
    error = null;
    try {
      await dismissConflict(conflict.id, {
        note: notes[conflict.id]?.trim() || undefined,
        resolved_by: resolvedBy[conflict.id]?.trim() || undefined,
      });
      await loadConflicts(statusFilter);
    } catch (e: any) {
      error = e.message;
    } finally {
      acting[conflict.id] = false;
    }
  }

  async function openConcept(id: string) {
    try {
      const concept = await fetchConcept(id);
      $currentView = 'concepts';
      // ConceptList clears conceptPath on mount; set the path after it settles
      await tick();
      conceptPath.set([concept]);
    } catch (e: any) {
      error = e.message;
    }
  }

  function formatDate(iso: string | null): string {
    if (!iso) return '';
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
    });
  }

  function winnerLabel(conflict: Conflict): string | null {
    if (!conflict.winning_fact_id) return null;
    for (const fact of [conflict.fact_a, conflict.fact_b]) {
      if (fact && fact.id === conflict.winning_fact_id) return fact.statement;
    }
    return conflict.winning_fact_id;
  }

  const filters: Array<{ value: StatusFilter; label: string }> = [
    { value: 'open', label: 'Open' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'dismissed', label: 'Dismissed' },
    { value: 'all', label: 'All' },
  ];
</script>

<div class="conflicts-inbox">
  <div class="header">
    <h2><AlertTriangle size={20} /> Conflicts</h2>
    <div class="filters">
      {#each filters as f}
        <button
          class="filter-btn"
          class:active={statusFilter === f.value}
          onclick={() => setFilter(f.value)}
        >
          {f.label}
          {#if f.value === 'open' && $openConflictCount > 0}
            <span class="count-badge">{$openConflictCount}</span>
          {/if}
        </button>
      {/each}
    </div>
  </div>

  {#if error}
    <div class="error">{error}</div>
  {/if}

  {#if loading}
    <div class="empty-state">Loading conflicts...</div>
  {:else if conflicts.length === 0}
    <div class="empty-state">
      {#if statusFilter === 'open'}
        <Check size={32} />
        <p>No open conflicts. Memory is consistent.</p>
      {:else}
        <p>No {statusFilter === 'all' ? '' : statusFilter} conflicts.</p>
      {/if}
    </div>
  {:else}
    <div class="conflict-list">
      {#each conflicts as conflict (conflict.id)}
        <div class="conflict-card" class:open={conflict.status === 'open'}>
          <div class="conflict-header">
            <span class="badge kind-{conflict.kind}">{conflict.kind}</span>
            <span class="badge severity-{conflict.severity}">{conflict.severity}</span>
            <span class="conflict-date">detected {formatDate(conflict.created_at)}</span>
            {#if conflict.status !== 'open'}
              <span class="badge status-{conflict.status}">{conflict.status}</span>
            {/if}
          </div>

          <p class="description">{conflict.description}</p>

          {#if conflict.kind === 'fact' && (conflict.fact_a || conflict.fact_b)}
            <div class="facts-row">
              {#each [conflict.fact_a, conflict.fact_b] as fact}
                {#if fact}
                  <div
                    class="fact-card"
                    class:winner={conflict.winning_fact_id === fact.id}
                    class:superseded={fact.valid_to !== null}
                  >
                    <p class="fact-statement">{fact.statement}</p>
                    <div class="fact-meta">
                      {#if fact.asserted_by}
                        <span><User size={11} /> {fact.asserted_by}</span>
                      {/if}
                      {#if fact.source_ref}
                        <span><Link2 size={11} /> {fact.source_ref}</span>
                      {/if}
                      <span>since {formatDate(fact.valid_from)}</span>
                    </div>
                    {#if conflict.status === 'open'}
                      <button
                        class="btn btn-keep"
                        disabled={acting[conflict.id]}
                        onclick={() => handleResolve(conflict, fact.id)}
                      >
                        <Check size={13} /> Keep this
                      </button>
                    {:else if conflict.winning_fact_id === fact.id}
                      <span class="winner-tag"><Check size={12} /> kept</span>
                    {/if}
                  </div>
                {/if}
              {/each}
            </div>
          {/if}

          {#if conflict.concepts.length > 0}
            <div class="concept-links">
              {#each conflict.concepts as concept}
                <button class="concept-link" onclick={() => openConcept(concept.id)}>
                  {concept.title || concept.summary}
                </button>
              {/each}
            </div>
          {/if}

          {#if conflict.status === 'open'}
            <div class="actions">
              <input
                class="input"
                placeholder="Resolution note (optional)"
                bind:value={notes[conflict.id]}
              />
              <input
                class="input input-narrow"
                placeholder="Decided by"
                bind:value={resolvedBy[conflict.id]}
              />
              {#if conflict.kind === 'concept'}
                <button
                  class="btn btn-resolve"
                  disabled={acting[conflict.id]}
                  onclick={() => handleResolve(conflict)}
                >
                  <Check size={13} /> Resolve
                </button>
              {/if}
              <button
                class="btn btn-dismiss"
                disabled={acting[conflict.id]}
                onclick={() => handleDismiss(conflict)}
                title="Not a real contradiction — both claims stay active"
              >
                <X size={13} /> Dismiss
              </button>
            </div>
          {:else}
            <div class="resolution-info">
              {#if winnerLabel(conflict)}
                <span>Kept: "{winnerLabel(conflict)}"</span>
              {/if}
              {#if conflict.resolution_note}
                <span>Note: {conflict.resolution_note}</span>
              {/if}
              {#if conflict.resolved_by}
                <span>By: {conflict.resolved_by}</span>
              {/if}
              {#if conflict.resolved_at}
                <span>{formatDate(conflict.resolved_at)}</span>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .conflicts-inbox {
    padding: 1.5rem;
    max-width: 960px;
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .header h2 {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--color-text);
    margin: 0;
  }

  .filters {
    display: flex;
    gap: 0.25rem;
  }

  .filter-btn {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 6px;
    color: var(--color-text-muted);
    padding: 0.35rem 0.7rem;
    font-size: 0.8rem;
    cursor: pointer;
  }
  .filter-btn:hover { background: var(--color-hover); }
  .filter-btn.active {
    color: var(--color-text);
    border-color: var(--color-accent);
  }

  .count-badge {
    background: var(--color-warning, #e6a23c);
    color: white;
    border-radius: 999px;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 0.05rem 0.4rem;
    line-height: 1.4;
  }

  .error {
    color: var(--color-danger, #e55);
    background: var(--color-surface);
    border: 1px solid var(--color-danger, #e55);
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    margin-bottom: 1rem;
    font-size: 0.85rem;
  }

  .empty-state {
    color: var(--color-text-muted);
    padding: 3rem 2rem;
    text-align: center;
    font-size: 0.9rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
  }

  .conflict-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .conflict-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 0.9rem 1rem;
  }
  .conflict-card.open {
    border-left: 3px solid var(--color-warning, #e6a23c);
  }

  .conflict-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }

  .badge {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-radius: 4px;
    padding: 0.1rem 0.4rem;
    border: 1px solid var(--color-border);
    color: var(--color-text-muted);
  }
  .badge.severity-high { color: var(--color-danger, #e55); border-color: var(--color-danger, #e55); }
  .badge.severity-medium { color: var(--color-warning, #e6a23c); border-color: var(--color-warning, #e6a23c); }
  .badge.status-resolved { color: var(--color-success, #4a4); border-color: var(--color-success, #4a4); }

  .conflict-date {
    font-size: 0.75rem;
    color: var(--color-text-muted);
    margin-left: auto;
  }

  .description {
    font-size: 0.9rem;
    color: var(--color-text);
    margin: 0 0 0.75rem;
  }

  .facts-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.6rem;
    margin-bottom: 0.75rem;
  }
  @media (max-width: 720px) {
    .facts-row { grid-template-columns: 1fr; }
  }

  .fact-card {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: 6px;
    padding: 0.6rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .fact-card.winner { border-color: var(--color-success, #4a4); }
  .fact-card.superseded { opacity: 0.65; }

  .fact-statement {
    font-size: 0.85rem;
    color: var(--color-text);
    margin: 0;
    flex: 1;
  }

  .fact-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    font-size: 0.7rem;
    color: var(--color-text-muted);
  }
  .fact-meta span {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
  }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    cursor: pointer;
    border: 1px solid var(--color-border);
    border-radius: 6px;
    background: var(--color-surface);
    color: var(--color-text);
    padding: 0.35rem 0.65rem;
    font-size: 0.78rem;
    white-space: nowrap;
  }
  .btn:hover { background: var(--color-hover); }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .btn-keep {
    align-self: flex-start;
    border-color: var(--color-success, #4a4);
    color: var(--color-success, #4a4);
  }
  .btn-resolve {
    border-color: var(--color-success, #4a4);
    color: var(--color-success, #4a4);
  }
  .btn-dismiss {
    color: var(--color-text-muted);
  }

  .winner-tag {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--color-success, #4a4);
  }

  .concept-links {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 0.75rem;
  }

  .concept-link {
    background: none;
    border: 1px solid var(--color-border);
    border-radius: 999px;
    color: var(--color-accent);
    font-size: 0.75rem;
    padding: 0.2rem 0.6rem;
    cursor: pointer;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .concept-link:hover { background: var(--color-hover); }

  .actions {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: wrap;
  }

  .input {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: 6px;
    padding: 0.35rem 0.6rem;
    color: var(--color-text);
    font-size: 0.78rem;
    flex: 1;
    min-width: 160px;
  }
  .input:focus {
    outline: none;
    border-color: var(--color-accent);
  }
  .input-narrow {
    flex: 0 1 130px;
    min-width: 100px;
  }

  .resolution-info {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    font-size: 0.75rem;
    color: var(--color-text-muted);
    border-top: 1px solid var(--color-border);
    padding-top: 0.5rem;
  }
</style>
