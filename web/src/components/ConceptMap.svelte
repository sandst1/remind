<script lang="ts">
  import { onMount } from 'svelte';
  import * as d3 from 'd3';
  import { currentDb, conceptMapLoading, conceptMapError, conceptMapData } from '../lib/stores';
  import { fetchGraph, fetchEpisode } from '../lib/api';
  import type { GraphData, GraphNode, EpisodeType, Episode } from '../lib/types';
  import { ZoomIn, ZoomOut, RotateCcw } from 'lucide-svelte';

  let container: HTMLDivElement;
  let width = 800;
  let height = 600;
  let mounted = false;
  let svg: d3.Selection<SVGSVGElement, unknown, null, undefined> | null = null;
  let zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null;

  // Tooltip state
  let tooltip = { visible: false, x: 0, y: 0, title: '', content: '' };

  // Selected concept for detail panel
  let selectedConcept: GraphNode | null = null;

  // Selected episode for detail panel
  let selectedEpisode: Episode | null = null;
  let episodeLoading = false;

  const episodeColors: Record<EpisodeType, string> = {
    observation: '#3b82f6',  // blue
    decision: '#f97316',     // orange
    question: '#a855f7',     // purple
    meta: '#22c55e',         // green
    preference: '#ec4899',   // pink
  };

  onMount(() => {
    mounted = true;
    loadData();

    // Handle resize
    const resizeObserver = new ResizeObserver(entries => {
      const entry = entries[0];
      if (entry) {
        width = entry.contentRect.width;
        height = entry.contentRect.height;
        if ($conceptMapData) renderVisualization();
      }
    });
    resizeObserver.observe(container);

    return () => resizeObserver.disconnect();
  });

  $: if (mounted && $currentDb) {
    loadData();
  }

  async function loadData() {
    if (!$currentDb) return;

    conceptMapLoading.set(true);
    conceptMapError.set(null);

    try {
      const data = await fetchGraph();
      conceptMapData.set(data);
      renderVisualization();
    } catch (e) {
      conceptMapError.set(e instanceof Error ? e.message : 'Failed to load data');
    } finally {
      conceptMapLoading.set(false);
    }
  }

  interface HierarchyNode {
    name: string;
    id?: string;
    title?: string;
    summary?: string;
    confidence?: number;
    instance_count?: number;
    type?: EpisodeType;
    content?: string;
    nodeType: 'root' | 'concept' | 'episode';
    children?: HierarchyNode[];
  }

  function transformToHierarchy(data: GraphData): HierarchyNode {
    return {
      name: 'Memory',
      nodeType: 'root',
      children: data.nodes.map(node => ({
        id: node.id,
        name: node.title || node.summary.substring(0, 40),
        title: node.title,
        summary: node.summary,
        confidence: node.confidence,
        instance_count: node.instance_count,
        nodeType: 'concept' as const,
        children: (node.source_episodes || []).map(ep => ({
          id: ep.id,
          name: ep.title || ep.content.substring(0, 30),
          title: ep.title,
          type: ep.type,
          content: ep.content,
          nodeType: 'episode' as const,
        })),
      })),
    };
  }

  function renderVisualization() {
    if (!$conceptMapData || !container || width === 0 || height === 0) return;

    // Clear previous
    d3.select(container).selectAll('svg').remove();

    const hierarchy = transformToHierarchy($conceptMapData);

    // If no concepts, show empty state
    if (!hierarchy.children || hierarchy.children.length === 0) {
      return;
    }

    // Create hierarchy
    const root = d3.hierarchy(hierarchy);

    // Sort children
    root.sort((a, b) => d3.ascending(a.data.name, b.data.name));

    // Calculate tree dimensions based on node count
    const nodeCount = root.descendants().length;
    const dx = 20; // Vertical spacing between nodes
    const dy = 180; // Horizontal spacing between levels

    // Create tree layout
    const treeLayout = d3.tree<HierarchyNode>().nodeSize([dx, dy]);
    treeLayout(root);

    // Compute the extent of the tree
    let x0 = Infinity;
    let x1 = -Infinity;
    root.each(d => {
      if (d.x > x1) x1 = d.x;
      if (d.x < x0) x0 = d.x;
    });

    const treeHeight = x1 - x0 + dx * 2;
    const treeWidth = (root.height + 1) * dy;

    svg = d3.select(container)
      .append('svg')
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', [-dy / 2, x0 - dx, treeWidth + dy, treeHeight].join(' '))
      .style('font', '10px sans-serif');

    const g = svg.append('g');

    // Add zoom behavior
    zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoomBehavior);

    // Draw links
    g.append('g')
      .attr('fill', 'none')
      .attr('stroke', 'var(--color-border)')
      .attr('stroke-opacity', 0.5)
      .attr('stroke-width', 1.5)
      .selectAll('path')
      .data(root.links())
      .join('path')
      .attr('d', d3.linkHorizontal<d3.HierarchyPointLink<HierarchyNode>, d3.HierarchyPointNode<HierarchyNode>>()
        .x(d => d.y)
        .y(d => d.x) as any);

    // Draw nodes
    const node = g.append('g')
      .selectAll<SVGGElement, d3.HierarchyPointNode<HierarchyNode>>('g')
      .data(root.descendants())
      .join('g')
      .attr('transform', d => `translate(${d.y},${d.x})`);

    // Node circles
    node.append('circle')
      .attr('r', d => getNodeRadius(d.data))
      .attr('fill', d => getNodeColor(d.data))
      .attr('stroke', d => d.data.nodeType === 'concept' ? getConceptStrokeColor(d.data) : 'none')
      .attr('stroke-width', 2)
      .style('cursor', d => d.data.nodeType !== 'root' ? 'pointer' : 'default')
      .on('mouseover', handleMouseOver)
      .on('mouseout', handleMouseOut)
      .on('click', handleClick);

    // Node labels
    node.append('text')
      .attr('dy', '0.31em')
      .attr('x', d => d.children ? -getNodeRadius(d.data) - 6 : getNodeRadius(d.data) + 6)
      .attr('text-anchor', d => d.children ? 'end' : 'start')
      .attr('fill', 'var(--color-text)')
      .style('font-size', d => d.data.nodeType === 'concept' ? '11px' : '9px')
      .text(d => truncateText(d.data.name, d.data.nodeType === 'episode' ? 25 : 35))
      .style('pointer-events', 'none');
  }

  function getNodeRadius(data: HierarchyNode): number {
    switch (data.nodeType) {
      case 'root': return 8;
      case 'concept': return 6;
      case 'episode': return 4;
      default: return 4;
    }
  }

  function getNodeColor(data: HierarchyNode): string {
    switch (data.nodeType) {
      case 'root': return 'var(--color-primary)';
      case 'concept': return getConceptColor(data);
      case 'episode': return data.type ? episodeColors[data.type] : '#71717a';
      default: return '#71717a';
    }
  }

  function getConceptColor(data: HierarchyNode): string {
    const confidence = data.confidence || 0.5;
    if (confidence >= 0.7) return '#22c55e';  // green
    if (confidence >= 0.4) return '#f59e0b';  // amber
    return '#ef4444';  // red
  }

  function getConceptStrokeColor(data: HierarchyNode): string {
    const confidence = data.confidence || 0.5;
    if (confidence >= 0.7) return '#16a34a';  // darker green
    if (confidence >= 0.4) return '#d97706';  // darker amber
    return '#dc2626';  // darker red
  }

  function truncateText(text: string, maxLength: number): string {
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
  }

  function handleMouseOver(event: MouseEvent, d: d3.HierarchyPointNode<HierarchyNode>) {
    if (d.data.nodeType === 'root') return;

    const data = d.data;
    let title: string;
    let content: string;

    if (data.nodeType === 'concept') {
      title = data.title || 'Concept';
      content = `${data.summary?.substring(0, 150) || ''}...\nConfidence: ${Math.round((data.confidence || 0) * 100)}%\nInstances: ${data.instance_count || 0}`;
    } else {
      title = 'Episode';
      content = `${data.content?.substring(0, 150) || ''}...\nType: ${data.type || 'unknown'}`;
    }

    tooltip = {
      visible: true,
      x: event.pageX + 10,
      y: event.pageY + 10,
      title,
      content,
    };
  }

  function handleMouseOut() {
    tooltip = { ...tooltip, visible: false };
  }

  async function handleClick(event: MouseEvent, d: d3.HierarchyPointNode<HierarchyNode>) {
    if (d.data.nodeType === 'concept') {
      selectedEpisode = null;
      // Find the original GraphNode
      const graphNode = $conceptMapData?.nodes.find(n => n.id === d.data.id);
      if (graphNode) {
        selectedConcept = graphNode;
      }
    } else if (d.data.nodeType === 'episode' && d.data.id) {
      selectedConcept = null;
      episodeLoading = true;
      try {
        selectedEpisode = await fetchEpisode(d.data.id);
      } catch (e) {
        console.error('Failed to fetch episode:', e);
        selectedEpisode = null;
      } finally {
        episodeLoading = false;
      }
    }
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
    selectedConcept = null;
  }

  function closeEpisodeDetail() {
    selectedEpisode = null;
  }

  function formatDate(isoDate: string): string {
    return new Date(isoDate).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }
</script>

<div class="concept-map">
  <div class="header">
    <h2>Concept Map</h2>
    <div class="controls">
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
      {#if $conceptMapLoading}
        <div class="loading">Loading visualization...</div>
      {:else if $conceptMapError}
        <div class="error">{$conceptMapError}</div>
      {:else if !$conceptMapData || $conceptMapData.nodes.length === 0}
        <div class="empty">No concepts to display. Remember some episodes first.</div>
      {/if}
    </div>

    {#if selectedConcept}
      <div class="detail-panel">
        <div class="detail-header">
          <h3>{selectedConcept.title || 'Concept'}</h3>
          <button class="close-btn" onclick={closeDetail}>&times;</button>
        </div>
        <div class="detail-content">
          <p class="summary">{selectedConcept.summary}</p>
          <div class="meta">
            <span class="confidence" style="color: {getConceptColor({ confidence: selectedConcept.confidence, nodeType: 'concept', name: '' })}">
              {Math.round(selectedConcept.confidence * 100)}% confidence
            </span>
            <span class="count">{selectedConcept.instance_count} instances</span>
          </div>
          {#if selectedConcept.conditions && selectedConcept.conditions.length > 0}
            <div class="section">
              <h4>Conditions</h4>
              <ul>
                {#each selectedConcept.conditions as condition}
                  <li>{condition}</li>
                {/each}
              </ul>
            </div>
          {/if}
          {#if selectedConcept.exceptions && selectedConcept.exceptions.length > 0}
            <div class="section">
              <h4>Exceptions</h4>
              <ul>
                {#each selectedConcept.exceptions as exception}
                  <li>{exception}</li>
                {/each}
              </ul>
            </div>
          {/if}
          {#if selectedConcept.tags && selectedConcept.tags.length > 0}
            <div class="tags">
              {#each selectedConcept.tags as tag}
                <span class="tag">{tag}</span>
              {/each}
            </div>
          {/if}
          {#if selectedConcept.source_episodes && selectedConcept.source_episodes.length > 0}
            <div class="section">
              <h4>Source Episodes ({selectedConcept.source_episodes.length})</h4>
              <div class="episodes">
                {#each selectedConcept.source_episodes as ep}
                  <div class="episode">
                    <span class="episode-type" style="background: {episodeColors[ep.type] || '#71717a'}">{ep.type}</span>
                    <span class="episode-content">{ep.title || ep.content}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      </div>
    {/if}

    {#if selectedEpisode || episodeLoading}
      <div class="detail-panel">
        <div class="detail-header">
          <h3>{selectedEpisode?.title || 'Episode'}</h3>
          <button class="close-btn" onclick={closeEpisodeDetail}>&times;</button>
        </div>
        {#if episodeLoading}
          <div class="detail-content">
            <div class="loading-inline">Loading episode...</div>
          </div>
        {:else if selectedEpisode}
          <div class="detail-content">
            <div class="episode-meta">
              <span class="episode-type-badge" style="background: {episodeColors[selectedEpisode.episode_type] || '#71717a'}">{selectedEpisode.episode_type}</span>
              <span class="episode-date">{formatDate(selectedEpisode.timestamp)}</span>
              {#if selectedEpisode.consolidated}
                <span class="episode-status consolidated">Consolidated</span>
              {:else}
                <span class="episode-status pending">Pending</span>
              {/if}
            </div>
            <div class="episode-full-content">{selectedEpisode.content}</div>
            {#if selectedEpisode.entity_ids && selectedEpisode.entity_ids.length > 0}
              <div class="section">
                <h4>Entities ({selectedEpisode.entity_ids.length})</h4>
                <div class="entity-tags">
                  {#each selectedEpisode.entity_ids as entityId}
                    <span class="entity-tag">{entityId}</span>
                  {/each}
                </div>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {:else if !selectedConcept}
      <div class="detail-panel-placeholder"></div>
    {/if}
  </div>

  <!-- Legend -->
  <div class="legend">
    <div class="legend-section">
      <span class="legend-title">Confidence:</span>
      <div class="legend-item">
        <span class="legend-color" style="background: #22c55e"></span>
        <span>High (70%+)</span>
      </div>
      <div class="legend-item">
        <span class="legend-color" style="background: #f59e0b"></span>
        <span>Medium</span>
      </div>
      <div class="legend-item">
        <span class="legend-color" style="background: #ef4444"></span>
        <span>Low</span>
      </div>
    </div>
    <div class="legend-section">
      <span class="legend-title">Episode:</span>
      {#each Object.entries(episodeColors) as [type, color]}
        <div class="legend-item">
          <span class="legend-color small" style="background: {color}"></span>
          <span>{type}</span>
        </div>
      {/each}
    </div>
  </div>

  {#if tooltip.visible}
    <div class="tooltip" style="left: {tooltip.x}px; top: {tooltip.y}px;">
      <div class="tooltip-title">{tooltip.title}</div>
      <div class="tooltip-content">{tooltip.content}</div>
    </div>
  {/if}
</div>

<style>
  .concept-map {
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
    gap: var(--space-xs);
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

  .detail-header h3 {
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--color-text);
    margin: 0;
  }

  .close-btn {
    background: none;
    border: none;
    font-size: 24px;
    color: var(--color-text-secondary);
    cursor: pointer;
    padding: 0;
    line-height: 1;
  }

  .close-btn:hover {
    color: var(--color-text);
  }

  .detail-content {
    padding: var(--space-md);
    overflow-y: auto;
  }

  .summary {
    color: var(--color-text);
    margin-bottom: var(--space-md);
    line-height: 1.6;
  }

  .meta {
    display: flex;
    gap: var(--space-md);
    margin-bottom: var(--space-md);
    font-size: var(--font-size-sm);
  }

  .section {
    margin-bottom: var(--space-md);
  }

  .section h4 {
    font-size: var(--font-size-sm);
    font-weight: 600;
    color: var(--color-text-secondary);
    margin-bottom: var(--space-xs);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .section ul {
    list-style: disc;
    padding-left: var(--space-md);
    color: var(--color-text);
    font-size: var(--font-size-sm);
  }

  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    margin-bottom: var(--space-md);
  }

  .tag {
    padding: var(--space-xs) var(--space-sm);
    background: var(--color-zinc-100);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  :global([data-theme="dark"]) .tag {
    background: var(--color-zinc-800);
  }

  .episodes {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .episode {
    display: flex;
    gap: var(--space-sm);
    padding: var(--space-sm);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
  }

  .episode-type {
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    color: white;
    font-weight: 500;
    text-transform: capitalize;
    flex-shrink: 0;
  }

  .episode-content {
    color: var(--color-text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Episode detail panel styles */
  .episode-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
    align-items: center;
    margin-bottom: var(--space-md);
  }

  .episode-type-badge {
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    color: white;
    font-weight: 500;
    text-transform: capitalize;
    font-size: var(--font-size-xs);
  }

  .episode-date {
    font-size: var(--font-size-sm);
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

  .episode-full-content {
    font-size: var(--font-size-sm);
    color: var(--color-text);
    line-height: 1.6;
    white-space: pre-wrap;
    margin-bottom: var(--space-md);
  }

  .entity-tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
  }

  .entity-tag {
    padding: 2px 6px;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    font-family: var(--font-mono);
  }

  .loading-inline {
    color: var(--color-text-secondary);
    padding: var(--space-md);
  }

  .legend {
    position: absolute;
    bottom: var(--space-md);
    left: var(--space-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-sm) var(--space-md);
    display: flex;
    gap: var(--space-lg);
    font-size: var(--font-size-xs);
  }

  .legend-section {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }

  .legend-title {
    font-weight: 600;
    color: var(--color-text-secondary);
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--color-text-secondary);
  }

  .legend-color {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }

  .legend-color.small {
    width: 8px;
    height: 8px;
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
