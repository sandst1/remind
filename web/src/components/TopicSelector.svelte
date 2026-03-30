<script lang="ts">
  import { onMount } from 'svelte';
  import { selectedTopic, topics, currentDb } from '../lib/stores';
  import { fetchTopics } from '../lib/api';
  import { FolderOpen, X } from 'lucide-svelte';

  let mounted = false;

  onMount(() => {
    mounted = true;
    loadTopics();
  });

  $: if (mounted && $currentDb) {
    loadTopics();
  }

  async function loadTopics() {
    if (!$currentDb) return;
    try {
      const result = await fetchTopics();
      topics.set(result.topics);
    } catch {
      // ignore
    }
  }

  function handleChange(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    selectedTopic.set(value || null);
  }

  function clear() {
    selectedTopic.set(null);
  }
</script>

<div class="topic-selector">
  <div class="select-wrapper">
    <FolderOpen size={14} />
    <select value={$selectedTopic ?? ''} onchange={handleChange}>
      <option value="">All topics</option>
      {#each $topics as t}
        <option value={t.id}>{t.name}</option>
      {/each}
    </select>
    {#if $selectedTopic}
      <button class="clear-btn" onclick={clear} title="Clear topic filter">
        <X size={12} />
      </button>
    {/if}
  </div>
</div>

<style>
  .topic-selector {
    width: 100%;
  }

  .select-wrapper {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-xs) var(--space-sm);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
  }

  select {
    flex: 1;
    border: none;
    background: transparent;
    color: var(--color-text);
    font-size: var(--font-size-xs);
    cursor: pointer;
    outline: none;
    min-width: 0;
  }

  .clear-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2px;
    border-radius: var(--radius-sm);
    color: var(--color-text-secondary);
    background: transparent;
  }

  .clear-btn:hover {
    background: var(--color-zinc-200);
    color: var(--color-text);
  }

  :global([data-theme="dark"]) .clear-btn:hover {
    background: var(--color-zinc-700);
  }
</style>
