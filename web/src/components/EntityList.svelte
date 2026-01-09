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
  import {
    File,
    Code,
    Box,
    Folder,
    Lightbulb,
    User,
    Briefcase,
    Wrench,
    Tag,
    BookOpen,
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

  let filterType: EntityType | '' = '';
  let search = '';
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

  // Client-side filtering and sorting of entities
  $: filteredEntities = $entities
    .filter(e => {
      // Filter by type
      if (filterType && e.type !== filterType) return false;
      // Filter by search
      if (search.length >= 2) {
        const searchLower = search.toLowerCase();
        return e.id.toLowerCase().includes(searchLower) ||
               (e.display_name && e.display_name.toLowerCase().includes(searchLower));
      }
      return true;
    })
    .sort((a, b) => (a.display_name || a.id).localeCompare(b.display_name || b.id));

  async function loadEntities() {
    if (!$currentDb) return;

    entitiesLoading.set(true);
    entitiesError.set(null);

    try {
      const response = await fetchEntities();
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
    subject: 'Subject',
    person: 'Person',
    project: 'Project',
    tool: 'Tool',
    other: 'Other',
  };

  const entityTypeIcons: Record<EntityType, any> = {
    file: File,
    function: Code,
    class: Box,
    module: Folder,
    concept: Lightbulb,
    subject: BookOpen,
    person: User,
    project: Briefcase,
    tool: Wrench,
    other: Tag,
  };

  const episodeTypeIcons: Record<string, any> = {
    observation: Eye,
    decision: Zap,
    question: CircleHelp,
    meta: Brain,
    preference: Heart,
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

  function getEntityName(entity: Entity): string {
    if (entity.display_name) return entity.display_name;
    // Extract name part after the colon (e.g., "ai-architecture" from "concept:ai-architecture")
    const colonIndex = entity.id.indexOf(':');
    return colonIndex >= 0 ? entity.id.slice(colonIndex + 1) : entity.id;
  }
</script>

<div class="entity-list">
  <div class="header">
    <h2>Entities</h2>
    <div class="filters">
      <div class="search-bar">
        <Search size={14} class="search-icon" />
        <input
          type="text"
          placeholder="Search entities..."
          bind:value={search}
          class="search-input"
        />
      </div>
      <select bind:value={filterType}>
        <option value="">All types</option>
        <option value="file">Files</option>
        <option value="function">Functions</option>
        <option value="class">Classes</option>
        <option value="module">Modules</option>
        <option value="concept">Concepts</option>
        <option value="subject">Subjects</option>
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
      {:else if filteredEntities.length === 0}
        <div class="empty">No entities found</div>
      {:else}
        <div class="entity-items">
          {#each filteredEntities as entity}
            <button
              class="entity-item"
              class:selected={selectedEntity?.id === entity.id}
              onclick={() => selectEntity(entity)}
            >
              <span class="entity-icon icon-{entity.type}">
                <svelte:component this={entityTypeIcons[entity.type]} size={16} />
              </span>
              <div class="entity-info">
                <div class="entity-name">{getEntityName(entity)}</div>
                <div class="entity-type">{entityTypeLabels[entity.type]}</div>
              </div>
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
              <span class="entity-type-icon icon-{selectedEntity.type}">
                <svelte:component this={entityTypeIcons[selectedEntity.type]} size={24} />
              </span>
              {selectedEntity.display_name || selectedEntity.id}
            </h3>
            <button class="close-btn" onclick={clearSelection}>
              <X size={20} />
            </button>
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
                          <span class="relation-direction">
                            {#if relation.direction === 'outgoing'}
                              <ArrowRight size={14} />
                            {:else}
                              <ArrowRight size={14} style="transform: rotate(180deg)" />
                            {/if}
                          </span>
                          <span class="relation-type">{relation.relation_type}</span>
                          <span class="relation-strength">{Math.round(relation.strength * 100)}%</span>
                        </div>
                        <div class="related-entity-info">
                          <span class="entity-icon icon-{relation.related_entity.type}">
                            <svelte:component this={entityTypeIcons[relation.related_entity.type]} size={14} />
                          </span>
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
                      {#if concept.title}
                        <div class="related-title">{concept.title}</div>
                      {/if}
                      <div class="related-summary">{concept.summary}</div>
                      <div class="concept-footer">
                        <span class="related-meta confidence {getConfidenceClass(concept.confidence)}">
                          {formatConfidence(concept.confidence)} confidence
                        </span>
                        <span class="open-indicator">
                          View <ArrowRight size={12} style="display: inline-block; vertical-align: middle;" />
                        </span>
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
                        <span class="expand-indicator">
                          {#if expandedEpisodes[episode.id]}
                            <ChevronDown size={14} />
                          {:else}
                            <ChevronRight size={14} />
                          {/if}
                        </span>
                        <span class="episode-type-icon">
                          <svelte:component this={episodeTypeIcons[episode.episode_type]} size={14} />
                        </span>
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
          <button class="back-btn" onclick={closeConceptPanel}>
            <ArrowRight size={16} style="transform: rotate(180deg)" /> Close
          </button>
          <h3>{selectedConcept.title || 'Concept Detail'}</h3>
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
    font-size: var(--font-size-2xl);
    font-weight: 700;
  }

  .filters {
    display: flex;
    gap: var(--space-sm);
  }

  .search-bar {
    position: relative;
    display: flex;
    align-items: center;
  }

  .search-input {
    padding: var(--space-xs) var(--space-sm) var(--space-xs) 36px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--font-size-sm);
    width: 200px;
    transition: all 0.15s ease;
  }
  
  .search-input:focus {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px var(--color-primary-bg);
  }

  .filters select {
    padding: var(--space-xs) var(--space-sm);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--font-size-sm);
    cursor: pointer;
  }
  
  .filters select:hover {
    border-color: var(--color-zinc-400);
  }

  .content {
    display: flex;
    gap: var(--space-md);
    flex: 1;
    min-height: 0;
  }

  .list-panel {
    width: 350px;
    flex-shrink: 0;
    overflow-y: auto;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    display: flex;
    flex-direction: column;
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
    background: var(--color-surface-hover);
  }

  .entity-item.selected {
    background: var(--color-primary-bg);
    border-left: 3px solid var(--color-primary);
    padding-left: calc(var(--space-md) - 3px);
  }

  .entity-item.selected .entity-name {
    color: var(--color-primary);
    font-weight: 500;
  }

  .entity-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--color-text-secondary);
    flex-shrink: 0;
  }
  
  .entity-item.selected .entity-icon {
    color: var(--color-primary);
  }

  /* Entity Type Colors */
  .icon-file { color: var(--color-blue); }
  .icon-function { color: var(--color-violet); }
  .icon-class { color: var(--color-amber); }
  .icon-module { color: var(--color-indigo); }
  .icon-concept { color: var(--color-orange); }
  .icon-subject { color: var(--color-teal); }
  .icon-person { color: var(--color-green); }
  .icon-project { color: var(--color-primary); }
  .icon-tool { color: var(--color-rose); }
  .icon-other { color: var(--color-text-secondary); }

  .entity-info {
    flex: 1;
    min-width: 0;
    overflow: hidden;
  }

  .entity-name {
    font-size: var(--font-size-sm);
    color: var(--color-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .entity-type {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
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
    padding: var(--space-lg);
  }

  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: var(--space-lg);
  }

  .panel-header h3 {
    margin: 0;
    font-size: var(--font-size-xl);
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    font-weight: 600;
  }

  .entity-type-icon {
    color: var(--color-text-secondary);
    display: flex;
    align-items: center;
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--color-text-secondary);
    cursor: pointer;
    padding: var(--space-xs);
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .close-btn:hover {
    background: var(--color-surface-hover);
    color: var(--color-text);
  }

  .detail-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-lg);
    margin-bottom: var(--space-xl);
    padding: var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
  }

  .meta-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .meta-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.05em;
  }

  .meta-value {
    font-size: var(--font-size-base);
    color: var(--color-text);
    font-weight: 500;
  }

  .meta-value.mono {
    font-family: var(--font-mono);
  }

  .detail-section {
    margin-bottom: var(--space-xl);
  }

  .detail-section h4 {
    margin: 0 0 var(--space-sm) 0;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.05em;
  }

  .related-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .related-item {
    padding: var(--space-md);
    background: var(--color-surface);
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
    transition: all 0.15s ease;
  }

  .concept-item .related-title {
    font-weight: 600;
    font-size: var(--font-size-base);
    color: var(--color-text);
    margin-bottom: var(--space-xs);
  }

  .concept-item .related-summary {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    margin-bottom: var(--space-sm);
    line-height: 1.5;
  }

  .related-meta {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    font-weight: 500;
  }

  .confidence.high { color: var(--color-success); }
  .confidence.medium { color: var(--color-warning); }
  .confidence.low { color: var(--color-error); }

  /* Entity relation item styles */
  .entity-relation-item {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
    cursor: pointer;
  }

  .entity-relation-item:hover {
    border-color: var(--color-primary);
    box-shadow: var(--shadow-sm);
  }

  .relation-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    font-size: var(--font-size-sm);
  }

  .relation-direction {
    color: var(--color-text-muted);
    display: flex;
    align-items: center;
  }

  .relation-type {
    color: var(--color-primary);
    font-weight: 600;
    background: var(--color-primary-bg);
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
  }

  .relation-strength {
    margin-left: auto;
    font-size: var(--font-size-xs);
    color: var(--color-text-muted);
  }

  .related-entity-info {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding-left: var(--space-sm);
  }

  .related-entity-info .entity-name {
    font-size: var(--font-size-sm);
    color: var(--color-text);
    font-weight: 500;
  }

  .episode-item .episode-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-xs);
  }

  .episode-type-icon {
    color: var(--color-text-secondary);
    display: flex;
    align-items: center;
  }

  .episode-date {
    font-size: var(--font-size-xs);
    color: var(--color-text-muted);
    font-family: var(--font-mono);
  }

  .episode-status {
    font-size: var(--font-size-xs);
    padding: 2px 8px;
    border-radius: var(--radius-full);
    font-weight: 500;
  }

  .episode-status.consolidated {
    background: var(--color-success-bg);
    color: var(--color-success);
  }

  .episode-status.pending {
    background: var(--color-warning-bg);
    color: var(--color-warning);
  }

  .episode-preview {
    font-size: var(--font-size-sm);
    color: var(--color-text);
    line-height: 1.5;
    padding-left: 24px; /* Align with text after chevron */
  }

  .more-items {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-align: center;
    padding: var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-md);
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
    border: 1px solid var(--color-border);
    width: 100%;
    text-align: left;
    font-family: inherit;
  }

  .concept-item.clickable:hover {
    border-color: var(--color-primary);
    box-shadow: var(--shadow-sm);
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
    opacity: 0;
    transition: opacity 0.15s ease;
    display: flex;
    align-items: center;
    gap: 4px;
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
    background: var(--color-surface-hover);
  }

  .episode-item.expanded {
    border-color: var(--color-primary);
    background: var(--color-surface);
    box-shadow: var(--shadow-sm);
  }

  .expand-indicator {
    color: var(--color-text-secondary);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
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
    background: var(--color-bg);
    color: var(--color-text-secondary);
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
    color: var(--color-text-muted);
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
    display: flex;
    flex-direction: column;
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
    z-index: 10;
  }

  .side-panel-header h3 {
    margin: 0;
    font-size: var(--font-size-base);
    color: var(--color-text);
    font-weight: 600;
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
    display: flex;
    align-items: center;
    gap: var(--space-xs);
  }

  .back-btn:hover {
    background: var(--color-surface-hover);
    color: var(--color-text);
    border-color: var(--color-zinc-300);
  }

  .side-panel-content {
    padding: var(--space-lg);
  }

  .concept-summary {
    font-size: var(--font-size-base);
    line-height: 1.6;
    color: var(--color-text);
    margin-bottom: var(--space-lg);
  }

  .concept-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-md);
    padding: var(--space-md);
    background: var(--color-bg);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-lg);
    border: 1px solid var(--color-border);
  }

  .concept-section {
    margin-bottom: var(--space-lg);
  }

  .concept-section h4 {
    margin: 0 0 var(--space-xs) 0;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    font-weight: 600;
  }

  .concept-section p {
    margin: 0;
    font-size: var(--font-size-sm);
    color: var(--color-text);
    line-height: 1.5;
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
    background: var(--color-surface);
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
    align-items: center;
  }

  .relation-type {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    font-weight: 600;
  }

  .relation-target {
    color: var(--color-text);
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
  }

  .relation-implies { border-color: var(--color-success); }
  .relation-contradicts { border-color: var(--color-error); }
  .relation-specializes { border-color: var(--color-primary); }
  .relation-generalizes { border-color: var(--color-warning); }
</style>
