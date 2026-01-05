<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import * as d3 from 'd3';
  import {
    graphData,
    graphLoading,
    graphError,
    expandedNodeIds,
    currentDb,
  } from '../lib/stores';
  import { fetchGraph } from '../lib/api';
  import type { GraphNode, GraphLink, RelationType } from '../lib/types';

  let container: HTMLDivElement;
  let svg: SVGSVGElement;
  let simulation: d3.Simulation<GraphNode, GraphLink> | null = null;
  let transform = d3.zoomIdentity;
  let mounted = false;

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

  const nodeWidth = 200;
  const nodeHeightCollapsed = 60;
  const nodeHeightExpanded = 280;

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
        // Wait for DOM to update with SVG element before initializing
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

    // Clear existing
    d3.select(svg).selectAll('*').remove();

    const svgEl = d3.select(svg)
      .attr('width', width)
      .attr('height', height);

    // Create defs for arrow markers
    const defs = svgEl.append('defs');

    Object.entries(relationColors).forEach(([type, color]) => {
      defs.append('marker')
        .attr('id', `arrow-${type}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 15)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('fill', color)
        .attr('d', 'M0,-5L10,0L0,5');
    });

    // Create main group for zoom/pan
    const g = svgEl.append('g').attr('class', 'graph-container');

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        transform = event.transform;
        g.attr('transform', event.transform.toString());
      });

    svgEl.call(zoom);

    // Create links group
    const linksGroup = g.append('g').attr('class', 'links');

    // Create link labels group
    const linkLabelsGroup = g.append('g').attr('class', 'link-labels');

    // Create nodes group
    const nodesGroup = g.append('g').attr('class', 'nodes');

    // Initialize simulation
    simulation = d3.forceSimulation<GraphNode>(data.nodes)
      .force('link', d3.forceLink<GraphNode, GraphLink>(data.links)
        .id((d) => d.id)
        .distance(200))
      .force('charge', d3.forceManyBody().strength(-500))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(120));

    // Create links
    const links = linksGroup.selectAll('.link')
      .data(data.links)
      .join('path')
      .attr('class', 'link')
      .attr('stroke', (d) => relationColors[d.type as RelationType] || '#999')
      .attr('stroke-width', (d) => 1 + d.strength * 2)
      .attr('stroke-opacity', 0.6)
      .attr('fill', 'none')
      .attr('marker-end', (d) => `url(#arrow-${d.type})`);

    // Create link labels
    const linkLabels = linkLabelsGroup.selectAll('.link-label')
      .data(data.links)
      .join('text')
      .attr('class', 'link-label')
      .attr('font-size', 10)
      .attr('fill', (d) => relationColors[d.type as RelationType] || '#666')
      .attr('text-anchor', 'middle')
      .attr('dy', -5)
      .text((d) => d.type.toUpperCase().replace('_', ' '));

    // Create nodes using foreignObject for HTML content
    const nodes = nodesGroup.selectAll('.node')
      .data(data.nodes)
      .join('g')
      .attr('class', 'node')
      .call(d3.drag<SVGGElement, GraphNode>()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended)
      );

    // Add foreignObject for each node
    nodes.each(function (d) {
      const node = d3.select(this);
      const isExpanded = $expandedNodeIds.has(d.id);

      // Background rect for interaction
      node.append('rect')
        .attr('class', 'node-bg')
        .attr('width', nodeWidth)
        .attr('height', isExpanded ? nodeHeightExpanded : nodeHeightCollapsed)
        .attr('x', -nodeWidth / 2)
        .attr('y', isExpanded ? -nodeHeightExpanded / 2 : -nodeHeightCollapsed / 2)
        .attr('rx', 8)
        .attr('fill', 'white')
        .attr('stroke', getNodeBorderColor(d))
        .attr('stroke-width', 2)
        .style('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))');

      // ForeignObject for HTML content
      const fo = node.append('foreignObject')
        .attr('width', nodeWidth - 16)
        .attr('height', (isExpanded ? nodeHeightExpanded : nodeHeightCollapsed) - 16)
        .attr('x', -nodeWidth / 2 + 8)
        .attr('y', (isExpanded ? -nodeHeightExpanded / 2 : -nodeHeightCollapsed / 2) + 8);

      const div = fo.append('xhtml:div')
        .attr('class', `node-content ${isExpanded ? 'expanded' : ''}`)
        .style('font-family', '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif')
        .style('font-size', '12px')
        .style('line-height', '1.4')
        .style('overflow', 'hidden')
        .style('height', '100%');

      updateNodeContent(div, d, isExpanded);

      // Click handler
      node.on('click', (event: MouseEvent) => {
        event.stopPropagation();
        toggleNode(d.id);
      });
    });

    // Simulation tick
    simulation.on('tick', () => {
      links.attr('d', (d) => {
        const source = d.source as GraphNode;
        const target = d.target as GraphNode;
        const dx = (target.x || 0) - (source.x || 0);
        const dy = (target.y || 0) - (source.y || 0);
        const dr = Math.sqrt(dx * dx + dy * dy) * 0.8;
        return `M${source.x},${source.y}A${dr},${dr} 0 0,1 ${target.x},${target.y}`;
      });

      linkLabels
        .attr('x', (d) => {
          const source = d.source as GraphNode;
          const target = d.target as GraphNode;
          return ((source.x || 0) + (target.x || 0)) / 2;
        })
        .attr('y', (d) => {
          const source = d.source as GraphNode;
          const target = d.target as GraphNode;
          return ((source.y || 0) + (target.y || 0)) / 2;
        });

      nodes.attr('transform', (d) => `translate(${d.x},${d.y})`);
    });

    // Double-click to fit
    svgEl.on('dblclick.zoom', () => {
      svgEl.transition().duration(500).call(
        zoom.transform,
        d3.zoomIdentity
      );
    });
  }

  function getNodeBorderColor(node: GraphNode): string {
    // Use the most common relation type's color
    if (node.relations.length === 0) return '#e1e4e8';
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
    return relationColors[maxType as RelationType] || '#e1e4e8';
  }

  function updateNodeContent(div: d3.Selection<HTMLDivElement, unknown, null, undefined>, node: GraphNode, isExpanded: boolean) {
    div.html('');

    // Header with confidence
    const header = div.append('div')
      .style('display', 'flex')
      .style('justify-content', 'space-between')
      .style('margin-bottom', '4px');

    header.append('span')
      .style('font-weight', '500')
      .style('color', getConfidenceColor(node.confidence))
      .text(`${Math.round(node.confidence * 100)}%`);

    header.append('span')
      .style('color', '#6a737d')
      .style('font-size', '11px')
      .text(`${node.instance_count}x`);

    // Summary
    const summary = div.append('div')
      .style('color', '#24292e')
      .style('overflow', 'hidden')
      .style('text-overflow', 'ellipsis')
      .text(isExpanded ? node.summary : truncate(node.summary, 60));

    if (isExpanded) {
      summary.style('margin-bottom', '8px');

      // Conditions
      if (node.conditions && node.conditions.length > 0) {
        div.append('div')
          .style('font-size', '10px')
          .style('color', '#586069')
          .style('margin-bottom', '4px')
          .style('font-weight', '500')
          .text('Conditions:');

        const condList = div.append('div')
          .style('font-size', '10px')
          .style('color', '#6a737d')
          .style('margin-bottom', '8px');

        node.conditions.forEach((c) => {
          condList.append('div').text(`• ${c}`);
        });
      }

      // Source episodes
      if (node.source_episodes.length > 0) {
        div.append('div')
          .style('font-size', '10px')
          .style('color', '#586069')
          .style('margin-bottom', '4px')
          .style('font-weight', '500')
          .text(`Episodes (${node.source_episodes.length}):`);

        const epList = div.append('div')
          .style('font-size', '10px')
          .style('max-height', '80px')
          .style('overflow-y', 'auto');

        node.source_episodes.slice(0, 3).forEach((ep) => {
          epList.append('div')
            .style('padding', '2px 4px')
            .style('margin-bottom', '2px')
            .style('background', '#f6f8fa')
            .style('border-radius', '3px')
            .style('color', '#24292e')
            .text(truncate(ep.content, 80));
        });
      }

      // Relations
      if (node.relations.length > 0) {
        div.append('div')
          .style('font-size', '10px')
          .style('color', '#586069')
          .style('margin-top', '8px')
          .style('margin-bottom', '4px')
          .style('font-weight', '500')
          .text(`Relations (${node.relations.length}):`);

        const relList = div.append('div')
          .style('font-size', '10px');

        node.relations.slice(0, 3).forEach((rel) => {
          const relDiv = relList.append('div')
            .style('display', 'flex')
            .style('align-items', 'center')
            .style('gap', '4px')
            .style('margin-bottom', '2px');

          relDiv.append('span')
            .style('color', relationColors[rel.type as RelationType] || '#666')
            .style('font-weight', '500')
            .text(rel.type.toUpperCase());

          relDiv.append('span')
            .style('color', '#6a737d')
            .text(truncate(rel.target_summary || rel.target_id, 30));
        });
      }
    }
  }

  function getConfidenceColor(confidence: number): string {
    if (confidence >= 0.7) return '#28a745';
    if (confidence >= 0.4) return '#ffc107';
    return '#dc3545';
  }

  function truncate(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength - 3) + '...';
  }

  function toggleNode(nodeId: string) {
    const newExpanded = new Set($expandedNodeIds);
    if (newExpanded.has(nodeId)) {
      newExpanded.delete(nodeId);
    } else {
      newExpanded.add(nodeId);
    }
    expandedNodeIds.set(newExpanded);

    // Update the node visually
    if ($graphData) {
      const node = $graphData.nodes.find((n) => n.id === nodeId);
      if (node) {
        const isExpanded = newExpanded.has(nodeId);
        const nodeEl = d3.select(svg).select(`.node`).filter((d: any) => d.id === nodeId);

        nodeEl.select('.node-bg')
          .transition()
          .duration(200)
          .attr('height', isExpanded ? nodeHeightExpanded : nodeHeightCollapsed)
          .attr('y', isExpanded ? -nodeHeightExpanded / 2 : -nodeHeightCollapsed / 2);

        nodeEl.select('foreignObject')
          .transition()
          .duration(200)
          .attr('height', (isExpanded ? nodeHeightExpanded : nodeHeightCollapsed) - 16)
          .attr('y', (isExpanded ? -nodeHeightExpanded / 2 : -nodeHeightCollapsed / 2) + 8);

        const div = nodeEl.select('.node-content') as unknown as d3.Selection<HTMLDivElement, unknown, null, undefined>;
        div.classed('expanded', isExpanded);
        updateNodeContent(div, node, isExpanded);
      }
    }

    // Update collision radius
    if (simulation) {
      simulation.force('collision', d3.forceCollide().radius((d: any) => {
        return newExpanded.has(d.id) ? 160 : 80;
      }));
      simulation.alpha(0.3).restart();
    }
  }

  function dragstarted(event: d3.D3DragEvent<SVGGElement, GraphNode, GraphNode>) {
    if (!event.active && simulation) simulation.alphaTarget(0.3).restart();
    event.subject.fx = event.subject.x;
    event.subject.fy = event.subject.y;
  }

  function dragged(event: d3.D3DragEvent<SVGGElement, GraphNode, GraphNode>) {
    event.subject.fx = event.x;
    event.subject.fy = event.y;
  }

  function dragended(event: d3.D3DragEvent<SVGGElement, GraphNode, GraphNode>) {
    if (!event.active && simulation) simulation.alphaTarget(0);
    event.subject.fx = null;
    event.subject.fy = null;
  }
</script>

<div class="graph-visualization">
  <div class="header">
    <h2>Concept Graph</h2>
    <div class="legend">
      {#each Object.entries(relationColors) as [type, color]}
        <div class="legend-item">
          <span class="legend-color" style="background: {color}"></span>
          <span class="legend-label">{type.replace('_', ' ')}</span>
        </div>
      {/each}
    </div>
  </div>

  <div class="graph-container" bind:this={container}>
    {#if $graphLoading}
      <div class="loading">Loading graph...</div>
    {:else if $graphError}
      <div class="error">{$graphError}</div>
    {:else if !$graphData || $graphData.nodes.length === 0}
      <div class="empty">No concepts to display</div>
    {:else}
      <svg bind:this={svg}></svg>
      <div class="controls">
        <div class="hint">Click nodes to expand. Drag to move. Scroll to zoom. Double-click to reset.</div>
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
    align-items: flex-start;
    margin-bottom: var(--space-md);
  }

  h2 {
    font-size: var(--font-size-2xl);
  }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
    max-width: 500px;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: var(--font-size-xs);
  }

  .legend-color {
    width: 12px;
    height: 12px;
    border-radius: 2px;
  }

  .legend-label {
    color: var(--color-text-secondary);
    text-transform: capitalize;
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

  .controls {
    position: absolute;
    bottom: var(--space-md);
    left: var(--space-md);
    right: var(--space-md);
    display: flex;
    justify-content: center;
  }

  .hint {
    padding: var(--space-xs) var(--space-md);
    background: rgba(255, 255, 255, 0.9);
    border-radius: var(--radius-md);
    font-size: var(--font-size-sm);
    color: var(--color-text-muted);
    box-shadow: var(--shadow-sm);
  }

  .loading,
  .error,
  .empty {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-text-secondary);
  }

  .error {
    color: var(--color-contradicts);
  }

  :global(.node) {
    cursor: pointer;
  }

  :global(.node:hover .node-bg) {
    stroke-width: 3px;
  }

  :global(.link) {
    pointer-events: none;
  }

  :global(.link-label) {
    pointer-events: none;
    font-weight: 500;
  }
</style>
