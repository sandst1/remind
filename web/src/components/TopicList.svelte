<script lang="ts">
  import { onMount } from 'svelte';
  import { currentDb, topics, topicsLoading, topicsError, selectedTopic } from '../lib/stores';
  import { fetchTopics, createTopic, updateTopic as apiUpdateTopic, deleteTopic as apiDeleteTopic, fetchConcepts, fetchEpisodes } from '../lib/api';
  import type { Topic, Concept, Episode } from '../lib/types';
  import { Plus, Pencil, Trash2, ChevronDown, ChevronRight, FolderOpen } from 'lucide-svelte';

  let showCreateForm = false;
  let newName = '';
  let newDescription = '';
  let creating = false;

  let editingId: string | null = null;
  let editName = '';
  let editDescription = '';
  let saving = false;

  let expandedId: string | null = null;
  let drillConcepts: Concept[] = [];
  let drillEpisodes: Episode[] = [];
  let drillLoading = false;

  let mounted = false;

  $: if (mounted && $currentDb) {
    loadTopics();
  }

  onMount(() => {
    mounted = true;
  });

  async function loadTopics() {
    $topicsLoading = true;
    $topicsError = null;
    try {
      const res = await fetchTopics();
      $topics = res.topics;
    } catch (e: any) {
      $topicsError = e.message;
    } finally {
      $topicsLoading = false;
    }
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    creating = true;
    try {
      await createTopic(newName.trim(), newDescription.trim());
      newName = '';
      newDescription = '';
      showCreateForm = false;
      await loadTopics();
    } catch (e: any) {
      $topicsError = e.message;
    } finally {
      creating = false;
    }
  }

  function startEdit(t: Topic) {
    editingId = t.id;
    editName = t.name;
    editDescription = t.description;
  }

  async function handleSave() {
    if (!editingId || !editName.trim()) return;
    saving = true;
    try {
      await apiUpdateTopic(editingId, { name: editName.trim(), description: editDescription.trim() });
      editingId = null;
      await loadTopics();
    } catch (e: any) {
      $topicsError = e.message;
    } finally {
      saving = false;
    }
  }

  function cancelEdit() {
    editingId = null;
  }

  async function handleDelete(id: string) {
    try {
      await apiDeleteTopic(id);
      await loadTopics();
    } catch (e: any) {
      $topicsError = e.message;
    }
  }

  async function toggleExpand(id: string) {
    if (expandedId === id) {
      expandedId = null;
      return;
    }
    expandedId = id;
    drillLoading = true;
    try {
      const [cRes, eRes] = await Promise.all([
        fetchConcepts({ topic: id, limit: 10 }),
        fetchEpisodes({ topic: id, limit: 10 }),
      ]);
      drillConcepts = cRes.concepts;
      drillEpisodes = eRes.episodes;
    } catch (e: any) {
      console.error(e);
    } finally {
      drillLoading = false;
    }
  }

  function canDelete(t: Topic): boolean {
    return (t.episode_count ?? 0) === 0 && (t.concept_count ?? 0) === 0;
  }

  function truncate(s: string, max: number): string {
    return s.length > max ? s.slice(0, max) + '...' : s;
  }
</script>

<div class="topic-list">
  <div class="header">
    <h2><FolderOpen size={20} /> Topics</h2>
    <button class="btn btn-sm btn-primary" onclick={() => (showCreateForm = !showCreateForm)}>
      <Plus size={14} /> New
    </button>
  </div>

  {#if showCreateForm}
    <div class="create-form card">
      <input class="input" bind:value={newName} placeholder="Topic name" />
      <input class="input" bind:value={newDescription} placeholder="Description (optional)" />
      <div class="form-actions">
        <button class="btn btn-sm btn-primary" onclick={handleCreate} disabled={creating || !newName.trim()}>
          {creating ? 'Creating...' : 'Create'}
        </button>
        <button class="btn btn-sm" onclick={() => (showCreateForm = false)}>Cancel</button>
      </div>
    </div>
  {/if}

  {#if $topicsError}
    <div class="error">{$topicsError}</div>
  {/if}

  {#if $topicsLoading}
    <div class="loading">Loading topics...</div>
  {:else if $topics.length === 0}
    <div class="empty">No topics yet. Create one to get started.</div>
  {:else}
    <div class="topics-grid">
      {#each $topics as t (t.id)}
        <div class="topic-card card" class:expanded={expandedId === t.id}>
          {#if editingId === t.id}
            <div class="edit-form">
              <input class="input" bind:value={editName} placeholder="Name" />
              <input class="input" bind:value={editDescription} placeholder="Description" />
              <div class="form-actions">
                <button class="btn btn-sm btn-primary" onclick={handleSave} disabled={saving}>Save</button>
                <button class="btn btn-sm" onclick={cancelEdit}>Cancel</button>
              </div>
            </div>
          {:else}
            <div class="topic-header" role="button" tabindex="0" onclick={() => toggleExpand(t.id)} onkeydown={(e: KeyboardEvent) => e.key === 'Enter' && toggleExpand(t.id)}>
              <span class="expand-icon">
                {#if expandedId === t.id}
                  <ChevronDown size={16} />
                {:else}
                  <ChevronRight size={16} />
                {/if}
              </span>
              <div class="topic-info">
                <span class="topic-name">{t.name}</span>
                <span class="topic-id">{t.id}</span>
                {#if t.description}
                  <span class="topic-desc">{truncate(t.description, 80)}</span>
                {/if}
              </div>
              <div class="topic-stats">
                <span class="stat">{t.episode_count ?? 0} episodes</span>
                <span class="stat">{t.concept_count ?? 0} concepts</span>
              </div>
              <div class="topic-actions" role="group" onclick={(e: MouseEvent) => e.stopPropagation()} onkeydown={(e: KeyboardEvent) => e.stopPropagation()}>
                <button class="btn-icon" title="Edit" onclick={() => startEdit(t)}>
                  <Pencil size={14} />
                </button>
                <button
                  class="btn-icon danger"
                  title={canDelete(t) ? 'Delete' : 'Cannot delete — topic in use'}
                  disabled={!canDelete(t)}
                  onclick={() => handleDelete(t.id)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>

            {#if expandedId === t.id}
              <div class="drill-down">
                {#if drillLoading}
                  <div class="loading">Loading...</div>
                {:else}
                  {#if drillConcepts.length > 0}
                    <h4>Concepts ({drillConcepts.length})</h4>
                    <ul class="drill-list">
                      {#each drillConcepts as c}
                        <li>
                          <span class="drill-id">[{c.id}]</span>
                          <span class="drill-title">{c.title || truncate(c.summary, 60)}</span>
                          <span class="drill-meta">conf: {c.confidence.toFixed(2)}</span>
                        </li>
                      {/each}
                    </ul>
                  {:else}
                    <p class="empty-sub">No concepts in this topic.</p>
                  {/if}

                  {#if drillEpisodes.length > 0}
                    <h4>Recent Episodes ({drillEpisodes.length})</h4>
                    <ul class="drill-list">
                      {#each drillEpisodes as e}
                        <li>
                          <span class="drill-type">[{e.episode_type}]</span>
                          <span class="drill-content">{truncate(e.content, 80)}</span>
                        </li>
                      {/each}
                    </ul>
                  {:else}
                    <p class="empty-sub">No episodes in this topic.</p>
                  {/if}
                {/if}
              </div>
            {/if}
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .topic-list {
    padding: 1.5rem;
    max-width: 960px;
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
  }

  .header h2 {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--color-text);
    margin: 0;
  }

  .card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 0.75rem 1rem;
  }

  .create-form {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }

  .input {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    color: var(--color-text);
    font-size: 0.875rem;
    width: 100%;
  }
  .input:focus {
    outline: none;
    border-color: var(--color-accent);
  }

  .form-actions {
    display: flex;
    gap: 0.5rem;
  }

  .btn {
    cursor: pointer;
    border: 1px solid var(--color-border);
    border-radius: 6px;
    background: var(--color-surface);
    color: var(--color-text);
    padding: 0.4rem 0.75rem;
    font-size: 0.8rem;
  }
  .btn:hover { background: var(--color-hover); }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .btn-primary {
    background: var(--color-accent);
    color: white;
    border-color: var(--color-accent);
  }
  .btn-primary:hover { opacity: 0.9; }

  .btn-sm { font-size: 0.8rem; padding: 0.35rem 0.65rem; display: flex; align-items: center; gap: 0.3rem; }

  .btn-icon {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--color-text-muted);
    padding: 0.3rem;
    border-radius: 4px;
  }
  .btn-icon:hover { color: var(--color-text); background: var(--color-hover); }
  .btn-icon.danger:hover { color: var(--color-danger, #e55); }
  .btn-icon:disabled { opacity: 0.3; cursor: not-allowed; }

  .error {
    color: var(--color-danger, #e55);
    background: var(--color-surface);
    border: 1px solid var(--color-danger, #e55);
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    margin-bottom: 1rem;
    font-size: 0.85rem;
  }

  .loading, .empty {
    color: var(--color-text-muted);
    padding: 2rem;
    text-align: center;
    font-size: 0.9rem;
  }

  .topics-grid {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .topic-card {
    transition: border-color 0.15s;
  }
  .topic-card.expanded {
    border-color: var(--color-accent);
  }

  .topic-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    user-select: none;
  }

  .expand-icon {
    color: var(--color-text-muted);
    flex-shrink: 0;
  }

  .topic-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }

  .topic-name {
    font-weight: 600;
    color: var(--color-text);
    font-size: 0.95rem;
  }

  .topic-id {
    font-size: 0.75rem;
    color: var(--color-text-muted);
    font-family: var(--font-mono, monospace);
  }

  .topic-desc {
    font-size: 0.8rem;
    color: var(--color-text-muted);
  }

  .topic-stats {
    display: flex;
    gap: 0.75rem;
    flex-shrink: 0;
  }

  .stat {
    font-size: 0.75rem;
    color: var(--color-text-muted);
    white-space: nowrap;
  }

  .topic-actions {
    display: flex;
    gap: 0.25rem;
    flex-shrink: 0;
  }

  .edit-form {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .drill-down {
    margin-top: 0.75rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--color-border);
  }

  .drill-down h4 {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--color-text-muted);
    margin: 0.5rem 0 0.25rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .drill-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .drill-list li {
    font-size: 0.8rem;
    color: var(--color-text);
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
    padding: 0.2rem 0;
  }

  .drill-id, .drill-type {
    font-family: var(--font-mono, monospace);
    font-size: 0.7rem;
    color: var(--color-accent);
    flex-shrink: 0;
  }

  .drill-title, .drill-content {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .drill-meta {
    font-size: 0.7rem;
    color: var(--color-text-muted);
    flex-shrink: 0;
  }

  .empty-sub {
    font-size: 0.8rem;
    color: var(--color-text-muted);
    margin: 0.25rem 0;
  }
</style>
