<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import * as d3 from 'd3';
  import {
    graphData,
    graphLoading,
    graphError,
    currentDb,
  } from '../lib/stores';
  import { fetchGraph } from '../lib/api';
  import type { GraphNode, GraphLink, RelationType } from '../lib/types';

  let container: HTMLDivElement;
  let svg: SVGSVGElement;
  let mounted = false;

  // State
  let selectedNodeId: string | null = null;
  let searchQuery = '';
  let simulation: d3.Simulation<GraphNode, GraphLink> | null = null;

  const relationColors: Record<RelationType, string> = {
    implies: '#28a745',
    contradicts: '#dc3545',
    specializes: '#0366d6',
    generalizes: '#6f42c1',
    causes: '#fd7e14',
    correlates: '#6c757d',
    part_of: '#795548',
    context_of: '#17a2b8',
  };

  const NODE_WIDTH = 180;
  const NODE_HEIGHT = 56;

  onMount(() => {
    mounted = true;
    loadGraph();
  });

  onDestroy(() => {
    mounted = false;
    if (simulation) {
      simulation.stop();
    }
  });

  // React to database changes
  $: if (mounted && $currentDb) {
    loadGraph();
  }

  async function loadGraph() {
    if (!$currentDb) return;

    graphLoading.set(true);
    graphError.set(null);

    try {
      const data = await fetchGraph();
      graphData.set(data);

      if (data.nodes.length > 0 && mounted) {
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
        if (svg && container) {
          initializeGraph(data);
        }
      }
    } catch (e) {
      graphError.set(e instanceof Error ? e.message : 'Failed to load graph');
    } finally {
      graphLoading.set(false);
    }
  }

  function initializeGraph(data: { nodes: GraphNode[]; links: GraphLink[] }) {
    const width = container.clientWidth;
    const height = container.clientHeight;

    // Stop existing simulation
    if (simulation) {
      simulation.stop();
    }

    const svgEl = d3.select(svg)
      .attr('width', width)
      .attr('height', height);

    // Clear existing
    svgEl.selectAll('*').remove();

    // Create main group for zoom/pan
    const g = svgEl.append('g').attr('class', 'graph-container');

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform.toString());
      });

    svgEl.call(zoom);

    // Initial zoom to fit
    const initialScale = Math.min(width, height) / 1000;
    svgEl.call(
      zoom.transform,
      d3.zoomIdentity.translate(width / 2, height / 2).scale(Math.max(0.3, initialScale))
    );

    // Create links group (drawn first, behind nodes)
    const linksGroup = g.append('g').attr('class', 'links');

    // Create nodes group
    const nodesGroup = g.append('g').attr('class', 'nodes');

    // Initialize force simulation
    simulation = d3.forceSimulation<GraphNode>(data.nodes)
      .force('link', d3.forceLink<GraphNode, GraphLink>(data.links)
        .id((d) => d.id)
        .distance(250)
        .strength(0.3))
      .force('charge', d3.forceManyBody()
        .strength(-800)
        .distanceMax(600))
      .force('center', d3.forceCenter(0, 0))
      .force('collision', d3.forceCollide()
        .radius(NODE_WIDTH / 2 + 40)
        .strength(0.8))
      .force('x', d3.forceX(0).strength(0.02))
      .force('y', d3.forceY(0).strength(0.02));

    // Create links
    const links = linksGroup.selectAll('.link')
      .data(data.links)
      .join('path')
      .attr('class', 'link')
      .attr('stroke', (d) => relationColors[d.type as RelationType] || '#999')
      .attr('stroke-width', (d) => 1.5 + d.strength)
      .attr('stroke-opacity', 0.5)
      .attr('fill', 'none');

    // Create link labels
    const linkLabels = linksGroup.selectAll('.link-label')
      .data(data.links)
      .join('text')
      .attr('class', 'link-label')
      .attr('font-size', 9)
      .attr('fill', (d) => relationColors[d.type as RelationType] || '#666')
      .attr('text-anchor', 'middle')
      .attr('dy', -4)
      .attr('opacity', 0.7)
      .text((d) => d.type.replace('_', ' '));

    // Create node groups
    const nodes = nodesGroup.selectAll('.node')
      .data(data.nodes)
      .join('g')
      .attr('class', 'node')
      .call(d3.drag<SVGGElement, GraphNode>()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended)
      );

    // Node background
    nodes.append('rect')
      .attr('class', 'node-bg')
      .attr('width', NODE_WIDTH)
      .attr('height', NODE_HEIGHT)
      .attr('x', -NODE_WIDTH / 2)
      .attr('y', -NODE_HEIGHT / 2)
      .attr('rx', 6)
      .attr('fill', 'white')
      .attr('stroke', (d) => getNodeBorderColor(d))
      .attr('stroke-width', 2)
      .style('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))')
      .style('cursor', 'grab');

    // Node content using foreignObject
    nodes.each(function(d) {
      const node = d3.select(this);

      const fo = node.append('foreignObject')
        .attr('width', NODE_WIDTH - 12)
        .attr('height', NODE_HEIGHT - 8)
        .attr('x', -NODE_WIDTH / 2 + 6)
        .attr('y', -NODE_HEIGHT / 2 + 4);

      const div = fo.append('xhtml:div')
        .style('font-family', '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif')
        .style('font-size', '11px')
        .style('line-height', '1.3')
        .style('height', '100%')
        .style('display', 'flex')
        .style('flex-direction', 'column')
        .style('overflow', 'hidden')
        .style('pointer-events', 'none');

      // Header
      const header = div.append('div')
        .style('display', 'flex')
        .style('justify-content', 'space-between')
        .style('align-items', 'center')
        .style('margin-bottom', '2px');

      header.append('span')
        .style('font-weight', '600')
        .style('font-size', '10px')
        .style('padding', '1px 5px')
        .style('border-radius', '8px')
        .style('background', getConfidenceBackground(d.confidence))
        .style('color', 'white')
        .text(`${Math.round(d.confidence * 100)}%`);

      header.append('span')
        .style('color', '#8b949e')
        .style('font-size', '10px')
        .text(`${d.instance_count}x`);

      // Summary
      div.append('div')
        .style('color', '#24292f')
        .style('flex', '1')
        .style('overflow', 'hidden')
        .style('text-overflow', 'ellipsis')
        .style('display', '-webkit-box')
        .style('-webkit-line-clamp', '2')
        .style('-webkit-box-orient', 'vertical')
        .style('font-size', '10px')
        .text(d.summary);
    });

    // Click handler
    nodes.on('click', (event: MouseEvent, d: GraphNode) => {
      event.stopPropagation();
      selectNode(d.id);
    });

    // Hover effects
    nodes
      .on('mouseenter', function() {
        d3.select(this).select('.node-bg')
          .transition()
          .duration(100)
          .attr('stroke-width', 3)
          .style('filter', 'drop-shadow(0 4px 8px rgba(0,0,0,0.15))');
      })
      .on('mouseleave', function() {
        d3.select(this).select('.node-bg')
          .transition()
          .duration(100)
          .attr('stroke-width', 2)
          .style('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))');
      });

    // Update selection highlight
    function updateSelection() {
      nodes.select('.node-bg')
        .attr('fill', (d: GraphNode) => d.id === selectedNodeId ? '#e8f4fd' : 'white')
        .attr('stroke-width', (d: GraphNode) => d.id === selectedNodeId ? 3 : 2);
    }

    // Simulation tick
    simulation.on('tick', () => {
      links.attr('d', (d: any) => {
        const source = d.source as GraphNode;
        const target = d.target as GraphNode;
        const dx = (target.x || 0) - (source.x || 0);
        const dy = (target.y || 0) - (source.y || 0);
        const dr = Math.sqrt(dx * dx + dy * dy) * 0.8;
        return `M${source.x},${source.y}A${dr},${dr} 0 0,1 ${target.x},${target.y}`;
      });

      linkLabels
        .attr('x', (d: any) => {
          const source = d.source as GraphNode;
          const target = d.target as GraphNode;
          return ((source.x || 0) + (target.x || 0)) / 2;
        })
        .attr('y', (d: any) => {
          const source = d.source as GraphNode;
          const target = d.target as GraphNode;
          return ((source.y || 0) + (target.y || 0)) / 2;
        });

      nodes.attr('transform', (d: GraphNode) => `translate(${d.x},${d.y})`);
    });

    // Click background to deselect
    svgEl.on('click', () => {
      selectedNodeId = null;
    });

    // Drag functions
    function dragstarted(event: d3.D3DragEvent<SVGGElement, GraphNode, GraphNode>) {
      if (!event.active && simulation) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
      d3.select(event.sourceEvent.target.closest('.node')).select('.node-bg').style('cursor', 'grabbing');
    }

    function dragged(event: d3.D3DragEvent<SVGGElement, GraphNode, GraphNode>) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }

    function dragended(event: d3.D3DragEvent<SVGGElement, GraphNode, GraphNode>) {
      if (!event.active && simulation) simulation.alphaTarget(0);
      // Keep node fixed where user dropped it
      // event.subject.fx = null;
      // event.subject.fy = null;
      d3.select(event.sourceEvent.target.closest('.node')).select('.node-bg').style('cursor', 'grab');
    }

    // Double-click to release node
    nodes.on('dblclick', (event: MouseEvent, d: GraphNode) => {
      event.stopPropagation();
      d.fx = null;
      d.fy = null;
      if (simulation) simulation.alpha(0.3).restart();
    });

    // Double-click background to reset view
    svgEl.on('dblclick', () => {
      svgEl.transition().duration(500).call(
        zoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(Math.max(0.3, initialScale))
      );
    });
  }

  function getNodeBorderColor(node: GraphNode): string {
    if (node.relations.length === 0) return '#d0d7de';

    const typeCounts = new Map<string, number>();
    node.relations.forEach((r) => {
      typeCounts.set(r.type, (typeCounts.get(r.type) || 0) + 1);
    });

    let maxType = node.relations[0].type;
    let maxCount = 0;
    typeCounts.forEach((count, type) => {
      if (count > maxCount) {
        maxCount = count;
        maxType = type;
      }
    });

    return relationColors[maxType as RelationType] || '#d0d7de';
  }

  function getConfidenceBackground(confidence: number): string {
    if (confidence >= 0.7) return '#1a7f37';
    if (confidence >= 0.4) return '#bf8700';
    return '#cf222e';
  }

  function selectNode(nodeId: string) {
    selectedNodeId = selectedNodeId === nodeId ? null : nodeId;
  }

  function handleSearch() {
    if (!$graphData || !searchQuery.trim()) return;

    const query = searchQuery.toLowerCase();
    const found = $graphData.nodes.find(n =>
      n.summary.toLowerCase().includes(query)
    );

    if (found) {
      selectedNodeId = found.id;
      // TODO: could pan to the node here
    }
  }

  function resetSimulation() {
    if (!$graphData) return;

    // Unfix all nodes
    for (const node of $graphData.nodes) {
      node.fx = null;
      node.fy = null;
    }

    if (simulation) {
      simulation.alpha(1).restart();
    }
  }

  // Get selected node for details panel
  $: selectedNode = selectedNodeId && $graphData
    ? $graphData.nodes.find(n => n.id === selectedNodeId)
    : null;
</script>

<div class="graph-visualization">
  <div class="header">
    <h2>Concept Graph</h2>
    <div class="controls">
      <div class="search-box">
        <input
          type="text"
          placeholder="Search concepts..."
          bind:value={searchQuery}
          on:keydown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button class="btn" on:click={handleSearch}>Search</button>
      </div>
      <button class="btn" on:click={resetSimulation}>Reset Layout</button>
    </div>
  </div>

  <div class="legend">
    {#each Object.entries(relationColors) as [type, color]}
      <div class="legend-item">
        <span class="legend-color" style="background: {color}"></span>
        <span class="legend-label">{type.replace('_', ' ')}</span>
      </div>
    {/each}
  </div>

  <div class="main-content">
    <div class="graph-container" bind:this={container}>
      {#if $graphLoading}
        <div class="message">Loading graph...</div>
      {:else if $graphError}
        <div class="message error">{$graphError}</div>
      {:else if !$graphData || $graphData.nodes.length === 0}
        <div class="message">No concepts to display</div>
      {:else}
        <svg bind:this={svg}></svg>
        <div class="hint">
          Drag nodes to move. Double-click node to release. Double-click background to reset view. Scroll to zoom.
        </div>
        <div class="node-count">{$graphData.nodes.length} concepts</div>
      {/if}
    </div>

    {#if selectedNode}
      <div class="details-panel">
        <div class="details-header">
          <h3>Selected Concept</h3>
          <button class="close-btn" on:click={() => selectedNodeId = null}>×</button>
        </div>

        <div class="details-content">
          <div class="detail-row">
            <span class="confidence-badge" style="background: {getConfidenceBackground(selectedNode.confidence)}">
              {Math.round(selectedNode.confidence * 100)}% confidence
            </span>
            <span class="instance-count">{selectedNode.instance_count} instances</span>
          </div>

          <p class="summary">{selectedNode.summary}</p>

          {#if selectedNode.conditions && selectedNode.conditions.length > 0}
            <div class="detail-section">
              <h4>Conditions</h4>
              <ul>
                {#each selectedNode.conditions as condition}
                  <li>{condition}</li>
                {/each}
              </ul>
            </div>
          {/if}

          {#if selectedNode.tags && selectedNode.tags.length > 0}
            <div class="detail-section">
              <h4>Tags</h4>
              <div class="tags">
                {#each selectedNode.tags as tag}
                  <span class="tag">{tag}</span>
                {/each}
              </div>
            </div>
          {/if}

          {#if selectedNode.relations && selectedNode.relations.length > 0}
            <div class="detail-section">
              <h4>Relations ({selectedNode.relations.length})</h4>
              <div class="relations-list">
                {#each selectedNode.relations as rel}
                  <div class="relation-item">
                    <span class="relation-type" style="color: {relationColors[rel.type]}">{rel.type.replace('_', ' ')}</span>
                    <span class="relation-arrow">→</span>
                    <span class="relation-target">{rel.target_summary || rel.target_id}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          {#if selectedNode.source_episodes && selectedNode.source_episodes.length > 0}
            <div class="detail-section">
              <h4>Source Episodes ({selectedNode.source_episodes.length})</h4>
              <div class="episodes-list">
                {#each selectedNode.source_episodes.slice(0, 3) as ep}
                  <div class="episode-item">
                    <span class="episode-type">{ep.type}</span>
                    <span class="episode-content">{ep.content}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .graph-visualization {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 80px);
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-sm);
    flex-wrap: wrap;
    gap: var(--space-sm);
  }

  h2 {
    font-size: var(--font-size-xl);
    margin: 0;
  }

  .controls {
    display: flex;
    gap: var(--space-xs);
    align-items: center;
    flex-wrap: wrap;
  }

  .search-box {
    display: flex;
    gap: 4px;
  }

  .search-box input {
    padding: 5px 10px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    font-size: var(--font-size-sm);
    width: 180px;
  }

  .btn {
    padding: 5px 10px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--font-size-sm);
    cursor: pointer;
    transition: background 0.15s;
  }

  .btn:hover {
    background: #f3f4f6;
  }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
    margin-bottom: var(--space-sm);
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
  }

  .legend-color {
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }

  .legend-label {
    color: var(--color-text-secondary);
    text-transform: capitalize;
  }

  .main-content {
    flex: 1;
    display: flex;
    gap: var(--space-md);
    min-height: 0;
  }

  .graph-container {
    flex: 1;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    position: relative;
    overflow: hidden;
  }

  .graph-container svg {
    width: 100%;
    height: 100%;
  }

  .hint {
    position: absolute;
    bottom: var(--space-sm);
    left: 50%;
    transform: translateX(-50%);
    padding: 4px 12px;
    background: rgba(255, 255, 255, 0.95);
    border-radius: var(--radius-md);
    font-size: 11px;
    color: var(--color-text-muted);
    box-shadow: var(--shadow-sm);
  }

  .node-count {
    position: absolute;
    top: var(--space-sm);
    left: var(--space-sm);
    padding: 4px 10px;
    background: rgba(255, 255, 255, 0.9);
    border-radius: var(--radius-md);
    font-size: 12px;
    color: var(--color-text-secondary);
    font-weight: 500;
  }

  .message {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-text-secondary);
  }

  .message.error {
    color: var(--color-contradicts);
  }

  /* Details Panel */
  .details-panel {
    width: 320px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    flex-shrink: 0;
  }

  .details-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--color-border);
    background: #f6f8fa;
  }

  .details-header h3 {
    margin: 0;
    font-size: var(--font-size-sm);
    font-weight: 600;
  }

  .close-btn {
    background: none;
    border: none;
    font-size: 20px;
    cursor: pointer;
    color: var(--color-text-secondary);
    padding: 0;
    line-height: 1;
  }

  .details-content {
    padding: var(--space-md);
    overflow-y: auto;
    flex: 1;
  }

  .detail-row {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-sm);
  }

  .confidence-badge {
    padding: 2px 8px;
    border-radius: 12px;
    color: white;
    font-size: 11px;
    font-weight: 600;
  }

  .instance-count {
    color: var(--color-text-secondary);
    font-size: 12px;
  }

  .summary {
    font-size: var(--font-size-sm);
    line-height: 1.5;
    color: var(--color-text);
    margin: 0 0 var(--space-md);
  }

  .detail-section {
    margin-bottom: var(--space-md);
  }

  .detail-section h4 {
    font-size: 11px;
    font-weight: 600;
    color: var(--color-text-secondary);
    text-transform: uppercase;
    margin: 0 0 var(--space-xs);
  }

  .detail-section ul {
    margin: 0;
    padding-left: var(--space-md);
    font-size: var(--font-size-sm);
  }

  .detail-section li {
    margin-bottom: 4px;
  }

  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .tag {
    padding: 2px 8px;
    background: #e8f4fd;
    border-radius: 12px;
    font-size: 11px;
    color: #0366d6;
  }

  .relations-list,
  .episodes-list {
    max-height: 200px;
    overflow-y: auto;
  }

  .relation-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    padding: 4px 0;
    border-bottom: 1px solid #f0f0f0;
  }

  .relation-type {
    font-weight: 600;
    text-transform: uppercase;
    font-size: 10px;
    flex-shrink: 0;
  }

  .relation-arrow {
    color: #8b949e;
  }

  .relation-target {
    flex: 1;
    color: var(--color-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .episode-item {
    padding: 6px;
    margin-bottom: 4px;
    background: #f6f8fa;
    border-radius: 4px;
    font-size: 11px;
  }

  .episode-type {
    display: inline-block;
    padding: 1px 6px;
    background: #e1e4e8;
    border-radius: 8px;
    font-size: 10px;
    margin-right: 6px;
    text-transform: uppercase;
  }

  .episode-content {
    color: var(--color-text-secondary);
  }

  :global(.node) {
    cursor: grab;
  }

  :global(.node:active) {
    cursor: grabbing;
  }
</style>
