<script lang="ts">
  import { onMount } from 'svelte';
  import {
    entities,
    entitiesTotal,
    entitiesLoading,
    entitiesError,
    currentDb,
  } from '../lib/stores';
  import { fetchEntities, fetchEntity, fetchEntityEpisodes, fetchEntityConcepts, fetchEpisode, fetchConcept } from '../lib/api';
  import type { Entity, Episode, Concept, EntityType, EntityRelation } from '../lib/types';

  let filterType: EntityType | '' = '';
  let mounted = false;

  // Selected entity detail
  let selectedEntity: Entity | null = null;
  let relatedEpisodes: Episode[] = [];
  let relatedConcepts: Concept[] = [];
  let detailLoading = false;

  // Expandable episodes state
  let expandedEpisodes: Record<string, Episode | null> = {};

  // Concept side panel state
  let selectedConcept: Concept | null = null;
  let conceptLoading = false;

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
    detailLoading = true;
    relatedEpisodes = [];
    relatedConcepts = [];

    try {
      // Fetch entity detail with relations, episodes, and concepts in parallel
      const [entityDetail, episodesRes, conceptsRes] = await Promise.all([
        fetchEntity(entity.id),
        fetchEntityEpisodes(entity.id),
        fetchEntityConcepts(entity.id),
      ]);
      selectedEntity = entityDetail;
      relatedEpisodes = episodesRes.episodes;
      relatedConcepts = conceptsRes.concepts;
    } catch (e) {
      console.error('Failed to load entity details:', e);
      selectedEntity = entity; // Fallback to basic entity data
    } finally {
      detailLoading = false;
    }
  }

  // Navigate to a related entity
  async function navigateToRelatedEntity(relatedEntity: Entity) {
    await selectEntity(relatedEntity);
  }

  function applyFilter() {
    loadEntities();
  }

  function clearSelection() {
    selectedEntity = null;
    relatedEpisodes = [];
    relatedConcepts = [];
    expandedEpisodes = {};
    selectedConcept = null;
  }

  // Toggle episode expansion
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

  // Open concept in side panel
  async function openRelatedConcept(conceptId: string) {
    conceptLoading = true;
    try {
      selectedConcept = await fetchConcept(conceptId);
    } catch (e) {
      console.error('Failed to fetch concept:', e);
    } finally {
      conceptLoading = false;
    }
  }

  function closeConceptPanel() {
    selectedConcept = null;
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
            {#if selectedEntity?.relations && selectedEntity.relations.length > 0}
              <div class="detail-section">
                <h4>Related Entities ({selectedEntity.relations.length})</h4>
                <div class="related-list">
                  {#each selectedEntity.relations as relation}
                    {#if relation.related_entity}
                      <button
                        class="related-item entity-relation-item clickable"
                        onclick={() => navigateToRelatedEntity(relation.related_entity)}
                      >
                        <div class="relation-header">
                          <span class="relation-direction">{relation.direction === 'outgoing' ? '→' : '←'}</span>
                          <span class="relation-type">{relation.relation_type}</span>
                          <span class="relation-strength">{Math.round(relation.strength * 100)}%</span>
                        </div>
                        <div class="related-entity-info">
                          <span class="entity-icon">{entityTypeIcons[relation.related_entity.type]}</span>
                          <span class="entity-name">{relation.related_entity.display_name || relation.related_entity.id}</span>
                        </div>
                      </button>
                    {/if}
                  {/each}
                </div>
              </div>
            {/if}

            {#if relatedConcepts.length > 0}
              <div class="detail-section">
                <h4>Related Concepts ({relatedConcepts.length})</h4>
                <div class="related-list">
                  {#each relatedConcepts as concept}
                    <button
                      class="related-item concept-item clickable"
                      onclick={() => openRelatedConcept(concept.id)}
                    >
                      <div class="related-summary">{concept.summary}</div>
                      <div class="concept-footer">
                        <span class="related-meta confidence {getConfidenceClass(concept.confidence)}">
                          {formatConfidence(concept.confidence)} confidence
                        </span>
                        <span class="open-indicator">View →</span>
                      </div>
                    </button>
                  {/each}
                </div>
              </div>
            {/if}

            {#if relatedEpisodes.length > 0}
              <div class="detail-section">
                <h4>Mentioning Episodes ({relatedEpisodes.length})</h4>
                <div class="related-list">
                  {#each relatedEpisodes.slice(0, 20) as episode}
                    <button
                      class="related-item episode-item expandable"
                      class:expanded={expandedEpisodes[episode.id]}
                      onclick={() => toggleEpisodeExpand(episode.id)}
                    >
                      <div class="episode-header">
                        <span class="expand-indicator">{expandedEpisodes[episode.id] ? '▼' : '▶'}</span>
                        <span class="episode-type-icon">{episodeTypeIcons[episode.episode_type] || '📝'}</span>
                        <span class="episode-date">{formatDate(episode.timestamp)}</span>
                        {#if episode.consolidated}
                          <span class="episode-status consolidated">Consolidated</span>
                        {:else}
                          <span class="episode-status pending">Pending</span>
                        {/if}
                      </div>

                      {#if expandedEpisodes[episode.id]}
                        <div class="episode-full-content">{expandedEpisodes[episode.id].content}</div>
                        {#if expandedEpisodes[episode.id].entity_ids && expandedEpisodes[episode.id].entity_ids.length > 0}
                          <div class="episode-entities">
                            {#each expandedEpisodes[episode.id].entity_ids as entityId}
                              <span class="entity-tag">{entityId}</span>
                            {/each}
                          </div>
                        {/if}
                        <div class="episode-footer">
                          <span class="episode-id">ID: {episode.id.slice(0, 8)}</span>
                        </div>
                      {:else}
                        <div class="episode-preview">{episode.content.slice(0, 200)}{episode.content.length > 200 ? '...' : ''}</div>
                      {/if}
                    </button>
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

    {#if selectedConcept}
      <div class="concept-side-panel">
        <div class="side-panel-header">
          <button class="back-btn" onclick={closeConceptPanel}>← Close</button>
          <h3>Concept Detail</h3>
        </div>

        {#if conceptLoading}
          <div class="loading">Loading concept...</div>
        {:else}
          <div class="side-panel-content">
            <div class="concept-summary">{selectedConcept.summary}</div>

            <div class="concept-meta">
              <div class="meta-item">
                <span class="meta-label">Confidence</span>
                <span class="meta-value confidence {getConfidenceClass(selectedConcept.confidence)}">
                  {formatConfidence(selectedConcept.confidence)}
                </span>
              </div>
              <div class="meta-item">
                <span class="meta-label">Instance Count</span>
                <span class="meta-value">{selectedConcept.instance_count}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">Created</span>
                <span class="meta-value">{formatDate(selectedConcept.created_at)}</span>
              </div>
            </div>

            {#if selectedConcept.conditions}
              <div class="concept-section">
                <h4>Conditions</h4>
                <p>{selectedConcept.conditions}</p>
              </div>
            {/if}

            {#if selectedConcept.exceptions && selectedConcept.exceptions.length > 0}
              <div class="concept-section">
                <h4>Exceptions</h4>
                <ul>
                  {#each selectedConcept.exceptions as exception}
                    <li>{exception}</li>
                  {/each}
                </ul>
              </div>
            {/if}

            {#if selectedConcept.tags && selectedConcept.tags.length > 0}
              <div class="concept-section">
                <h4>Tags</h4>
                <div class="tags">
                  {#each selectedConcept.tags as tag}
                    <span class="tag">{tag}</span>
                  {/each}
                </div>
              </div>
            {/if}

            {#if selectedConcept.relations && selectedConcept.relations.length > 0}
              <div class="concept-section">
                <h4>Relations ({selectedConcept.relations.length})</h4>
                <div class="relations-list">
                  {#each selectedConcept.relations as relation}
                    <div class="relation-item relation-{relation.type}">
                      <span class="relation-type">{relation.type}</span>
                      <span class="relation-target">{relation.target_id}</span>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
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

  /* Entity relation item styles */
  .entity-relation-item {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
    cursor: pointer;
    transition: background-color 0.15s ease;
  }

  .entity-relation-item:hover {
    background: var(--color-surface);
  }

  .relation-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    font-size: var(--font-size-sm);
  }

  .relation-direction {
    color: var(--color-text-secondary);
    font-weight: 500;
  }

  .relation-type {
    color: var(--color-primary);
    font-weight: 500;
  }

  .relation-strength {
    margin-left: auto;
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .related-entity-info {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    padding-left: var(--space-md);
  }

  .related-entity-info .entity-icon {
    font-size: var(--font-size-sm);
  }

  .related-entity-info .entity-name {
    font-size: var(--font-size-sm);
    color: var(--color-text);
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

  /* Clickable concept items */
  .concept-item.clickable {
    cursor: pointer;
    transition: all 0.15s ease;
    border: none;
    width: 100%;
    text-align: left;
    font-family: inherit;
  }

  .concept-item.clickable:hover {
    background: var(--color-border);
    border-color: var(--color-primary);
  }

  .concept-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--space-xs);
  }

  .open-indicator {
    font-size: var(--font-size-xs);
    color: var(--color-primary);
    opacity: 0.7;
  }

  .concept-item.clickable:hover .open-indicator {
    opacity: 1;
  }

  /* Expandable episode items */
  .episode-item.expandable {
    cursor: pointer;
    transition: all 0.15s ease;
    border: 1px solid var(--color-border);
    width: 100%;
    text-align: left;
    font-family: inherit;
  }

  .episode-item.expandable:hover {
    background: var(--color-border);
  }

  .episode-item.expanded {
    border-color: var(--color-primary);
    background: var(--color-surface);
  }

  .expand-indicator {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    width: 1em;
    flex-shrink: 0;
  }

  .episode-full-content {
    white-space: pre-wrap;
    line-height: 1.6;
    font-size: var(--font-size-sm);
    color: var(--color-text);
    padding: var(--space-sm) 0;
    border-top: 1px solid var(--color-border);
    margin-top: var(--space-sm);
  }

  .episode-entities {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    padding-top: var(--space-sm);
  }

  .entity-tag {
    display: inline-block;
    padding: 2px 8px;
    background: var(--color-primary-bg, #e3f2fd);
    color: var(--color-primary);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    font-family: var(--font-mono);
  }

  .episode-footer {
    display: flex;
    justify-content: flex-end;
    padding-top: var(--space-xs);
    border-top: 1px solid var(--color-border);
    margin-top: var(--space-sm);
  }

  .episode-id {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    font-family: var(--font-mono);
  }

  /* Concept side panel */
  .concept-side-panel {
    width: 400px;
    flex-shrink: 0;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    overflow-y: auto;
  }

  .side-panel-header {
    display: flex;
    align-items: center;
    gap: var(--space-md);
    padding: var(--space-md);
    border-bottom: 1px solid var(--color-border);
    position: sticky;
    top: 0;
    background: var(--color-surface);
  }

  .side-panel-header h3 {
    margin: 0;
    font-size: var(--font-size-base);
    color: var(--color-text);
  }

  .back-btn {
    background: none;
    border: 1px solid var(--color-border);
    padding: var(--space-xs) var(--space-sm);
    border-radius: var(--radius-md);
    cursor: pointer;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    transition: all 0.15s ease;
  }

  .back-btn:hover {
    background: var(--color-bg);
    color: var(--color-text);
  }

  .side-panel-content {
    padding: var(--space-md);
  }

  .concept-summary {
    font-size: var(--font-size-base);
    line-height: 1.6;
    color: var(--color-text);
    margin-bottom: var(--space-md);
  }

  .concept-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-md);
    padding: var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-md);
  }

  .concept-section {
    margin-bottom: var(--space-md);
  }

  .concept-section h4 {
    margin: 0 0 var(--space-xs) 0;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .concept-section p {
    margin: 0;
    font-size: var(--font-size-sm);
    color: var(--color-text);
  }

  .concept-section ul {
    margin: 0;
    padding-left: var(--space-md);
    font-size: var(--font-size-sm);
    color: var(--color-text);
  }

  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
  }

  .tag {
    padding: 2px 8px;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
  }

  .relations-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .relation-item {
    display: flex;
    gap: var(--space-sm);
    padding: var(--space-xs) var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    border-left: 3px solid var(--color-border);
    font-size: var(--font-size-sm);
  }

  .relation-type {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    text-transform: uppercase;
  }

  .relation-target {
    color: var(--color-text);
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
  }

  .relation-implies { border-color: var(--color-success, #28a745); }
  .relation-contradicts { border-color: var(--color-error, #dc3545); }
  .relation-specializes { border-color: var(--color-primary); }
  .relation-generalizes { border-color: var(--color-warning, #ffc107); }
</style>
