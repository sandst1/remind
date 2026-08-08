<script lang="ts">
  import { onMount } from 'svelte';
  import { selectedLabel, labels, currentDb } from '../lib/stores';
  import { fetchLabels } from '../lib/api';
  import { Tag, X } from 'lucide-svelte';

  let mounted = false;

  onMount(() => {
    mounted = true;
    loadLabels();
  });

  $: if (mounted && $currentDb) {
    loadLabels();
  }

  async function loadLabels() {
    if (!$currentDb) return;
    try {
      const result = await fetchLabels();
      labels.set(result.labels);
    } catch {
      // ignore
    }
  }

  $: selectedValue = $selectedLabel ? `${$selectedLabel.key}:${$selectedLabel.value}` : '';

  function handleChange(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    if (!value) {
      selectedLabel.set(null);
      return;
    }
    const [key, val] = value.split(':');
    selectedLabel.set({ key, value: val });
  }

  function clear() {
    selectedLabel.set(null);
  }
</script>

<div class="label-filter">
  <div class="select-wrapper">
    <Tag size={14} />
    <select value={selectedValue} onchange={handleChange}>
      <option value="">All labels</option>
      {#each $labels as l}
        <option value={`${l.key}:${l.value}`}>{l.key}={l.value} ({l.count})</option>
      {/each}
    </select>
    {#if $selectedLabel}
      <button class="clear-btn" onclick={clear} title="Clear label filter">
        <X size={12} />
      </button>
    {/if}
  </div>
</div>

<style>
  .label-filter {
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
