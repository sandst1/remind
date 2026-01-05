<script lang="ts">
  import { onMount } from 'svelte';
  import {
    episodes,
    episodesTotal,
    episodesLoading,
    episodesError,
    currentDb,
  } from '../lib/stores';
  import { fetchEpisodes } from '../lib/api';
  import type { Episode, EpisodeType } from '../lib/types';

  let filterType: EpisodeType | '' = '';
  let filterConsolidated: boolean | null = null;
  let page = 0;
  const pageSize = 20;
  let mounted = false;

  onMount(() => {
    mounted = true;
    loadEpisodes();
  });

  // React to database changes
  $: if (mounted && $currentDb) {
    loadEpisodes();
  }

  async function loadEpisodes() {
    if (!$currentDb) return;

    episodesLoading.set(true);
    episodesError.set(null);

    try {
      const response = await fetchEpisodes({
        offset: page * pageSize,
        limit: pageSize,
        type: filterType || undefined,
        consolidated: filterConsolidated ?? undefined,
      });
      episodes.set(response.episodes);
      episodesTotal.set(response.total);
    } catch (e) {
      episodesError.set(e instanceof Error ? e.message : 'Failed to load episodes');
    } finally {
      episodesLoading.set(false);
    }
  }

  function applyFilters() {
    page = 0;
    loadEpisodes();
  }

  function nextPage() {
    page++;
    loadEpisodes();
  }

  function prevPage() {
    if (page > 0) {
      page--;
      loadEpisodes();
    }
  }

  function formatDate(isoDate: string): string {
    const date = new Date(isoDate);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  const episodeTypeLabels: Record<EpisodeType, string> = {
    observation: 'Observation',
    decision: 'Decision',
    question: 'Question',
    meta: 'Meta',
    preference: 'Preference',
  };

  const episodeTypeIcons: Record<EpisodeType, string> = {
    observation: '👁️',
    decision: '⚡',
    question: '❓',
    meta: '🧠',
    preference: '❤️',
  };
</script>

<div class="episode-timeline">
  <div class="header">
    <h2>Episodes</h2>
    <div class="filters">
      <select bind:value={filterType} onchange={applyFilters}>
        <option value="">All types</option>
        <option value="observation">Observations</option>
        <option value="decision">Decisions</option>
        <option value="question">Questions</option>
        <option value="meta">Meta</option>
        <option value="preference">Preferences</option>
      </select>

      <select
        bind:value={filterConsolidated}
        onchange={applyFilters}
      >
        <option value={null}>All status</option>
        <option value={true}>Consolidated</option>
        <option value={false}>Pending</option>
      </select>
    </div>
  </div>

  {#if $episodesLoading}
    <div class="loading">Loading episodes...</div>
  {:else if $episodesError}
    <div class="error">{$episodesError}</div>
  {:else if $episodes.length === 0}
    <div class="empty">No episodes found</div>
  {:else}
    <div class="timeline">
      {#each $episodes as episode}
        <div class="timeline-item" class:consolidated={episode.consolidated}>
          <div class="timeline-marker">
            <span class="episode-icon">{episodeTypeIcons[episode.episode_type]}</span>
          </div>
          <div class="timeline-content">
            <div class="episode-header">
              <span class="episode-type type-{episode.episode_type}">
                {episodeTypeLabels[episode.episode_type]}
              </span>
              <span class="episode-date">{formatDate(episode.timestamp)}</span>
              {#if !episode.consolidated}
                <span class="pending-badge">Pending</span>
              {/if}
            </div>
            <div class="episode-content">{episode.content}</div>
            {#if episode.entity_ids.length > 0}
              <div class="episode-entities">
                {#each episode.entity_ids as entityId}
                  <span class="entity-tag">{entityId}</span>
                {/each}
              </div>
            {/if}
            <div class="episode-footer">
              <span class="episode-id">ID: {episode.id}</span>
              {#if episode.confidence < 1}
                <span class="episode-confidence">
                  Confidence: {Math.round(episode.confidence * 100)}%
                </span>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>

    <div class="pagination">
      <button onclick={prevPage} disabled={page === 0}>Previous</button>
      <span>Page {page + 1} of {Math.ceil($episodesTotal / pageSize)}</span>
      <button onclick={nextPage} disabled={(page + 1) * pageSize >= $episodesTotal}>Next</button>
    </div>
  {/if}
</div>

<style>
  .episode-timeline {
    max-width: 800px;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-lg);
  }

  h2 {
    font-size: var(--font-size-2xl);
  }

  .filters {
    display: flex;
    gap: var(--space-sm);
  }

  .filters select {
    padding: var(--space-sm) var(--space-md);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }

  .timeline {
    position: relative;
    padding-left: 40px;
  }

  .timeline::before {
    content: '';
    position: absolute;
    left: 15px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--color-border);
  }

  .timeline-item {
    position: relative;
    margin-bottom: var(--space-lg);
  }

  .timeline-marker {
    position: absolute;
    left: -40px;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface);
    border: 2px solid var(--color-border);
    border-radius: 50%;
    font-size: var(--font-size-base);
  }

  .timeline-item.consolidated .timeline-marker {
    border-color: var(--color-implies);
  }

  .timeline-content {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-md);
  }

  .episode-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-sm);
  }

  .episode-type {
    font-size: var(--font-size-xs);
    font-weight: 500;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    text-transform: uppercase;
  }

  .type-observation { background: #e3f2fd; color: #1565c0; }
  .type-decision { background: #fff3e0; color: #e65100; }
  .type-question { background: #f3e5f5; color: #7b1fa2; }
  .type-meta { background: #e8f5e9; color: #2e7d32; }
  .type-preference { background: #fce4ec; color: #c2185b; }

  .episode-date {
    font-size: var(--font-size-sm);
    color: var(--color-text-muted);
    margin-left: auto;
  }

  .pending-badge {
    font-size: var(--font-size-xs);
    padding: 2px 6px;
    background: #fff3cd;
    color: #856404;
    border-radius: var(--radius-sm);
  }

  .episode-content {
    line-height: 1.6;
    color: var(--color-text);
    white-space: pre-wrap;
  }

  .episode-entities {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    margin-top: var(--space-md);
  }

  .entity-tag {
    padding: 2px 8px;
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-sm);
    font-family: var(--font-mono);
  }

  .episode-footer {
    display: flex;
    gap: var(--space-md);
    margin-top: var(--space-md);
    padding-top: var(--space-sm);
    border-top: 1px solid var(--color-border);
    font-size: var(--font-size-xs);
    color: var(--color-text-muted);
  }

  .pagination {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--space-lg);
    padding: var(--space-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
  }

  .pagination button {
    padding: var(--space-xs) var(--space-md);
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    cursor: pointer;
  }

  .pagination button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

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
