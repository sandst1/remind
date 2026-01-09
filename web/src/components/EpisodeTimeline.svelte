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
  import { Eye, Zap, CircleHelp, Brain, Heart, Search, Filter } from 'lucide-svelte';

  let filterType: EpisodeType | '' = '';
  let filterConsolidated: boolean | null = null;
  let search = '';
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
        search: search || undefined,
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

  const episodeTypeIcons: Record<EpisodeType, any> = {
    observation: Eye,
    decision: Zap,
    question: CircleHelp,
    meta: Brain,
    preference: Heart,
  };
</script>

<div class="episode-timeline">
  <div class="header">
    <h2>Episodes</h2>
    <div class="filters">
      <div class="search-bar">
        <div class="search-icon">
          <Search size={16} />
        </div>
        <input
          type="text"
          placeholder="Search episodes..."
          bind:value={search}
          onkeydown={(e) => e.key === 'Enter' && applyFilters()}
        />
      </div>
      
      <div class="select-wrapper">
        <Filter size={14} class="select-icon" />
        <select bind:value={filterType} onchange={applyFilters}>
          <option value="">All types</option>
          <option value="observation">Observations</option>
          <option value="decision">Decisions</option>
          <option value="question">Questions</option>
          <option value="meta">Meta</option>
          <option value="preference">Preferences</option>
        </select>
      </div>

      <div class="select-wrapper">
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
            <span class="episode-icon">
              <svelte:component this={episodeTypeIcons[episode.episode_type]} size={16} />
            </span>
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
            {#if episode.title}
              <div class="episode-title">{episode.title}</div>
            {/if}
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
    margin: 0 auto;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-xl);
  }

  h2 {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    color: var(--color-text);
  }

  .filters {
    display: flex;
    gap: var(--space-sm);
    align-items: center;
  }

  .search-bar {
    position: relative;
    display: flex;
    align-items: center;
  }

  .search-bar input {
    padding: var(--space-sm) var(--space-md) var(--space-sm) 36px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    width: 240px;
    font-size: var(--font-size-sm);
    background: var(--color-surface);
    transition: all 0.15s ease;
  }

  .search-bar input:focus {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px var(--color-primary-bg);
  }

  .select-wrapper {
    position: relative;
    display: flex;
    align-items: center;
  }

  .search-icon {
    position: absolute;
    left: var(--space-sm);
    margin-right: var(--space-xs);
    top: 65%;
    transform: translateY(-65%);
  }

  .select-icon {
    position: absolute;
    left: var(--space-sm);
    color: var(--color-text-muted);
    margin-right: var(--space-sm);
    pointer-events: none;
    z-index: 1;
  }

  .filters select {
    padding: var(--space-sm) var(--space-md);
    padding-left: 30px; /* Make room for icon if needed, though only one has icon */
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--font-size-sm);
    cursor: pointer;
    transition: all 0.15s ease;
    margin-left: var(--space-sm);
  }
  
  /* Helper for the one without icon */
  .select-wrapper:last-child select {
    padding-left: var(--space-md);
  }

  .filters select:hover {
    border-color: var(--color-zinc-400);
  }

  .timeline {
    position: relative;
    padding-left:64px;
  }

  .timeline::before {
    content: '';
    position: absolute;
    left: 31px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--color-border);
    margin-top: var(--space-sm);
  }

  .timeline-item {
    position: relative;
    margin-bottom: var(--space-lg);
  }

  .timeline-marker {
    position: absolute;
    left: -48px;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface);
    border: 2px solid var(--color-border);
    border-radius: 50%;
    color: var(--color-text-secondary);
    z-index: 2;
    transition: all 0.2s ease;
    margin-top: var(--space-sm);
  }

  .timeline-item.consolidated .timeline-marker {
    border-color: var(--color-primary);
    color: var(--color-primary);
    background: var(--color-primary-bg);
  }

  .timeline-content {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    box-shadow: var(--shadow-sm);
    transition: box-shadow 0.2s ease;
  }
  
  .timeline-content:hover {
    box-shadow: var(--shadow-md);
  }

  .episode-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-md);
  }

  .episode-title {
    font-weight: 600;
    font-size: var(--font-size-base);
    color: var(--color-text);
    margin-bottom: var(--space-sm);
  }

  .episode-type {
    font-size: var(--font-size-xs);
    font-weight: 600;
    padding: 4px 10px;
    border-radius: var(--radius-full);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  /* Refined type colors using variables */
  .type-observation { background: var(--color-blue-bg); color: var(--color-blue); }
  .type-decision { background: var(--color-orange-bg); color: var(--color-orange); }
  .type-question { background: var(--color-purple-bg); color: var(--color-purple); }
  .type-meta { background: var(--color-green-bg); color: var(--color-green); }
  .type-preference { background: var(--color-pink-bg); color: var(--color-pink); }

  .episode-date {
    font-size: var(--font-size-xs);
    color: var(--color-text-muted);
    margin-left: auto;
    font-family: var(--font-mono);
  }

  .pending-badge {
    font-size: var(--font-size-xs);
    padding: 2px 8px;
    background: var(--color-warning-bg);
    color: var(--color-warning);
    border: 1px solid var(--color-warning);
    border-radius: var(--radius-full);
    font-weight: 500;
  }

  .episode-content {
    line-height: 1.6;
    color: var(--color-text);
    white-space: pre-wrap;
    font-size: var(--font-size-base);
  }

  .episode-entities {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    margin-top: var(--space-md);
  }

  .entity-tag {
    padding: 4px 10px;
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    font-family: var(--font-mono);
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
  }
  
  .entity-tag:hover {
    border-color: var(--color-zinc-300);
  }

  .episode-footer {
    display: flex;
    gap: var(--space-md);
    margin-top: var(--space-md);
    padding-top: var(--space-md);
    border-top: 1px solid var(--color-zinc-100);
    font-size: var(--font-size-xs);
    color: var(--color-text-muted);
  }
  
  .episode-id {
    font-family: var(--font-mono);
  }

  .pagination {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--space-xl);
    padding: var(--space-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-sm);
  }

  .pagination button {
    padding: var(--space-xs) var(--space-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text);
    font-size: var(--font-size-sm);
    font-weight: 500;
    transition: all 0.15s ease;
  }

  .pagination button:hover:not(:disabled) {
    background: var(--color-surface-hover);
    border-color: var(--color-zinc-300);
  }

  .pagination button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    background: var(--color-bg);
  }

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
