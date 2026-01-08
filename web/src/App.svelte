<script lang="ts">
  import { onMount } from 'svelte';
  import { currentDb, currentView, databases, hasDatabase, type View } from './lib/stores';
  import { fetchDatabases, getDbParam } from './lib/api';
  import Dashboard from './components/Dashboard.svelte';
  import EntityList from './components/EntityList.svelte';
  import ConceptList from './components/ConceptList.svelte';
  import EpisodeTimeline from './components/EpisodeTimeline.svelte';
  import Sidebar from './components/Sidebar.svelte';
  import DatabaseSelector from './components/DatabaseSelector.svelte';

  let initialized = false;

  onMount(async () => {
    // Get db from URL
    const db = getDbParam();
    currentDb.set(db);

    // Fetch available databases
    try {
      const dbs = await fetchDatabases();
      databases.set(dbs);
    } catch (e) {
      console.error('Failed to fetch databases:', e);
    }

    initialized = true;
  });

  const navItems: Array<{ view: View; label: string; icon: string }> = [
    { view: 'dashboard', label: 'Dashboard', icon: 'home' },
    { view: 'entities', label: 'Entities', icon: 'tag' },
    { view: 'episodes', label: 'Episodes', icon: 'history' },
    { view: 'concepts', label: 'Concepts', icon: 'lightbulb' },
  ];
</script>

<div class="app">
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1 class="logo">Remind</h1>
      <DatabaseSelector />
    </div>

    {#if $hasDatabase}
      <nav class="nav">
        {#each navItems as item}
          <button
            class="nav-item"
            class:active={$currentView === item.view}
            onclick={() => currentView.set(item.view)}
          >
            <span class="nav-icon">{item.icon === 'home' ? '🏠' : item.icon === 'lightbulb' ? '💡' : item.icon === 'history' ? '📜' : item.icon === 'tag' ? '🏷️' : '🕸️'}</span>
            <span class="nav-label">{item.label}</span>
          </button>
        {/each}
      </nav>
    {/if}
  </aside>

  <main class="main">
    {#if !initialized}
      <div class="loading">Loading...</div>
    {:else if !$hasDatabase}
      <div class="no-db">
        <h2>Select a Database</h2>
        <p>Choose a database from the dropdown above to explore your memories.</p>
      </div>
    {:else}
      {#if $currentView === 'dashboard'}
        <Dashboard />
      {:else if $currentView === 'entities'}
        <EntityList />
      {:else if $currentView === 'episodes'}
        <EpisodeTimeline />
      {:else if $currentView === 'concepts'}
        <ConceptList />
      {/if}
    {/if}
  </main>
</div>

<style>
  .app {
    display: flex;
    height: 100vh;
    overflow: hidden;
  }

  .sidebar {
    width: var(--sidebar-width);
    background: var(--color-surface);
    border-right: 1px solid var(--color-border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }

  .sidebar-header {
    padding: var(--space-md);
    border-bottom: 1px solid var(--color-border);
  }

  .logo {
    font-size: var(--font-size-xl);
    font-weight: 600;
    margin-bottom: var(--space-sm);
    color: var(--color-primary);
  }

  .nav {
    flex: 1;
    padding: var(--space-sm);
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    border: none;
    background: transparent;
    border-radius: var(--radius-md);
    color: var(--color-text-secondary);
    text-align: left;
    transition: all 0.15s ease;
  }

  .nav-item:hover {
    background: var(--color-bg);
    color: var(--color-text);
  }

  .nav-item.active {
    background: var(--color-primary);
    color: white;
  }

  .nav-icon {
    font-size: var(--font-size-lg);
  }

  .nav-label {
    font-size: var(--font-size-base);
  }

  .main {
    flex: 1;
    overflow: auto;
    padding: var(--space-lg);
  }

  .loading,
  .no-db {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-text-secondary);
  }

  .no-db h2 {
    margin-bottom: var(--space-sm);
    color: var(--color-text);
  }
</style>
