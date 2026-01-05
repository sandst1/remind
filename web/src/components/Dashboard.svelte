<script lang="ts">
  import { onMount } from 'svelte';
  import { stats, statsLoading, statsError, currentDb } from '../lib/stores';
  import { fetchStats } from '../lib/api';

  let mounted = false;

  onMount(() => {
    mounted = true;
    loadStats();
  });

  // React to database changes
  $: if (mounted && $currentDb) {
    loadStats();
  }

  async function loadStats() {
    if (!$currentDb) return;

    statsLoading.set(true);
    statsError.set(null);

    try {
      const data = await fetchStats();
      stats.set(data);
    } catch (e) {
      statsError.set(e instanceof Error ? e.message : 'Failed to load stats');
    } finally {
      statsLoading.set(false);
    }
  }

  const episodeTypeLabels: Record<string, string> = {
    observation: 'Observations',
    decision: 'Decisions',
    question: 'Questions',
    meta: 'Meta',
    preference: 'Preferences',
  };

  const relationTypeLabels: Record<string, string> = {
    implies: 'Implies',
    contradicts: 'Contradicts',
    specializes: 'Specializes',
    generalizes: 'Generalizes',
    causes: 'Causes',
    correlates: 'Correlates',
    part_of: 'Part of',
    context_of: 'Context of',
  };
</script>

<div class="dashboard">
  <h2>Dashboard</h2>

  {#if $statsLoading}
    <div class="loading">Loading stats...</div>
  {:else if $statsError}
    <div class="error">{$statsError}</div>
  {:else if $stats}
    <div class="stats-summary">
      <span class="stat-item"><strong>{$stats.concept_count}</strong> concepts</span>
      <span class="stat-item"><strong>{$stats.episode_count}</strong> episodes</span>
      <span class="stat-item"><strong>{$stats.entity_count}</strong> entities</span>
      <span class="stat-item"><strong>{$stats.relation_count}</strong> relations</span>
    </div>

    <div class="section">
      <h3>Consolidation Status</h3>
      <div class="consolidation-status">
        {#if $stats.unconsolidated_count > 0}
          <div class="status-item pending">
            <span class="status-count">{$stats.unconsolidated_count}</span>
            <span class="status-label">episodes pending consolidation</span>
          </div>
        {:else}
          <div class="status-item ok">
            All episodes consolidated
          </div>
        {/if}

        {#if $stats.unextracted_count > 0}
          <div class="status-item pending">
            <span class="status-count">{$stats.unextracted_count}</span>
            <span class="status-label">episodes pending entity extraction</span>
          </div>
        {/if}
      </div>
    </div>

    <div class="distributions">
      <div class="section">
        <h3>Episode Types</h3>
        <div class="distribution-list">
          {#each Object.entries($stats.episode_types) as [type, count]}
            <div class="distribution-item">
              <span class="distribution-label">{episodeTypeLabels[type] || type}</span>
              <span class="distribution-value">{count}</span>
            </div>
          {/each}
        </div>
      </div>

      <div class="section">
        <h3>Relation Types</h3>
        <div class="distribution-list">
          {#each Object.entries($stats.relation_types) as [type, count]}
            {#if count > 0}
              <div class="distribution-item">
                <span class="distribution-label relation-{type}">{relationTypeLabels[type] || type}</span>
                <span class="distribution-value">{count}</span>
              </div>
            {/if}
          {/each}
        </div>
      </div>
    </div>
  {:else}
    <div class="empty">No stats available</div>
  {/if}
</div>

<style>
  .dashboard {
    max-width: 1000px;
  }

  h2 {
    margin-bottom: var(--space-lg);
    font-size: var(--font-size-2xl);
  }

  h3 {
    margin-bottom: var(--space-md);
    font-size: var(--font-size-lg);
    color: var(--color-text-secondary);
  }

  .stats-summary {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-md);
    margin-bottom: var(--space-xl);
    padding: var(--space-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
  }

  .stat-item {
    color: var(--color-text-secondary);
  }

  .stat-item strong {
    color: var(--color-primary);
    font-size: var(--font-size-lg);
  }

  .section {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    margin-bottom: var(--space-lg);
  }

  .consolidation-status {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .status-item {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-md);
  }

  .status-item.pending {
    background: #fff3cd;
    color: #856404;
  }

  .status-item.ok {
    background: #d4edda;
    color: #155724;
  }

  .status-count {
    font-weight: 600;
  }

  .distributions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: var(--space-lg);
  }

  .distribution-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .distribution-item {
    display: flex;
    justify-content: space-between;
    padding: var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
  }

  .distribution-value {
    font-weight: 500;
    font-family: var(--font-mono);
  }

  .relation-implies { color: var(--color-implies); }
  .relation-contradicts { color: var(--color-contradicts); }
  .relation-specializes { color: var(--color-specializes); }
  .relation-generalizes { color: var(--color-generalizes); }
  .relation-causes { color: var(--color-causes); }
  .relation-correlates { color: var(--color-correlates); }
  .relation-part_of { color: var(--color-part-of); }
  .relation-context_of { color: var(--color-context-of); }

  .loading,
  .error,
  .empty {
    padding: var(--space-xl);
    text-align: center;
    color: var(--color-text-secondary);
  }

  .error {
    color: var(--color-contradicts);
  }
</style>
