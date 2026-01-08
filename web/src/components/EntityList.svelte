<script lang="ts">
  import { onMount } from 'svelte';
  import {
    entities,
    entitiesTotal,
    entitiesLoading,
    entitiesError,
    currentDb,
  } from '../lib/stores';
  import { fetchEntities, fetchEntityEpisodes, fetchEntityConcepts } from '../lib/api';
  import type { Entity, Episode, Concept, EntityType } from '../lib/types';

  let filterType: EntityType | '' = '';
  let mounted = false;

  // Selected entity detail
  let selectedEntity: Entity | null = null;
  let relatedEpisodes: Episode[] = [];
  let relatedConcepts: Concept[] = [];
  let detailLoading = false;

  onMount(() => {
    mounted = true;
    loadEntities();
  });

  // React to database changes
  $: if (mounted && $currentDb) {
    loadEntities();
    selectedEntity = null;
    relatedEpisodes = [];
    relatedConcepts = [];
  }

  async function loadEntities() {
    if (!$currentDb) return;

    entitiesLoading.set(true);
    entitiesError.set(null);

    try {
      const response = await fetchEntities({
        type: filterType || undefined,
      });
      entities.set(response.entities);
      entitiesTotal.set(response.total);
    } catch (e) {
      entitiesError.set(e instanceof Error ? e.message : 'Failed to load entities');
    } finally {
      entitiesLoading.set(false);
    }
  }

  async function selectEntity(entity: Entity) {
    selectedEntity = entity;
    detailLoading = true;
    relatedEpisodes = [];
    relatedConcepts = [];

    try {
      const [episodesRes, conceptsRes] = await Promise.all([
        fetchEntityEpisodes(entity.id),
        fetchEntityConcepts(entity.id),
      ]);
      relatedEpisodes = episodesRes.episodes;
      relatedConcepts = conceptsRes.concepts;
    } catch (e) {
      console.error('Failed to load entity details:', e);
    } finally {
      detailLoading = false;
    }
  }

  function applyFilter() {
    loadEntities();
  }

  function clearSelection() {
    selectedEntity = null;
    relatedEpisodes = [];
    relatedConcepts = [];
  }

  const entityTypeLabels: Record<EntityType, string> = {
    file: 'File',
    function: 'Function',
    class: 'Class',
    module: 'Module',
    concept: 'Concept',
    person: 'Person',
    project: 'Project',
    tool: 'Tool',
    other: 'Other',
  };

  const entityTypeIcons: Record<EntityType, string> = {
    file: '📄',
    function: '⚡',
    class: '📦',
    module: '📁',
    concept: '💡',
    person: '👤',
    project: '🏗️',
    tool: '🔧',
    other: '📎',
  };

  const episodeTypeIcons: Record<string, string> = {
    observation: '👁️',
    decision: '⚡',
    question: '❓',
    meta: '🧠',
    preference: '❤️',
  };

  function formatDate(isoDate: string): string {
    return new Date(isoDate).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  function formatConfidence(confidence: number): string {
    return `${Math.round(confidence * 100)}%`;
  }

  function getConfidenceClass(confidence: number): string {
    if (confidence >= 0.7) return 'high';
    if (confidence >= 0.4) return 'medium';
    return 'low';
  }
</script>

<div class="entity-list">
  <div class="header">
    <h2>Entities</h2>
    <div class="filters">
      <select bind:value={filterType} onchange={applyFilter}>
        <option value="">All types</option>
        <option value="file">Files</option>
        <option value="function">Functions</option>
        <option value="class">Classes</option>
        <option value="module">Modules</option>
        <option value="concept">Concepts</option>
        <option value="person">People</option>
        <option value="project">Projects</option>
        <option value="tool">Tools</option>
        <option value="other">Other</option>
      </select>
    </div>
  </div>

  <div class="content">
    <div class="list-panel">
      {#if $entitiesLoading}
        <div class="loading">Loading entities...</div>
      {:else if $entitiesError}
        <div class="error">{$entitiesError}</div>
      {:else if $entities.length === 0}
        <div class="empty">No entities found</div>
      {:else}
        <div class="entity-items">
          {#each $entities as entity}
            <button
              class="entity-item"
              class:selected={selectedEntity?.id === entity.id}
              onclick={() => selectEntity(entity)}
            >
              <span class="entity-icon">{entityTypeIcons[entity.type]}</span>
              <div class="entity-info">
                <div class="entity-id">{entity.id}</div>
                {#if entity.display_name && entity.display_name !== entity.id}
                  <div class="entity-name">{entity.display_name}</div>
                {/if}
              </div>
              <span class="entity-count">{entity.mention_count || 0}</span>
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <div class="detail-panel">
      {#if !selectedEntity}
        <div class="no-selection">
          Select an entity to view details
        </div>
      {:else}
        <div class="detail-content">
          <div class="panel-header">
            <h3>
              <span class="entity-type-icon">{entityTypeIcons[selectedEntity.type]}</span>
              {selectedEntity.display_name || selectedEntity.id}
            </h3>
            <button class="close-btn" onclick={clearSelection}>×</button>
          </div>

          <div class="detail-meta">
            <div class="meta-item">
              <span class="meta-label">Type</span>
              <span class="meta-value">{entityTypeLabels[selectedEntity.type]}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">ID</span>
              <span class="meta-value mono">{selectedEntity.id}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Mentions</span>
              <span class="meta-value">{selectedEntity.mention_count || 0}</span>
            </div>
          </div>

          {#if detailLoading}
            <div class="loading">Loading details...</div>
          {:else}
            {#if relatedConcepts.length > 0}
              <div class="detail-section">
                <h4>Related Concepts ({relatedConcepts.length})</h4>
                <div class="related-list">
                  {#each relatedConcepts as concept}
                    <div class="related-item concept-item">
                      <div class="related-summary">{concept.summary}</div>
                      <span class="related-meta confidence {getConfidenceClass(concept.confidence)}">
                        {formatConfidence(concept.confidence)} confidence
                      </span>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            {#if relatedEpisodes.length > 0}
              <div class="detail-section">
                <h4>Mentioning Episodes ({relatedEpisodes.length})</h4>
                <div class="related-list">
                  {#each relatedEpisodes.slice(0, 20) as episode}
                    <div class="related-item episode-item">
                      <div class="episode-header">
                        <span class="episode-type-icon">{episodeTypeIcons[episode.episode_type] || '📝'}</span>
                        <span class="episode-date">{formatDate(episode.timestamp)}</span>
                        {#if episode.consolidated}
                          <span class="episode-status consolidated">Consolidated</span>
                        {:else}
                          <span class="episode-status pending">Pending</span>
                        {/if}
                      </div>
                      <div class="episode-preview">{episode.content.slice(0, 200)}{episode.content.length > 200 ? '...' : ''}</div>
                    </div>
                  {/each}
                  {#if relatedEpisodes.length > 20}
                    <div class="more-items">+{relatedEpisodes.length - 20} more episodes</div>
                  {/if}
                </div>
              </div>
            {/if}

            {#if relatedConcepts.length === 0 && relatedEpisodes.length === 0}
              <div class="empty">No related concepts or episodes found</div>
            {/if}
          {/if}
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .entity-list {
    display: flex;
    flex-direction: column;
    height: 100%;
    max-height: calc(100vh - var(--space-lg) * 2);
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-md);
    flex-shrink: 0;
  }

  .header h2 {
    margin: 0;
    font-size: var(--font-size-xl);
  }

  .filters {
    display: flex;
    gap: var(--space-sm);
  }

  .filters select {
    padding: var(--space-xs) var(--space-sm);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--font-size-sm);
  }

  .content {
    display: flex;
    gap: var(--space-md);
    flex: 1;
    min-height: 0;
  }

  .list-panel {
    width: 400px;
    flex-shrink: 0;
    overflow-y: auto;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .entity-items {
    display: flex;
    flex-direction: column;
  }

  .entity-item {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    border: none;
    border-bottom: 1px solid var(--color-border);
    background: transparent;
    text-align: left;
    cursor: pointer;
    transition: background-color 0.15s ease;
  }

  .entity-item:last-child {
    border-bottom: none;
  }

  .entity-item:hover {
    background: var(--color-bg);
  }

  .entity-item.selected {
    background: var(--color-primary);
    color: white;
  }

  .entity-item.selected .entity-id,
  .entity-item.selected .entity-name,
  .entity-item.selected .entity-count {
    color: white;
  }

  .entity-icon {
    font-size: var(--font-size-lg);
    flex-shrink: 0;
  }

  .entity-info {
    flex: 1;
    min-width: 0;
    overflow: hidden;
  }

  .entity-id {
    font-size: var(--font-size-sm);
    font-family: var(--font-mono);
    color: var(--color-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .entity-name {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .entity-count {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    background: var(--color-bg);
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    flex-shrink: 0;
  }

  .entity-item.selected .entity-count {
    background: rgba(255, 255, 255, 0.2);
  }

  .detail-panel {
    flex: 1;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    overflow-y: auto;
  }

  .no-selection {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-text-secondary);
    font-size: var(--font-size-base);
  }

  .detail-content {
    padding: var(--space-md);
  }

  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: var(--space-md);
  }

  .panel-header h3 {
    margin: 0;
    font-size: var(--font-size-lg);
    display: flex;
    align-items: center;
    gap: var(--space-xs);
  }

  .entity-type-icon {
    font-size: var(--font-size-xl);
  }

  .close-btn {
    background: none;
    border: none;
    font-size: var(--font-size-xl);
    color: var(--color-text-secondary);
    cursor: pointer;
    padding: 0;
    line-height: 1;
  }

  .close-btn:hover {
    color: var(--color-text);
  }

  .detail-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-md);
    margin-bottom: var(--space-lg);
    padding: var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-md);
  }

  .meta-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .meta-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: uppercase;
  }

  .meta-value {
    font-size: var(--font-size-sm);
    color: var(--color-text);
  }

  .meta-value.mono {
    font-family: var(--font-mono);
  }

  .detail-section {
    margin-bottom: var(--space-lg);
  }

  .detail-section h4 {
    margin: 0 0 var(--space-sm) 0;
    font-size: var(--font-size-base);
    color: var(--color-text-secondary);
  }

  .related-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .related-item {
    padding: var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
  }

  .concept-item .related-summary {
    font-size: var(--font-size-sm);
    color: var(--color-text);
    margin-bottom: var(--space-xs);
  }

  .related-meta {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .confidence.high {
    color: var(--color-success);
  }

  .confidence.medium {
    color: var(--color-warning);
  }

  .confidence.low {
    color: var(--color-error);
  }

  .episode-item .episode-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-xs);
  }

  .episode-type-icon {
    font-size: var(--font-size-sm);
  }

  .episode-date {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .episode-status {
    font-size: var(--font-size-xs);
    padding: 1px 6px;
    border-radius: var(--radius-sm);
  }

  .episode-status.consolidated {
    background: var(--color-success-bg, #e6f4ea);
    color: var(--color-success, #1e7e34);
  }

  .episode-status.pending {
    background: var(--color-warning-bg, #fff8e6);
    color: var(--color-warning, #bf8c00);
  }

  .episode-preview {
    font-size: var(--font-size-sm);
    color: var(--color-text);
    line-height: 1.4;
  }

  .more-items {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-align: center;
    padding: var(--space-sm);
  }

  .loading,
  .error,
  .empty {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-lg);
    color: var(--color-text-secondary);
  }

  .error {
    color: var(--color-error);
  }
</style>
