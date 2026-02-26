<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { currentDb } from '../lib/stores';
  import { fetchConcepts } from '../lib/api';
  import type { Concept } from '../lib/types';
  import { ArrowUp, ArrowDown, Brain } from 'lucide-svelte';

  type SortKey = 'decay_factor' | 'access_count' | 'last_accessed' | 'created_at' | 'title';
  type SortDir = 'asc' | 'desc';

  const PAGE_SIZE = 50;

  let allConcepts: Concept[] = [];
  let visibleCount = PAGE_SIZE;
  let loading = false;
  let loadingMore = false;
  let error: string | null = null;
  let mounted = false;
  let loadGen = 0;

  let sortKey: SortKey = 'access_count';
  let sortDir: SortDir = 'desc';

  // Sentinel element for IntersectionObserver
  let sentinel: HTMLElement | null = null;
  let observer: IntersectionObserver | null = null;

  onMount(() => {
    mounted = true;
  });

  onDestroy(() => {
    observer?.disconnect();
  });

  $: if (mounted && $currentDb) {
    loadAll();
  }

  // Re-attach observer whenever sentinel or sorted list changes
  $: if (sentinel) {
    setupObserver();
  }

  async function loadAll() {
    if (!$currentDb) return;
    const gen = ++loadGen;
    loading = true;
    error = null;
    visibleCount = PAGE_SIZE;

    try {
      const batchSize = 200;
      let offset = 0;
      let total = Infinity;
      const collected: Concept[] = [];

      while (offset < total) {
        const response = await fetchConcepts({ offset, limit: batchSize });
        if (gen !== loadGen) return;
        total = response.total;
        collected.push(...response.concepts);
        offset += batchSize;
        if (response.concepts.length < batchSize) break;
      }

      allConcepts = collected;
    } catch (e) {
      if (gen !== loadGen) return;
      error = e instanceof Error ? e.message : 'Failed to load concepts';
    } finally {
      if (gen === loadGen) loading = false;
    }
  }

  function setupObserver() {
    observer?.disconnect();
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMore();
        }
      },
      { rootMargin: '100px' }
    );
    if (sentinel) observer.observe(sentinel);
  }

  function loadMore() {
    if (visibleCount >= sorted.length) return;
    loadingMore = true;
    // Small delay so the spinner renders before the DOM update
    setTimeout(() => {
      visibleCount = Math.min(visibleCount + PAGE_SIZE, sorted.length);
      loadingMore = false;
    }, 80);
  }

  function setSort(key: SortKey) {
    if (sortKey === key) {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      sortKey = key;
      sortDir = key === 'decay_factor' || key === 'last_accessed' || key === 'title' ? 'asc' : 'desc';
    }
    // Reset visible window on sort change
    visibleCount = PAGE_SIZE;
  }

  $: sorted = [...allConcepts].sort((a, b) => {
    let av: number | string, bv: number | string;

    if (sortKey === 'decay_factor') {
      av = a.decay_factor ?? 1;
      bv = b.decay_factor ?? 1;
    } else if (sortKey === 'access_count') {
      av = a.access_count ?? 0;
      bv = b.access_count ?? 0;
    } else if (sortKey === 'last_accessed') {
      av = a.last_accessed ?? '';
      bv = b.last_accessed ?? '';
    } else if (sortKey === 'created_at') {
      av = a.created_at;
      bv = b.created_at;
    } else {
      av = (a.title || a.summary).toLowerCase();
      bv = (b.title || b.summary).toLowerCase();
    }

    if (av < bv) return sortDir === 'asc' ? -1 : 1;
    if (av > bv) return sortDir === 'asc' ? 1 : -1;
    return 0;
  });

  $: visible = sorted.slice(0, visibleCount);
  $: hasMore = visibleCount < sorted.length;

  // Summary stats derived from all loaded concepts
  $: totalConcepts = allConcepts.length;
  $: neverAccessed = allConcepts.filter(c => !c.last_accessed).length;
  $: fading = allConcepts.filter(c => (c.decay_factor ?? 1) < 0.8).length;
  $: avgDecay = totalConcepts > 0
    ? allConcepts.reduce((s, c) => s + (c.decay_factor ?? 1), 0) / totalConcepts
    : 1;

  function decayColor(factor: number, isDormant: boolean): string {
    if (isDormant) return 'var(--color-text-secondary)';
    if (factor >= 0.8) return 'var(--color-primary)';
    if (factor >= 0.5) return 'var(--color-text-secondary)';
    return 'var(--color-zinc-400, #a1a1aa)';
  }

  function decayLabel(factor: number, isDormant: boolean): string {
    if (isDormant) return 'dormant';
    if (factor >= 0.8) return 'fresh';
    if (factor >= 0.5) return 'fading';
    return 'faded';
  }

  function relativeTime(iso: string | null): string {
    if (!iso) return 'Never';
    const diff = Date.now() - new Date(iso).getTime();
    const s = Math.floor(diff / 1000);
    if (s < 60) return 'just now';
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    if (d < 30) return `${d}d ago`;
    const mo = Math.floor(d / 30);
    if (mo < 12) return `${mo}mo ago`;
    return `${Math.floor(mo / 12)}y ago`;
  }

  function shortDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function conceptLabel(c: Concept): string {
    return c.title || c.summary;
  }
</script>

<div class="memory-status">
  <div class="page-header">
    <h2>Memory Status</h2>
    <p class="subtitle">See how concepts are decaying over time. Recalled concepts fade if not reinforced. Concepts never recalled stay dormant.</p>
  </div>

  {#if loading}
    <div class="loading">Loading concepts...</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if allConcepts.length === 0}
    <div class="empty">
      <Brain size={40} />
      <p>No concepts yet.</p>
    </div>
  {:else}
    <div class="summary-bar">
      <div class="summary-card">
        <span class="summary-value">{totalConcepts}</span>
        <span class="summary-label">Total concepts</span>
      </div>
      <div class="summary-card">
        <span class="summary-value">{(avgDecay * 100).toFixed(0)}%</span>
        <span class="summary-label">Avg memory strength</span>
      </div>
      <div class="summary-card" class:has-fading={fading > 0}>
        <span class="summary-value">{fading}</span>
        <span class="summary-label">Fading ({fading > 0 ? ((fading / totalConcepts) * 100).toFixed(0) : 0}%)</span>
      </div>
      <div class="summary-card">
        <span class="summary-value">{neverAccessed}</span>
        <span class="summary-label">Never recalled</span>
      </div>
    </div>

    <div class="table-wrap">
      <table class="decay-table">
        <thead>
          <tr>
            <th class="col-title">
              <button class="sort-btn" onclick={() => setSort('title')}>
                Concept
                {#if sortKey === 'title'}
                  {#if sortDir === 'asc'}<ArrowUp size={12} />{:else}<ArrowDown size={12} />{/if}
                {/if}
              </button>
            </th>
            <th class="col-decay">
              <button class="sort-btn" onclick={() => setSort('decay_factor')}>
                Memory strength
                {#if sortKey === 'decay_factor'}
                  {#if sortDir === 'asc'}<ArrowUp size={12} />{:else}<ArrowDown size={12} />{/if}
                {/if}
              </button>
            </th>
            <th class="col-access">
              <button class="sort-btn" onclick={() => setSort('access_count')}>
                Recalls
                {#if sortKey === 'access_count'}
                  {#if sortDir === 'asc'}<ArrowUp size={12} />{:else}<ArrowDown size={12} />{/if}
                {/if}
              </button>
            </th>
            <th class="col-last">
              <button class="sort-btn" onclick={() => setSort('last_accessed')}>
                Last recalled
                {#if sortKey === 'last_accessed'}
                  {#if sortDir === 'asc'}<ArrowUp size={12} />{:else}<ArrowDown size={12} />{/if}
                {/if}
              </button>
            </th>
            <th class="col-created">
              <button class="sort-btn" onclick={() => setSort('created_at')}>
                Created
                {#if sortKey === 'created_at'}
                  {#if sortDir === 'asc'}<ArrowUp size={12} />{:else}<ArrowDown size={12} />{/if}
                {/if}
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          {#each visible as concept (concept.id)}
            {@const factor = concept.decay_factor ?? 1}
            {@const isDormant = (concept.access_count ?? 0) === 0}
            <tr class="concept-row" class:faded={factor < 0.5} class:dormant={isDormant}>
              <td class="col-title">
                <span class="concept-title" class:dim={factor < 0.5} title={conceptLabel(concept)}>
                  {conceptLabel(concept)}
                </span>
              </td>
              <td class="col-decay">
                <div class="decay-cell">
                  {#if isDormant}
                    <div class="bar-track">
                      <div class="bar-fill bar-fill-dormant"></div>
                    </div>
                    <span class="decay-pct decay-pct-na">N/A</span>
                  {:else}
                    <div class="bar-track">
                      <div
                        class="bar-fill"
                        style="width: {(factor * 100).toFixed(1)}%; background: {decayColor(factor, false)};"
                      ></div>
                    </div>
                    <span class="decay-pct" style="color: {decayColor(factor, false)};">
                      {(factor * 100).toFixed(0)}%
                    </span>
                  {/if}
                  <span class="decay-badge badge-{decayLabel(factor, isDormant)}">
                    {decayLabel(factor, isDormant)}
                  </span>
                </div>
              </td>
              <td class="col-access">
                <span class:dim={factor < 0.5 || isDormant}>{concept.access_count ?? 0}</span>
              </td>
              <td class="col-last">
                <span class:dim={factor < 0.5 || isDormant}>{relativeTime(concept.last_accessed)}</span>
              </td>
              <td class="col-created">
                <span class:dim={factor < 0.5 || isDormant}>{shortDate(concept.created_at)}</span>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>

      <!-- Scroll sentinel / footer -->
      {#if hasMore}
        <div class="load-more-sentinel" bind:this={sentinel}>
          {#if loadingMore}
            <span class="loading-more-text">Loading more…</span>
          {:else}
            <span class="showing-count">Showing {visibleCount} of {sorted.length}</span>
          {/if}
        </div>
      {:else if sorted.length > PAGE_SIZE}
        <div class="all-loaded">All {sorted.length} concepts loaded</div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .memory-status {
    display: flex;
    flex-direction: column;
    gap: var(--space-lg);
    max-width: 1100px;
  }

  .page-header h2 {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    color: var(--color-text);
    margin-bottom: var(--space-xs);
  }

  .subtitle {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .loading,
  .error,
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-md);
    padding: var(--space-2xl);
    color: var(--color-text-secondary);
  }

  .error {
    color: var(--color-error, #ef4444);
  }

  /* Summary bar */

  .summary-bar {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--space-md);
  }

  .summary-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .summary-card.has-fading .summary-value {
    color: var(--color-text-secondary);
  }

  .summary-value {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    color: var(--color-text);
    line-height: 1;
  }

  .summary-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  /* Table */

  .table-wrap {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: auto;
  }

  .decay-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--font-size-sm);
  }

  .decay-table thead tr {
    border-bottom: 1px solid var(--color-border);
  }

  .decay-table th {
    padding: var(--space-sm) var(--space-md);
    text-align: left;
    font-weight: 600;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
  }

  .sort-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: none;
    border: none;
    padding: 0;
    color: inherit;
    font: inherit;
    letter-spacing: inherit;
    text-transform: inherit;
    cursor: pointer;
    transition: color 0.15s;
  }

  .sort-btn:hover {
    color: var(--color-text);
  }

  .concept-row {
    border-bottom: 1px solid var(--color-border);
    transition: background 0.1s;
  }

  .concept-row:last-child {
    border-bottom: none;
  }

  .concept-row:hover {
    background: var(--color-zinc-50, rgba(244, 244, 245, 0.5));
  }

  :global([data-theme="dark"]) .concept-row:hover {
    background: var(--color-zinc-800);
  }

  .concept-row.faded {
    opacity: 0.75;
  }

  .decay-table td {
    padding: var(--space-sm) var(--space-md);
    vertical-align: middle;
  }

  /* Column widths */

  .col-title {
    width: 35%;
    min-width: 180px;
  }

  .col-decay {
    width: 30%;
    min-width: 200px;
  }

  .col-access {
    width: 10%;
    min-width: 70px;
    text-align: right;
  }

  .col-last {
    width: 13%;
    min-width: 110px;
    white-space: nowrap;
  }

  .col-created {
    width: 12%;
    min-width: 100px;
    white-space: nowrap;
  }

  .concept-title {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    color: var(--color-text);
    line-height: 1.4;
  }

  .dim {
    color: var(--color-text-secondary);
  }

  /* Decay bar */

  .decay-cell {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }

  .bar-track {
    flex: 1;
    height: 6px;
    background: var(--color-border);
    border-radius: 3px;
    overflow: hidden;
  }

  .bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s ease, background 0.3s ease;
  }

  .decay-pct {
    font-variant-numeric: tabular-nums;
    font-size: var(--font-size-xs);
    font-weight: 600;
    width: 32px;
    text-align: right;
    flex-shrink: 0;
  }

  .decay-badge {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 999px;
    flex-shrink: 0;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .bar-fill-dormant {
    width: 0%;
  }

  .decay-pct-na {
    color: var(--color-text-secondary);
    font-variant-numeric: normal;
  }

  .badge-dormant {
    background: var(--color-zinc-100, #f4f4f5);
    color: var(--color-text-secondary);
  }

  :global([data-theme="dark"]) .badge-dormant {
    background: var(--color-zinc-800);
  }

  .badge-fresh {
    background: var(--color-primary-bg);
    color: var(--color-primary);
  }

  .badge-fading {
    background: var(--color-zinc-100, #f4f4f5);
    color: var(--color-text-secondary);
  }

  :global([data-theme="dark"]) .badge-fading {
    background: var(--color-zinc-800);
  }

  .badge-faded {
    background: var(--color-zinc-100, #f4f4f5);
    color: var(--color-zinc-400, #a1a1aa);
  }

  :global([data-theme="dark"]) .badge-faded {
    background: var(--color-zinc-800);
    color: var(--color-zinc-500, #71717a);
  }

  /* Load-more sentinel & footer */

  .load-more-sentinel,
  .all-loaded {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-md);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    border-top: 1px solid var(--color-border);
  }

  .loading-more-text {
    opacity: 0.7;
  }
</style>
