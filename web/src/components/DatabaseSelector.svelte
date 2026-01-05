<script lang="ts">
  import { currentDb, databases } from '../lib/stores';

  function handleChange(event: Event) {
    const select = event.target as HTMLSelectElement;
    const newDb = select.value;
    if (newDb !== $currentDb) {
      // Navigate with new db param
      const url = new URL(window.location.href);
      url.searchParams.set('db', newDb);
      window.location.href = url.toString();
    }
  }
</script>

<select class="db-select" value={$currentDb} onchange={handleChange}>
  <option value="">Select database...</option>
  {#each $databases as db}
    <option value={db.name}>{db.name}</option>
  {/each}
</select>

<style>
  .db-select {
    width: 100%;
    padding: var(--space-sm);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    color: var(--color-text);
    font-size: var(--font-size-sm);
    cursor: pointer;
  }

  .db-select:focus {
    outline: none;
    border-color: var(--color-primary);
  }
</style>
