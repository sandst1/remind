<script lang="ts">
  import { onMount } from 'svelte';
  import { stats, statsLoading, statsError, currentDb } from '../lib/stores';
  import { fetchStats } from '../lib/api';
  import { Lightbulb, History, Tag, Network, AlertCircle, CheckCircle } from 'lucide-svelte';

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
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon icon-concepts">
          <Lightbulb size={24} />
        </div>
        <div class="stat-content">
          <span class="stat-value">{$stats.concepts}</span>
          <span class="stat-label">Concepts</span>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon icon-episodes">
          <History size={24} />
        </div>
        <div class="stat-content">
          <span class="stat-value">{$stats.episodes}</span>
          <span class="stat-label">Episodes</span>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon icon-entities">
          <Tag size={24} />
        </div>
        <div class="stat-content">
          <span class="stat-value">{$stats.entities}</span>
          <span class="stat-label">Entities</span>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon icon-relations">
          <Network size={24} />
        </div>
        <div class="stat-content">
          <span class="stat-value">{$stats.relations}</span>
          <span class="stat-label">Relations</span>
        </div>
      </div>
    </div>

    <div class="section">
      <h3>Consolidation Status</h3>
      <div class="consolidation-status">
        {#if $stats.unconsolidated_episodes > 0}
          <div class="status-item pending">
            <AlertCircle size={20} />
            <div>
              <span class="status-count">{$stats.unconsolidated_episodes}</span>
              <span class="status-label">episodes pending consolidation</span>
            </div>
          </div>
        {:else}
          <div class="status-item ok">
            <CheckCircle size={20} />
            <span>All episodes consolidated</span>
          </div>
        {/if}

        {#if $stats.unextracted_count > 0}
          <div class="status-item pending">
            <AlertCircle size={20} />
            <div>
              <span class="status-count">{$stats.unextracted_count}</span>
              <span class="status-label">episodes pending entity extraction</span>
            </div>
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
    margin: 0 auto;
  }

  h2 {
    margin-bottom: var(--space-xl);
    font-size: var(--font-size-2xl);
    font-weight: 700;
    color: var(--color-text);
    letter-spacing: -0.025em;
  }

  h3 {
    margin-bottom: var(--space-md);
    font-size: var(--font-size-lg);
    color: var(--color-text-secondary);
    font-weight: 600;
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-lg);
    margin-bottom: var(--space-xl);
  }

  .stat-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    display: flex;
    align-items: center;
    gap: var(--space-md);
    box-shadow: var(--shadow-sm);
    transition: all 0.2s ease;
    cursor: default;
  }
  
  .stat-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
    border-color: var(--color-zinc-300);
  }

  .stat-icon {
    width: 48px;
    height: 48px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: transform 0.2s ease;
  }
  
  .stat-card:hover .stat-icon {
    transform: scale(1.1);
  }
  
  .icon-concepts { background: var(--color-amber-bg); color: var(--color-amber); }
  .icon-episodes { background: var(--color-blue-bg); color: var(--color-blue); }
  .icon-entities { background: var(--color-green-bg); color: var(--color-green); }
  .icon-relations { background: var(--color-purple-bg); color: var(--color-purple); }

  .stat-content {
    display: flex;
    flex-direction: column;
  }

  .stat-value {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    color: var(--color-text);
    line-height: 1.2;
    letter-spacing: -0.025em;
  }

  .stat-label {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    font-weight: 500;
  }

  .section {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    margin-bottom: var(--space-lg);
    box-shadow: var(--shadow-sm);
    transition: box-shadow 0.2s ease;
  }
  
  .section:hover {
    box-shadow: var(--shadow-md);
  }

  .consolidation-status {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .status-item {
    display: flex;
    align-items: center;
    gap: var(--space-md);
    padding: var(--space-md);
    border-radius: var(--radius-md);
    transition: transform 0.15s ease;
  }
  
  .status-item:hover {
    transform: scale(1.01);
  }

  .status-item.pending {
    background: var(--color-warning-bg);
    color: var(--color-warning);
    border: 1px solid rgba(245, 158, 11, 0.2);
  }

  .status-item.ok {
    background: var(--color-success-bg);
    color: var(--color-success);
    border: 1px solid rgba(16, 185, 129, 0.2);
  }

  .status-count {
    font-weight: 700;
  }

  .distributions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
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
    padding: var(--space-sm) var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    border: 1px solid transparent;
    transition: background 0.15s ease;
  }
  
  .distribution-item:hover {
    background: var(--color-surface-hover);
  }

  .distribution-label {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    font-weight: 500;
  }

  .distribution-value {
    font-weight: 600;
    font-family: var(--font-mono);
    color: var(--color-text);
    font-size: var(--font-size-sm);
  }

  .relation-implies { color: var(--color-implies); font-weight: 500; }
  .relation-contradicts { color: var(--color-contradicts); font-weight: 500; }
  .relation-specializes { color: var(--color-specializes); font-weight: 500; }
  .relation-generalizes { color: var(--color-generalizes); font-weight: 500; }
  .relation-causes { color: var(--color-causes); font-weight: 500; }
  .relation-correlates { color: var(--color-correlates); font-weight: 500; }
  .relation-part_of { color: var(--color-part-of); font-weight: 500; }
  .relation-context_of { color: var(--color-context-of); font-weight: 500; }

  .loading,
  .error,
  .empty {
    padding: var(--space-2xl);
    text-align: center;
    color: var(--color-text-secondary);
    background: var(--color-surface);
    border-radius: var(--radius-lg);
    border: 1px solid var(--color-border);
  }

  .error {
    color: var(--color-error);
    background: var(--color-error-bg);
    border-color: var(--color-error);
  }
</style>
