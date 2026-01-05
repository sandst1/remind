<script lang="ts">
  import { onMount } from 'svelte';
  import {
    concepts,
    conceptsTotal,
    conceptsLoading,
    conceptsError,
    selectedConcept,
    currentDb,
  } from '../lib/stores';
  import { fetchConcepts, fetchConcept } from '../lib/api';
  import type { Concept } from '../lib/types';

  let search = '';
  let page = 0;
  const pageSize = 20;
  let mounted = false;

  onMount(() => {
    mounted = true;
    loadConcepts();
  });

  // React to database changes
  $: if (mounted && $currentDb) {
    loadConcepts();
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
    selectedConcept.set(concept);
    // Could fetch full details here if needed
  }

  function handleSearch() {
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
</script>

<div class="concept-list">
  <div class="header">
    <h2>Concepts</h2>
    <div class="search-bar">
      <input
        type="text"
        placeholder="Search concepts..."
        bind:value={search}
        onkeydown={(e) => e.key === 'Enter' && handleSearch()}
      />
      <button onclick={handleSearch}>Search</button>
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
              class:selected={$selectedConcept?.id === concept.id}
              onclick={() => selectConcept(concept)}
            >
              <div class="concept-header">
                <span class="concept-confidence confidence-{getConfidenceClass(concept.confidence)}">
                  {formatConfidence(concept.confidence)}
                </span>
                <span class="concept-count">{concept.instance_count}x</span>
              </div>
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

    <div class="detail-panel">
      {#if $selectedConcept}
        <div class="detail-content">
          <h3>Concept Details</h3>

          <div class="detail-section">
            <h4>Summary</h4>
            <p>{$selectedConcept.summary}</p>
          </div>

          <div class="detail-meta">
            <div class="meta-item">
              <span class="meta-label">Confidence</span>
              <span class="meta-value confidence-{getConfidenceClass($selectedConcept.confidence)}">
                {formatConfidence($selectedConcept.confidence)}
              </span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Instances</span>
              <span class="meta-value">{$selectedConcept.instance_count}</span>
            </div>
          </div>

          {#if $selectedConcept.conditions}
            <div class="detail-section">
              <h4>Conditions</h4>
              <p class="conditions">{$selectedConcept.conditions}</p>
            </div>
          {/if}

          {#if $selectedConcept.exceptions.length > 0}
            <div class="detail-section">
              <h4>Exceptions</h4>
              <ul class="exceptions">
                {#each $selectedConcept.exceptions as exception}
                  <li>{exception}</li>
                {/each}
              </ul>
            </div>
          {/if}

          {#if $selectedConcept.relations.length > 0}
            <div class="detail-section">
              <h4>Relations</h4>
              <div class="relations-list">
                {#each $selectedConcept.relations as relation}
                  <div class="relation-item relation-{relation.type}">
                    <span class="relation-type">{relationTypeLabels[relation.type]}</span>
                    <span class="relation-target">{relation.target_id}</span>
                    {#if relation.context}
                      <span class="relation-context">({relation.context})</span>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          {#if $selectedConcept.source_episodes.length > 0}
            <div class="detail-section">
              <h4>Source Episodes ({$selectedConcept.source_episodes.length})</h4>
              <div class="source-episodes">
                {#each $selectedConcept.source_episodes as episodeId}
                  <span class="episode-id">{episodeId}</span>
                {/each}
              </div>
            </div>
          {/if}

          {#if $selectedConcept.tags.length > 0}
            <div class="detail-section">
              <h4>Tags</h4>
              <div class="tags">
                {#each $selectedConcept.tags as tag}
                  <span class="tag">{tag}</span>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {:else}
        <div class="no-selection">
          Select a concept to view details
        </div>
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
  }

  .search-bar {
    display: flex;
    gap: var(--space-sm);
  }

  .search-bar input {
    padding: var(--space-sm) var(--space-md);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    width: 250px;
  }

  .search-bar button {
    padding: var(--space-sm) var(--space-md);
    background: var(--color-primary);
    color: white;
    border: none;
    border-radius: var(--radius-md);
  }

  .content {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-lg);
    flex: 1;
    min-height: 0;
  }

  .list-panel {
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
    background: rgba(3, 102, 214, 0.05);
  }

  .concept-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: var(--space-xs);
    font-size: var(--font-size-sm);
  }

  .concept-confidence {
    font-weight: 500;
  }

  .confidence-high { color: var(--color-confidence-high); }
  .confidence-medium { color: var(--color-confidence-medium); }
  .confidence-low { color: var(--color-confidence-low); }

  .concept-count {
    color: var(--color-text-muted);
    font-family: var(--font-mono);
  }

  .concept-summary {
    color: var(--color-text);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .concept-tags {
    display: flex;
    gap: var(--space-xs);
    margin-top: var(--space-sm);
  }

  .tag {
    padding: 2px 6px;
    background: var(--color-border);
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

  .detail-panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow-y: auto;
  }

  .detail-content {
    padding: var(--space-lg);
  }

  .detail-content h3 {
    margin-bottom: var(--space-lg);
    font-size: var(--font-size-lg);
  }

  .detail-section {
    margin-bottom: var(--space-lg);
  }

  .detail-section h4 {
    margin-bottom: var(--space-sm);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
  }

  .detail-meta {
    display: flex;
    gap: var(--space-lg);
    margin-bottom: var(--space-lg);
    padding: var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-md);
  }

  .meta-item {
    display: flex;
    flex-direction: column;
  }

  .meta-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .meta-value {
    font-size: var(--font-size-lg);
    font-weight: 600;
  }

  .conditions {
    padding: var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-md);
    font-style: italic;
  }

  .exceptions {
    margin: 0;
    padding-left: var(--space-lg);
  }

  .exceptions li {
    margin-bottom: var(--space-xs);
  }

  .relations-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .relation-item {
    padding: var(--space-sm) var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-md);
    border-left: 3px solid;
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
    font-weight: 500;
    margin-right: var(--space-sm);
  }

  .relation-target {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
  }

  .relation-context {
    color: var(--color-text-muted);
    font-size: var(--font-size-sm);
    margin-left: var(--space-sm);
  }

  .source-episodes {
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
    height: 100%;
    color: var(--color-text-muted);
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
