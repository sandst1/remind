<script lang="ts">
  import { onMount } from 'svelte';
  import {
    concepts,
    conceptsTotal,
    conceptsLoading,
    conceptsError,
    conceptPath,
    currentDb,
  } from '../lib/stores';
  import { fetchConcepts, fetchConcept, fetchEpisode } from '../lib/api';
  import type { Concept, Episode, EpisodeType } from '../lib/types';
  import {
    Eye,
    Zap,
    CircleHelp,
    Brain,
    Heart,
    Search,
    ChevronRight,
    ChevronDown,
    X,
    ArrowRight
  } from 'lucide-svelte';

  let search = '';
  let page = 0;
  const pageSize = 20;
  let mounted = false;
  let detailsContainer: HTMLElement;
  let expandedEpisodes: Record<string, Episode | null> = {};
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  onMount(() => {
    mounted = true;
    loadConcepts();
  });

  // React to database changes
  $: if (mounted && $currentDb) {
    loadConcepts();
    conceptPath.set([]);
  }

  // Live filtering: trigger search when typing 2+ characters
  $: if (mounted && $currentDb && search.length >= 2) {
    debouncedSearch();
  }

  // Clear filter when search is emptied
  $: if (mounted && $currentDb && search === '') {
    if (debounceTimer) clearTimeout(debounceTimer);
    page = 0;
    loadConcepts();
  }

  function debouncedSearch() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      page = 0;
      loadConcepts();
    }, 300);
  }

  async function loadConcepts() {
    if (!$currentDb) return;

    conceptsLoading.set(true);
    conceptsError.set(null);

    try {
      const response = await fetchConcepts({
        offset: page * pageSize,
        limit: pageSize,
        search: search || undefined,
      });
      concepts.set(response.concepts);
      conceptsTotal.set(response.total);
    } catch (e) {
      conceptsError.set(e instanceof Error ? e.message : 'Failed to load concepts');
    } finally {
      conceptsLoading.set(false);
    }
  }

  async function selectConcept(concept: Concept) {
    // Fetch full concept details with episode data
    try {
      const fullConcept = await fetchConcept(concept.id);
      conceptPath.set([fullConcept]);
    } catch (e) {
      console.error('Failed to fetch concept:', e);
      conceptPath.set([concept]);
    }
  }

  let relationError: string | null = null;

  async function openRelatedConcept(targetId: string, pathIndex: number) {
    relationError = null;
    try {
      const concept = await fetchConcept(targetId);
      // Truncate path to current index and append new concept
      conceptPath.update(path => [...path.slice(0, pathIndex + 1), concept]);
      // Scroll to the new panel
      setTimeout(() => {
        if (detailsContainer) {
          detailsContainer.scrollLeft = detailsContainer.scrollWidth;
        }
      }, 50);
    } catch (e) {
      relationError = `Concept "${targetId}" not found`;
      setTimeout(() => relationError = null, 3000);
    }
  }

  function truncatePath(index: number) {
    conceptPath.update(path => path.slice(0, index + 1));
  }

  function closePath(index: number) {
    if (index === 0) {
      conceptPath.set([]);
    } else {
      conceptPath.update(path => path.slice(0, index));
    }
  }

  function handleSearch() {
    if (debounceTimer) clearTimeout(debounceTimer);
    page = 0;
    loadConcepts();
  }

  function nextPage() {
    page++;
    loadConcepts();
  }

  function prevPage() {
    if (page > 0) {
      page--;
      loadConcepts();
    }
  }

  function formatConfidence(confidence: number): string {
    return `${Math.round(confidence * 100)}%`;
  }

  function getConfidenceClass(confidence: number): string {
    if (confidence >= 0.7) return 'high';
    if (confidence >= 0.4) return 'medium';
    return 'low';
  }

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

  const episodeTypeIcons: Record<string, any> = {
    observation: Eye,
    decision: Zap,
    question: CircleHelp,
    meta: Brain,
    preference: Heart,
  };

  const episodeTypeLabels: Record<EpisodeType, string> = {
    observation: 'Observation',
    decision: 'Decision',
    question: 'Question',
    meta: 'Meta',
    preference: 'Preference',
  };

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

  async function toggleEpisodeExpand(episodeId: string) {
    if (expandedEpisodes[episodeId]) {
      expandedEpisodes = { ...expandedEpisodes, [episodeId]: null };
    } else {
      try {
        const episode = await fetchEpisode(episodeId);
        expandedEpisodes = { ...expandedEpisodes, [episodeId]: episode };
      } catch (e) {
        console.error('Failed to fetch episode:', e);
      }
    }
  }
</script>

<div class="concept-list">
  {#if relationError}
    <div class="error-toast">{relationError}</div>
  {/if}
  <div class="header">
    <h2>Concepts</h2>
    <div class="search-bar">
      <Search size={14} class="search-icon" />
      <input
        type="text"
        placeholder="Search concepts..."
        bind:value={search}
        onkeydown={(e) => e.key === 'Enter' && handleSearch()}
      />
      <!-- <button onclick={handleSearch}>Search</button> -->
    </div>
  </div>

  <div class="content">
    <div class="list-panel">
      {#if $conceptsLoading}
        <div class="loading">Loading concepts...</div>
      {:else if $conceptsError}
        <div class="error">{$conceptsError}</div>
      {:else if $concepts.length === 0}
        <div class="empty">No concepts found</div>
      {:else}
        <div class="concept-items">
          {#each $concepts as concept}
            <button
              class="concept-item"
              class:selected={$conceptPath.length > 0 && $conceptPath[0].id === concept.id}
              onclick={() => selectConcept(concept)}
            >
              <div class="concept-header">
                <span class="concept-confidence confidence-{getConfidenceClass(concept.confidence)}">
                  {formatConfidence(concept.confidence)}
                </span>
              </div>
              {#if concept.title}
                <div class="concept-title">{concept.title}</div>
              {/if}
              <div class="concept-summary">{concept.summary}</div>
              {#if concept.tags.length > 0}
                <div class="concept-tags">
                  {#each concept.tags.slice(0, 3) as tag}
                    <span class="tag">{tag}</span>
                  {/each}
                </div>
              {/if}
            </button>
          {/each}
        </div>

        <div class="pagination">
          <button onclick={prevPage} disabled={page === 0}>Previous</button>
          <span>Page {page + 1} of {Math.ceil($conceptsTotal / pageSize)}</span>
          <button onclick={nextPage} disabled={(page + 1) * pageSize >= $conceptsTotal}>Next</button>
        </div>
      {/if}
    </div>

    <div class="details-container" bind:this={detailsContainer}>
      {#if $conceptPath.length === 0}
        <div class="no-selection">
          Select a concept to view details
        </div>
      {:else}
        {#each $conceptPath as concept, index}
          <div class="detail-panel" class:first={index === 0}>
            <div class="detail-content">
              <div class="panel-header">
                <h3>
                  {#if index > 0}
                    <button class="back-btn" onclick={() => truncatePath(index - 1)}>
                      <ArrowRight size={16} style="transform: rotate(180deg)" />
                    </button>
                  {/if}
                  {concept.title || 'Concept Details'}
                </h3>
                <button class="close-btn" onclick={() => closePath(index)}>
                  <X size={20} />
                </button>
              </div>

              <div class="detail-section">
                <h4>Summary</h4>
                <p>{concept.summary}</p>
              </div>

              <div class="detail-meta">
                <div class="meta-item">
                  <span class="meta-label">Confidence</span>
                  <span class="meta-value confidence-{getConfidenceClass(concept.confidence)}">
                    {formatConfidence(concept.confidence)}
                  </span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">Instances</span>
                  <span class="meta-value">{concept.instance_count}</span>
                </div>
              </div>

              {#if concept.conditions}
                <div class="detail-section">
                  <h4>Conditions</h4>
                  <p class="conditions">{concept.conditions}</p>
                </div>
              {/if}

              {#if concept.exceptions.length > 0}
                <div class="detail-section">
                  <h4>Exceptions</h4>
                  <ul class="exceptions">
                    {#each concept.exceptions as exception}
                      <li>{exception}</li>
                    {/each}
                  </ul>
                </div>
              {/if}

              {#if concept.relations.length > 0}
                <div class="detail-section">
                  <h4>Relations</h4>
                  <div class="relations-list">
                    {#each concept.relations as relation}
                      <button
                        class="relation-item relation-{relation.type}"
                        onclick={() => openRelatedConcept(relation.target_id, index)}
                      >
                        <span class="relation-type">{relationTypeLabels[relation.type]}</span>
                        <span class="relation-target">{relation.target_id.substring(0, 8)}</span>
                        {#if relation.target_summary}
                          <span class="relation-summary">{relation.target_summary}</span>
                        {/if}
                        {#if relation.context}
                          <span class="relation-context">({relation.context})</span>
                        {/if}
                        <span class="relation-arrow">
                          <ArrowRight size={14} />
                        </span>
                      </button>
                    {/each}
                  </div>
                </div>
              {/if}

              {#if concept.source_episodes_data && concept.source_episodes_data.length > 0}
                <div class="detail-section">
                  <h4>Source Episodes ({concept.source_episodes.length})</h4>
                  <div class="source-episodes">
                    {#each concept.source_episodes_data as episode}
                      {@const expanded = expandedEpisodes[episode.id]}
                      <button
                        class="episode-item"
                        class:expanded={!!expanded}
                        onclick={() => toggleEpisodeExpand(episode.id)}
                      >
                        <div class="episode-collapsed">
                          <span class="episode-icon">
                            <svelte:component this={episodeTypeIcons[episode.type]} size={16} />
                          </span>
                          <span class="episode-content" class:expanded={!!expanded}>{episode.title || episode.content}</span>
                          <span class="episode-chevron">
                            {#if expanded}
                              <ChevronDown size={14} />
                            {:else}
                              <ChevronRight size={14} />
                            {/if}
                          </span>
                        </div>
                        {#if expanded}
                          <div class="episode-expanded">
                            <div class="episode-header">
                              <span class="episode-type type-{expanded.episode_type}">
                                {episodeTypeLabels[expanded.episode_type]}
                              </span>
                              <span class="episode-date">{formatDate(expanded.timestamp)}</span>
                              {#if !expanded.consolidated}
                                <span class="pending-badge">Pending</span>
                              {/if}
                            </div>
                            {#if expanded.title}
                              <div class="episode-title">{expanded.title}</div>
                            {/if}
                            <div class="episode-full-content">{expanded.content}</div>
                            {#if expanded.entity_ids.length > 0}
                              <div class="episode-entities">
                                {#each expanded.entity_ids as entityId}
                                  <span class="entity-tag">{entityId}</span>
                                {/each}
                              </div>
                            {/if}
                            <div class="episode-footer">
                              <span class="episode-id-label">ID: {expanded.id}</span>
                              {#if expanded.confidence < 1}
                                <span class="episode-confidence">
                                  Confidence: {Math.round(expanded.confidence * 100)}%
                                </span>
                              {/if}
                            </div>
                          </div>
                        {/if}
                      </button>
                    {/each}
                    {#if concept.source_episodes.length > 10}
                      <div class="more-episodes">
                        +{concept.source_episodes.length - 10} more episodes
                      </div>
                    {/if}
                  </div>
                </div>
              {:else if concept.source_episodes.length > 0}
                <div class="detail-section">
                  <h4>Source Episodes ({concept.source_episodes.length})</h4>
                  <div class="source-episodes-ids">
                    {#each concept.source_episodes as episodeId}
                      <span class="episode-id">{episodeId}</span>
                    {/each}
                  </div>
                </div>
              {/if}

              {#if concept.tags.length > 0}
                <div class="detail-section">
                  <h4>Tags</h4>
                  <div class="tags">
                    {#each concept.tags as tag}
                      <span class="tag">{tag}</span>
                    {/each}
                  </div>
                </div>
              {/if}
            </div>
          </div>
        {/each}
      {/if}
    </div>
  </div>
</div>

<style>
  .concept-list {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 80px);
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-lg);
  }

  h2 {
    font-size: var(--font-size-2xl);
    font-weight: 700;
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
    width: 250px;
    font-size: var(--font-size-sm);
    background: var(--color-surface);
    transition: all 0.15s ease;
  }
  
  .search-bar input:focus {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px var(--color-primary-bg);
  }

  .content {
    display: flex;
    gap: var(--space-lg);
    flex: 1;
    min-height: 0;
  }

  .list-panel {
    width: 400px;
    flex-shrink: 0;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .concept-items {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-sm);
  }

  .concept-item {
    display: block;
    width: 100%;
    padding: var(--space-md);
    margin-bottom: var(--space-sm);
    background: var(--color-bg);
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    text-align: left;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .concept-item:hover {
    border-color: var(--color-border);
  }

  .concept-item.selected {
    border-color: var(--color-primary);
    background: var(--color-primary-bg);
  }

  .concept-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: var(--space-xs);
    font-size: var(--font-size-sm);
  }

  .concept-confidence {
    font-weight: 600;
  }

  .confidence-high { color: var(--color-success); }
  .confidence-medium { color: var(--color-warning); }
  .confidence-low { color: var(--color-error); }

  .concept-title {
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--space-xs);
  }

  .concept-summary {
    color: var(--color-text);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .concept-tags {
    display: flex;
    gap: var(--space-xs);
    margin-top: var(--space-sm);
  }

  .tag {
    padding: 2px 8px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .pagination {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-md);
    border-top: 1px solid var(--color-border);
    background: var(--color-surface);
  }

  .pagination button {
    padding: var(--space-xs) var(--space-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    cursor: pointer;
    font-size: var(--font-size-sm);
    transition: all 0.15s ease;
  }
  
  .pagination button:hover:not(:disabled) {
    background: var(--color-surface-hover);
  }

  .pagination button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* Horizontal tree navigation */
  .details-container {
    flex: 1;
    display: flex;
    gap: var(--space-md);
    overflow-x: auto;
    padding-bottom: var(--space-md);
  }

  .detail-panel {
    min-width: 400px;
    max-width: 450px;
    flex-shrink: 0;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  .detail-panel.first {
    border-color: var(--color-primary);
    border-width: 1px;
    box-shadow: var(--shadow-sm);
  }

  .detail-content {
    padding: var(--space-lg);
  }

  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-lg);
  }

  .panel-header h3 {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    font-size: var(--font-size-lg);
    margin: 0;
    font-weight: 600;
  }

  .back-btn {
    padding: var(--space-xs);
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--color-text-secondary);
  }

  .close-btn {
    padding: var(--space-xs);
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--color-text-secondary);
  }

  .close-btn:hover, .back-btn:hover {
    background: var(--color-surface-hover);
    color: var(--color-text);
  }

  .detail-section {
    margin-bottom: var(--space-lg);
  }

  .detail-section h4 {
    margin-bottom: var(--space-sm);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    font-weight: 600;
  }

  .detail-meta {
    display: flex;
    gap: var(--space-lg);
    margin-bottom: var(--space-lg);
    padding: var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
  }

  .meta-item {
    display: flex;
    flex-direction: column;
  }

  .meta-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    font-weight: 600;
  }

  .meta-value {
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--color-text);
  }

  .conditions {
    padding: var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-md);
    font-style: italic;
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
  }

  .exceptions {
    margin: 0;
    padding-left: var(--space-lg);
  }

  .exceptions li {
    margin-bottom: var(--space-xs);
    color: var(--color-text);
  }

  .relations-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .relation-item {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    border-left: 3px solid;
    cursor: pointer;
    text-align: left;
    width: 100%;
    transition: background 0.15s ease;
  }

  .relation-item:hover {
    background: var(--color-surface-hover);
  }

  .relation-implies { border-color: var(--color-implies); }
  .relation-contradicts { border-color: var(--color-contradicts); }
  .relation-specializes { border-color: var(--color-specializes); }
  .relation-generalizes { border-color: var(--color-generalizes); }
  .relation-causes { border-color: var(--color-causes); }
  .relation-correlates { border-color: var(--color-correlates); }
  .relation-part_of { border-color: var(--color-part-of); }
  .relation-context_of { border-color: var(--color-context-of); }

  .relation-type {
    font-weight: 600;
    flex-shrink: 0;
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: uppercase;
  }

  .relation-target {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text);
    flex-shrink: 0;
    font-weight: 500;
  }

  .relation-summary {
    flex: 1;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    display: -webkit-box;
    -webkit-line-clamp: 1;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .relation-context {
    color: var(--color-text-muted);
    font-size: var(--font-size-xs);
    width: 100%;
    margin-top: var(--space-xs);
  }

  .relation-arrow {
    margin-left: auto;
    color: var(--color-text-muted);
    flex-shrink: 0;
  }

  .source-episodes {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .episode-item {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    width: 100%;
    text-align: left;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .episode-item:hover {
    border-color: var(--color-text-muted);
  }

  .episode-item.expanded {
    border-color: var(--color-primary);
    background: var(--color-surface);
    box-shadow: var(--shadow-sm);
  }

  .episode-collapsed {
    display: flex;
    gap: var(--space-sm);
    align-items: flex-start;
  }

  .episode-icon {
    flex-shrink: 0;
    color: var(--color-text-secondary);
  }

  .episode-content {
    flex: 1;
    font-size: var(--font-size-sm);
    line-height: 1.5;
    color: var(--color-text-secondary);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .episode-content.expanded {
    display: none;
  }

  .episode-chevron {
    flex-shrink: 0;
    color: var(--color-text-muted);
  }

  .episode-expanded {
    padding-top: var(--space-sm);
    border-top: 1px solid var(--color-border);
    margin-top: var(--space-xs);
  }

  .episode-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-sm);
  }

  .episode-type {
    font-size: var(--font-size-xs);
    font-weight: 600;
    padding: 2px 8px;
    border-radius: var(--radius-full);
    text-transform: uppercase;
  }

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
    padding: 2px 6px;
    background: var(--color-warning-bg);
    color: var(--color-warning);
    border-radius: var(--radius-sm);
    font-weight: 500;
  }

  .episode-title {
    font-weight: 600;
    font-size: var(--font-size-sm);
    color: var(--color-text);
    margin-bottom: var(--space-sm);
  }

  .episode-full-content {
    line-height: 1.6;
    color: var(--color-text);
    white-space: pre-wrap;
    margin-bottom: var(--space-md);
  }

  .episode-entities {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    margin-bottom: var(--space-md);
  }

  .entity-tag {
    padding: 2px 8px;
    background: var(--color-zinc-100);
    border: 1px solid var(--color-zinc-200);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    font-family: var(--font-mono);
    color: var(--color-text-secondary);
  }

  .episode-footer {
    display: flex;
    gap: var(--space-md);
    padding-top: var(--space-sm);
    border-top: 1px solid var(--color-border);
    font-size: var(--font-size-xs);
    color: var(--color-text-muted);
  }

  .episode-id-label {
    font-family: var(--font-mono);
  }

  .more-episodes {
    padding: var(--space-sm);
    text-align: center;
    font-size: var(--font-size-sm);
    color: var(--color-text-muted);
    background: var(--color-bg);
    border-radius: var(--radius-md);
  }

  .source-episodes-ids {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
  }

  .episode-id {
    padding: 2px 6px;
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
  }

  .no-selection {
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 400px;
    height: 100%;
    color: var(--color-text-muted);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
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

  .error-toast {
    position: fixed;
    top: var(--space-lg);
    right: var(--space-lg);
    padding: var(--space-md) var(--space-lg);
    background: var(--color-contradicts);
    color: white;
    border-radius: var(--radius-md);
    z-index: 1000;
    animation: fadeIn 0.2s ease;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
