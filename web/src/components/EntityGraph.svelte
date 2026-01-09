<script lang="ts">
  import { onMount } from 'svelte';
  import * as d3 from 'd3';
  import { currentDb, entityGraphLoading, entityGraphError, entityGraphData } from '../lib/stores';
  import { fetchEntityGraph, fetchEntity, fetchEntityEpisodes, fetchEntityConcepts, fetchEpisode } from '../lib/api';
  import type { EntityGraphData, EntityGraphNode, EntityGraphLink, EntityType, Entity, Episode, Concept } from '../lib/types';
  import {
    File, Code, Box, Folder, Lightbulb, User, Briefcase, Wrench, HelpCircle, BookOpen,
    ZoomIn, ZoomOut, RotateCcw, Eye, Zap, CircleHelp, Brain, Heart,
    ChevronRight, ChevronDown
  } from 'lucide-svelte';

  let container: HTMLDivElement;
  let width = 800;
  let height = 600;
  let mounted = false;
  let simulation: d3.Simulation<EntityGraphNode, EntityGraphLink> | null = null;
  let svg: d3.Selection<SVGSVGElement, unknown, null, undefined> | null = null;
  let zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null;

  // Filter state
  let filterType: EntityType | '' = '';

  // Tooltip and selection
  let tooltip = { visible: false, x: 0, y: 0, title: '', content: '' };
  let selectedNode: EntityGraphNode | null = null;
  let selectedEntityDetail: Entity | null = null;
  let relatedEpisodes: Episode[] = [];
  let relatedConcepts: Concept[] = [];
  let expandedEpisodes: Record<string, Episode | null> = {};
  let detailLoading = false;

  const entityColors: Record<EntityType, string> = {
    file: '#3b82f6',      // blue
    function: '#8b5cf6',  // violet
    class: '#f59e0b',     // amber
    module: '#6366f1',    // indigo
    concept: '#f97316',   // orange
    subject: '#14b8a6',   // teal
    person: '#22c55e',    // green
    project: '#2563eb',   // primary blue
    tool: '#f43f5e',      // rose
    other: '#71717a',     // zinc
  };

  const entityIcons: Record<EntityType, typeof File> = {
    file: File,
    function: Code,
    class: Box,
    module: Folder,
    concept: Lightbulb,
    subject: BookOpen,
    person: User,
    project: Briefcase,
    tool: Wrench,
    other: HelpCircle,
  };

  onMount(() => {
    mounted = true;
    loadData();

    const resizeObserver = new ResizeObserver(entries => {
      const entry = entries[0];
      if (entry) {
        width = entry.contentRect.width;
        height = entry.contentRect.height;
        if ($entityGraphData) renderGraph();
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      if (simulation) simulation.stop();
    };
  });

  $: if (mounted && $currentDb) {
    loadData();
  }

  async function loadData() {
    if (!$currentDb) return;

    entityGraphLoading.set(true);
    entityGraphError.set(null);
    selectedNode = null;
    selectedEntityDetail = null;

    try {
      const data = await fetchEntityGraph();
      entityGraphData.set(data);
      renderGraph();
    } catch (e) {
      entityGraphError.set(e instanceof Error ? e.message : 'Failed to load data');
    } finally {
      entityGraphLoading.set(false);
    }
  }

  function renderGraph() {
    if (!$entityGraphData || !container || width === 0 || height === 0) return;

    // Clear previous
    d3.select(container).selectAll('svg').remove();
    if (simulation) simulation.stop();

    // Filter data if needed
    let nodes = [...$entityGraphData.nodes];
    let links = [...$entityGraphData.links];

    if (filterType) {
      nodes = nodes.filter(n => n.type === filterType);
      const nodeIds = new Set(nodes.map(n => n.id));
      links = links.filter(l =>
        nodeIds.has(typeof l.source === 'string' ? l.source : l.source.id) &&
        nodeIds.has(typeof l.target === 'string' ? l.target : l.target.id)
      );
    }

    // If no nodes, show empty state
    if (nodes.length === 0) {
      return;
    }

    svg = d3.select(container)
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    // Add arrow marker for directed edges
    svg.append('defs').append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '-0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('orient', 'auto')
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .append('path')
      .attr('d', 'M 0,-5 L 10,0 L 0,5')
      .attr('fill', 'var(--color-text-muted)');

    // Add zoom behavior
    const g = svg.append('g');

    zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoomBehavior);

    // Create force simulation
    simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink<EntityGraphNode, EntityGraphLink>(links)
        .id(d => d.id)
        .distance(120))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(40));

    // Draw links
    const link = g.append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', 'var(--color-border)')
      .attr('stroke-width', d => Math.max(1, d.strength * 3))
      .attr('stroke-opacity', 0.6)
      .attr('marker-end', 'url(#arrowhead)');

    // Draw link labels
    const linkLabel = g.append('g')
      .attr('class', 'link-labels')
      .selectAll('text')
      .data(links)
      .join('text')
      .attr('font-size', '9px')
      .attr('fill', 'var(--color-text-muted)')
      .attr('text-anchor', 'middle')
      .attr('dy', -5)
      .text(d => d.type);

    // Draw nodes
    const node = g.append('g')
      .attr('class', 'nodes')
      .selectAll<SVGGElement, EntityGraphNode>('g')
      .data(nodes)
      .join('g')
      .call(drag(simulation));

    node.append('circle')
      .attr('r', d => Math.min(25, 12 + Math.sqrt(d.mention_count) * 2))
      .attr('fill', d => entityColors[d.type])
      .attr('fill-opacity', 0.85)
      .attr('stroke', 'var(--color-surface)')
      .attr('stroke-width', 2)
      .style('cursor', 'pointer')
      .on('mouseover', handleMouseOver)
      .on('mouseout', handleMouseOut)
      .on('click', handleClick);

    // Node labels
    node.append('text')
      .attr('dy', d => Math.min(25, 12 + Math.sqrt(d.mention_count) * 2) + 14)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('fill', 'var(--color-text-secondary)')
      .text(d => truncate(d.display_name || d.id.split(':')[1] || d.id, 12));

    // Update positions on tick
    simulation.on('tick', () => {
      link
        .attr('x1', d => (d.source as EntityGraphNode).x!)
        .attr('y1', d => (d.source as EntityGraphNode).y!)
        .attr('x2', d => (d.target as EntityGraphNode).x!)
        .attr('y2', d => (d.target as EntityGraphNode).y!);

      linkLabel
        .attr('x', d => ((d.source as EntityGraphNode).x! + (d.target as EntityGraphNode).x!) / 2)
        .attr('y', d => ((d.source as EntityGraphNode).y! + (d.target as EntityGraphNode).y!) / 2);

      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
  }

  function drag(simulation: d3.Simulation<EntityGraphNode, EntityGraphLink>) {
    function dragstarted(event: d3.D3DragEvent<SVGGElement, EntityGraphNode, EntityGraphNode>) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }

    function dragged(event: d3.D3DragEvent<SVGGElement, EntityGraphNode, EntityGraphNode>) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }

    function dragended(event: d3.D3DragEvent<SVGGElement, EntityGraphNode, EntityGraphNode>) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }

    return d3.drag<SVGGElement, EntityGraphNode>()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended);
  }

  function truncate(text: string, maxLength: number): string {
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
  }

  function handleMouseOver(event: MouseEvent, d: EntityGraphNode) {
    tooltip = {
      visible: true,
      x: event.pageX + 10,
      y: event.pageY + 10,
      title: d.display_name || d.id,
      content: `Type: ${d.type}\nMentions: ${d.mention_count}`,
    };
  }

  function handleMouseOut() {
    tooltip = { ...tooltip, visible: false };
  }

  async function handleClick(event: MouseEvent, d: EntityGraphNode) {
    selectedNode = d;
    detailLoading = true;
    relatedEpisodes = [];
    relatedConcepts = [];
    expandedEpisodes = {};

    try {
      const [entityDetail, episodesRes, conceptsRes] = await Promise.all([
        fetchEntity(d.id),
        fetchEntityEpisodes(d.id),
        fetchEntityConcepts(d.id),
      ]);
      selectedEntityDetail = entityDetail;
      relatedEpisodes = episodesRes.episodes;
      relatedConcepts = conceptsRes.concepts;
    } catch (e) {
      console.error('Failed to fetch entity detail:', e);
      selectedEntityDetail = null;
    } finally {
      detailLoading = false;
    }
  }

  function applyFilter() {
    renderGraph();
  }

  function zoomIn() {
    if (svg && zoomBehavior) {
      svg.transition().duration(300).call(zoomBehavior.scaleBy, 1.3);
    }
  }

  function zoomOut() {
    if (svg && zoomBehavior) {
      svg.transition().duration(300).call(zoomBehavior.scaleBy, 0.7);
    }
  }

  function resetZoom() {
    if (svg && zoomBehavior) {
      svg.transition().duration(300).call(zoomBehavior.transform, d3.zoomIdentity);
    }
  }

  function closeDetail() {
    selectedNode = null;
    selectedEntityDetail = null;
    relatedEpisodes = [];
    relatedConcepts = [];
    expandedEpisodes = {};
  }

  // Episode type icons
  const episodeTypeIcons: Record<string, typeof Eye> = {
    observation: Eye,
    decision: Zap,
    question: CircleHelp,
    meta: Brain,
    preference: Heart,
  };

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

  function formatDate(isoDate: string): string {
    return new Date(isoDate).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  function getConfidenceClass(confidence: number): string {
    if (confidence >= 0.7) return 'high';
    if (confidence >= 0.4) return 'medium';
    return 'low';
  }

  function formatConfidence(confidence: number): string {
    return `${Math.round(confidence * 100)}%`;
  }
</script>

<div class="entity-graph">
  <div class="header">
    <h2>Entity Network</h2>
    <div class="controls">
      <select bind:value={filterType} onchange={applyFilter}>
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
      <button class="control-btn" onclick={zoomIn} title="Zoom In">
        <ZoomIn size={18} />
      </button>
      <button class="control-btn" onclick={zoomOut} title="Zoom Out">
        <ZoomOut size={18} />
      </button>
      <button class="control-btn" onclick={resetZoom} title="Reset View">
        <RotateCcw size={18} />
      </button>
    </div>
  </div>

  <div class="content">
    <div class="visualization" bind:this={container}>
      {#if $entityGraphLoading}
        <div class="loading">Loading graph...</div>
      {:else if $entityGraphError}
        <div class="error">{$entityGraphError}</div>
      {:else if !$entityGraphData || $entityGraphData.nodes.length === 0}
        <div class="empty">
          {#if filterType}
            No {filterType} entities with relationships found.
          {:else}
            No entity relationships to display. Extract entities with relationships first.
          {/if}
        </div>
      {/if}
    </div>

    {#if selectedNode}
      <div class="detail-panel">
        <div class="detail-header">
          <div class="entity-title">
            <span class="entity-icon" style="background: {entityColors[selectedNode.type]}">
              <svelte:component this={entityIcons[selectedNode.type]} size={16} />
            </span>
            <h3>{selectedNode.display_name || selectedNode.id}</h3>
          </div>
          <button class="close-btn" onclick={closeDetail}>&times;</button>
        </div>
        <div class="detail-content">
          <div class="meta">
            <span class="type-badge" style="background: {entityColors[selectedNode.type]}">{selectedNode.type}</span>
            <span>{selectedNode.mention_count} mentions</span>
          </div>
          <div class="entity-id">
            <span class="label">ID:</span>
            <code>{selectedNode.id}</code>
          </div>

          {#if detailLoading}
            <div class="loading">Loading details...</div>
          {:else}
            {#if selectedEntityDetail?.relations && selectedEntityDetail.relations.length > 0}
              <div class="section">
                <h4>Related Entities ({selectedEntityDetail.relations.length})</h4>
                <div class="relations">
                  {#each selectedEntityDetail.relations as rel}
                    <div class="relation">
                      <span class="relation-direction">{rel.direction === 'outgoing' ? '→' : '←'}</span>
                      <span class="relation-type">{rel.relation_type}</span>
                      {#if rel.related_entity}
                        <span class="relation-target">
                          <span class="target-icon" style="background: {entityColors[rel.related_entity.type]}"></span>
                          {rel.related_entity.display_name || rel.related_entity.id}
                        </span>
                      {/if}
                      {#if rel.strength}
                        <span class="relation-strength">{Math.round(rel.strength * 100)}%</span>
                      {/if}
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            {#if relatedConcepts.length > 0}
              <div class="section">
                <h4>Related Concepts ({relatedConcepts.length})</h4>
                <div class="concepts-list">
                  {#each relatedConcepts as concept}
                    <div class="concept-item">
                      {#if concept.title}
                        <div class="concept-title">{concept.title}</div>
                      {/if}
                      <div class="concept-summary">{concept.summary}</div>
                      <span class="confidence {getConfidenceClass(concept.confidence)}">
                        {formatConfidence(concept.confidence)} confidence
                      </span>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            {#if relatedEpisodes.length > 0}
              <div class="section">
                <h4>Mentioning Episodes ({relatedEpisodes.length})</h4>
                <div class="episodes-list">
                  {#each relatedEpisodes.slice(0, 20) as episode}
                    <button
                      class="episode-item expandable"
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
                        {@const expanded = expandedEpisodes[episode.id]}
                        <div class="episode-full-content">{expanded?.content}</div>
                        {#if expanded?.entity_ids && expanded.entity_ids.length > 0}
                          <div class="episode-entities">
                            {#each expanded.entity_ids as entityId}
                              <span class="entity-tag">{entityId}</span>
                            {/each}
                          </div>
                        {/if}
                      {:else}
                        <div class="episode-preview">{episode.content.slice(0, 150)}{episode.content.length > 150 ? '...' : ''}</div>
                      {/if}
                    </button>
                  {/each}
                  {#if relatedEpisodes.length > 20}
                    <div class="more-items">+{relatedEpisodes.length - 20} more episodes</div>
                  {/if}
                </div>
              </div>
            {/if}
          {/if}
        </div>
      </div>
    {:else}
      <div class="detail-panel-placeholder"></div>
    {/if}
  </div>

  <!-- Legend -->
  <div class="legend">
    {#each Object.entries(entityColors) as [type, color]}
      <div class="legend-item">
        <span class="legend-color" style="background: {color}"></span>
        <span class="legend-label">{type}</span>
      </div>
    {/each}
  </div>

  {#if tooltip.visible}
    <div class="tooltip" style="left: {tooltip.x}px; top: {tooltip.y}px;">
      <div class="tooltip-title">{tooltip.title}</div>
      <div class="tooltip-content">{tooltip.content}</div>
    </div>
  {/if}
</div>

<style>
  .entity-graph {
    display: flex;
    flex-direction: column;
    height: 100%;
    position: relative;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-md);
    flex-shrink: 0;
  }

  .header h2 {
    font-size: var(--font-size-xl);
    font-weight: 600;
    color: var(--color-text);
  }

  .controls {
    display: flex;
    gap: var(--space-sm);
    align-items: center;
  }

  .controls select {
    padding: var(--space-sm) var(--space-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text);
    font-size: var(--font-size-sm);
  }

  .control-btn {
    padding: var(--space-sm);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text-secondary);
    transition: all 0.15s ease;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .control-btn:hover {
    background: var(--color-zinc-100);
    color: var(--color-text);
  }

  :global([data-theme="dark"]) .control-btn:hover {
    background: var(--color-zinc-800);
  }

  .content {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 350px;
    gap: var(--space-md);
    min-height: 0;
  }

  .visualization {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    position: relative;
  }

  .detail-panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  .detail-panel-placeholder {
    /* Empty placeholder to maintain grid layout */
  }

  .detail-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-md);
    border-bottom: 1px solid var(--color-border);
  }

  .entity-title {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    overflow: hidden;
  }

  .entity-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-md);
    color: white;
    flex-shrink: 0;
  }

  .detail-header h3 {
    font-size: var(--font-size-md);
    font-weight: 600;
    color: var(--color-text);
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .close-btn {
    background: none;
    border: none;
    font-size: 24px;
    color: var(--color-text-secondary);
    cursor: pointer;
    padding: 0;
    line-height: 1;
    flex-shrink: 0;
  }

  .close-btn:hover {
    color: var(--color-text);
  }

  .detail-content {
    padding: var(--space-md);
    overflow-y: auto;
  }

  .meta {
    display: flex;
    gap: var(--space-md);
    align-items: center;
    margin-bottom: var(--space-md);
    font-size: var(--font-size-sm);
  }

  .type-badge {
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    color: white;
    font-weight: 500;
    text-transform: capitalize;
    font-size: var(--font-size-xs);
  }

  .entity-id {
    margin-bottom: var(--space-md);
    font-size: var(--font-size-sm);
  }

  .entity-id .label {
    color: var(--color-text-secondary);
    margin-right: var(--space-xs);
  }

  .entity-id code {
    background: var(--color-bg);
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
  }

  .section {
    margin-bottom: var(--space-md);
  }

  .section h4 {
    font-size: var(--font-size-sm);
    font-weight: 600;
    color: var(--color-text-secondary);
    margin-bottom: var(--space-sm);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .relations {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .relation {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
  }

  .relation-direction {
    color: var(--color-text-muted);
    font-weight: bold;
  }

  .relation-type {
    color: var(--color-primary);
    font-weight: 500;
  }

  .relation-target {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--color-text);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .target-icon {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .relation-strength {
    color: var(--color-text-muted);
    font-size: var(--font-size-xs);
  }

  /* Concepts list styles */
  .concepts-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .concept-item {
    padding: var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
  }

  .concept-title {
    font-weight: 600;
    color: var(--color-text);
    font-size: var(--font-size-sm);
    margin-bottom: var(--space-xs);
  }

  .concept-summary {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    margin-bottom: var(--space-xs);
    line-height: 1.4;
  }

  .confidence {
    font-size: var(--font-size-xs);
  }

  .confidence.high {
    color: #22c55e;
  }

  .confidence.medium {
    color: #f59e0b;
  }

  .confidence.low {
    color: #ef4444;
  }

  /* Episodes list styles */
  .episodes-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .episode-item {
    width: 100%;
    padding: var(--space-sm);
    background: var(--color-bg);
    border: none;
    border-radius: var(--radius-sm);
    text-align: left;
    cursor: pointer;
    transition: background-color 0.15s ease;
  }

  .episode-item:hover {
    background: var(--color-zinc-100);
  }

  :global([data-theme="dark"]) .episode-item:hover {
    background: var(--color-zinc-800);
  }

  .episode-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    font-size: var(--font-size-xs);
  }

  .expand-indicator {
    color: var(--color-text-muted);
    display: flex;
    align-items: center;
  }

  .episode-type-icon {
    color: var(--color-text-secondary);
    display: flex;
    align-items: center;
  }

  .episode-date {
    color: var(--color-text-secondary);
  }

  .episode-status {
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    font-weight: 500;
  }

  .episode-status.consolidated {
    background: #22c55e20;
    color: #22c55e;
  }

  .episode-status.pending {
    background: #f59e0b20;
    color: #f59e0b;
  }

  .episode-preview {
    margin-top: var(--space-xs);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    line-height: 1.4;
  }

  .episode-full-content {
    margin-top: var(--space-sm);
    font-size: var(--font-size-sm);
    color: var(--color-text);
    line-height: 1.5;
    white-space: pre-wrap;
  }

  .episode-entities {
    margin-top: var(--space-sm);
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
  }

  .entity-tag {
    padding: 2px 6px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    font-family: var(--font-mono);
  }

  .more-items {
    text-align: center;
    font-size: var(--font-size-xs);
    color: var(--color-text-muted);
    padding: var(--space-sm);
  }

  .detail-content .loading {
    position: static;
    transform: none;
    padding: var(--space-md);
  }

  .legend {
    position: absolute;
    bottom: var(--space-md);
    left: var(--space-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-sm);
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .legend-color {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }

  .legend-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: capitalize;
  }

  .tooltip {
    position: fixed;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-sm) var(--space-md);
    box-shadow: var(--shadow-lg);
    max-width: 300px;
    z-index: 1000;
    pointer-events: none;
  }

  .tooltip-title {
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--space-xs);
  }

  .tooltip-content {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    white-space: pre-wrap;
  }

  .loading, .error, .empty {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: var(--color-text-secondary);
    text-align: center;
  }

  .error {
    color: var(--color-error);
  }
</style>
