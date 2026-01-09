<script lang="ts">
  import { onMount } from 'svelte';
  import { currentDb, currentView, databases, hasDatabase, type View, theme } from './lib/stores';
  import { fetchDatabases, getDbParam } from './lib/api';
  import Dashboard from './components/Dashboard.svelte';
  import EntityList from './components/EntityList.svelte';
  import ConceptList from './components/ConceptList.svelte';
  import EpisodeTimeline from './components/EpisodeTimeline.svelte';
  import ConceptMap from './components/ConceptMap.svelte';
  import EntityGraph from './components/EntityGraph.svelte';
  import DatabaseSelector from './components/DatabaseSelector.svelte';

  // Icons
  import { Home, Tag, History, Lightbulb, Moon, Sun, Monitor, Circle, Network } from 'lucide-svelte';

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

    // Listen for system theme changes
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (e: MediaQueryListEvent) => {
      if ($theme === 'system') {
        document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
      }
    };
    
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  });

  // Theme handling
  $: {
    if (typeof document !== 'undefined') {
      const t = $theme;
      const root = document.documentElement;
      
      if (t === 'system') {
        const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        root.setAttribute('data-theme', systemTheme);
      } else {
        root.setAttribute('data-theme', t);
      }
    }
  }

  const navItems: Array<{ view: View; label: string; icon: any }> = [
    { view: 'dashboard', label: 'Dashboard', icon: Home },
    { view: 'episodes', label: 'Episodes', icon: History },
    { view: 'entities', label: 'Entities', icon: Tag },
    { view: 'concepts', label: 'Concepts', icon: Lightbulb },
    { view: 'concept-map', label: 'Concept Map', icon: Circle },
    { view: 'entity-graph', label: 'Entity Graph', icon: Network },
  ];

  function toggleTheme() {
    if ($theme === 'light') theme.set('dark');
    else if ($theme === 'dark') theme.set('system');
    else theme.set('light');
  }

  // Helper to get theme icon
  function getThemeIcon(t: string) {
    if (t === 'light') return Sun;
    if (t === 'dark') return Moon;
    return Monitor;
  }
</script>

<div class="app">
  <aside class="sidebar">
    <div class="sidebar-header glass">
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
            <span class="nav-icon">
              <svelte:component this={item.icon} size={18} />
            </span>
            <span class="nav-label">{item.label}</span>
          </button>
        {/each}
      </nav>

      <div class="sidebar-footer">
        <button class="nav-item theme-toggle" onclick={toggleTheme} title="Toggle theme ({$theme})">
          <span class="nav-icon">
            <svelte:component this={getThemeIcon($theme)} size={18} />
          </span>
          <span class="nav-label">Theme: {$theme}</span>
        </button>
      </div>
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
      {:else if $currentView === 'concept-map'}
        <ConceptMap />
      {:else if $currentView === 'entity-graph'}
        <EntityGraph />
      {/if}
    {/if}
  </main>
</div>

<style>
  .app {
    display: flex;
    height: 100vh;
    overflow: hidden;
    background: var(--color-bg);
  }

  .sidebar {
    width: var(--sidebar-width);
    background: var(--color-surface);
    border-right: 1px solid var(--color-border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    z-index: 20;
  }

  .sidebar-header {
    padding: var(--space-lg);
    border-bottom: 1px solid var(--color-border);
    background: rgba(255, 255, 255, 0.9); /* Fallback for glass */
  }

  :global([data-theme="dark"]) .sidebar-header {
    background: rgba(24, 24, 27, 0.9);
  }

  .logo {
    font-size: var(--font-size-xl);
    font-weight: 700;
    margin-bottom: var(--space-md);
    color: var(--color-text);
    letter-spacing: -0.025em;
  }

  .nav {
    flex: 1;
    padding: var(--space-md);
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
    overflow-y: auto;
  }

  .sidebar-footer {
    padding: var(--space-md);
    border-top: 1px solid var(--color-border);
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    border: 1px solid transparent; /* Reserve space for border */
    background: transparent;
    border-radius: var(--radius-md);
    color: var(--color-text-secondary);
    text-align: left;
    transition: all 0.15s ease;
    font-weight: 500;
    position: relative;
    width: 100%;
  }

  .nav-item:hover {
    background: var(--color-zinc-100);
    color: var(--color-text);
  }

  :global([data-theme="dark"]) .nav-item:hover {
    background: var(--color-zinc-800);
  }

  .nav-item.active {
    background: var(--color-primary-bg);
    color: var(--color-primary);
    border-color: rgba(37, 99, 235, 0.1); /* Subtle border for active state */
  }

  .nav-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.2s ease;
  }
  
  .nav-item:hover .nav-icon {
    transform: scale(1.05);
  }

  .nav-label {
    font-size: var(--font-size-sm);
    text-transform: capitalize;
  }

  .main {
    flex: 1;
    overflow: auto;
    padding: var(--space-lg); /* Updated to lg (24px) */
    background: var(--color-bg);
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
    font-weight: 600;
  }
</style>
