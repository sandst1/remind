<script lang="ts">
  import { onMount } from 'svelte';
  import { currentDb } from '../lib/stores';
  import { fetchTasks, updateTaskStatus, addTask, updateEpisode } from '../lib/api';
  import type { Episode, TaskStatus } from '../lib/types';
  import { Circle, Play, CheckCircle2, Ban, Plus, ChevronDown, ChevronUp, Pencil } from 'lucide-svelte';

  let tasks: Episode[] = [];
  let loading = false;
  let error: string | null = null;
  let showDone = false;
  let mounted = false;
  let showAddForm = false;
  let newTaskContent = '';
  let newTaskPriority = 'p1';
  let addingTask = false;

  const columns: { status: TaskStatus; label: string; icon: any }[] = [
    { status: 'todo', label: 'To Do', icon: Circle },
    { status: 'in_progress', label: 'In Progress', icon: Play },
    { status: 'blocked', label: 'Blocked', icon: Ban },
    { status: 'done', label: 'Done', icon: CheckCircle2 },
  ];

  onMount(() => {
    mounted = true;
    loadTasks();
  });

  $: if (mounted && $currentDb) {
    loadTasks();
  }

  async function loadTasks() {
    if (!$currentDb) return;
    loading = true;
    error = null;
    try {
      const response = await fetchTasks({ include_done: showDone });
      tasks = response.tasks;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load tasks';
    } finally {
      loading = false;
    }
  }

  function tasksByStatus(status: TaskStatus): Episode[] {
    return tasks.filter(t => (t.metadata?.status || 'todo') === status);
  }

  async function handleStatusChange(taskId: string, newStatus: TaskStatus) {
    try {
      await updateTaskStatus(taskId, newStatus);
      await loadTasks();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to update task';
    }
  }

  async function handleAddTask() {
    if (!newTaskContent.trim()) return;
    addingTask = true;
    try {
      await addTask(newTaskContent.trim(), { priority: newTaskPriority });
      newTaskContent = '';
      showAddForm = false;
      await loadTasks();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to add task';
    } finally {
      addingTask = false;
    }
  }

  function toggleDone() {
    showDone = !showDone;
    loadTasks();
  }

  function formatDate(isoDate: string): string {
    const date = new Date(isoDate);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function getNextStatuses(current: string): TaskStatus[] {
    const transitions: Record<string, TaskStatus[]> = {
      todo: ['in_progress', 'blocked'],
      in_progress: ['done', 'blocked', 'todo'],
      blocked: ['todo', 'in_progress'],
      done: ['todo'],
    };
    return transitions[current] || [];
  }

  // Drag-and-drop state
  let draggingTaskId: string | null = null;
  let dragOverColumn: TaskStatus | null = null;

  function handleDragStart(e: DragEvent, task: Episode) {
    draggingTaskId = task.id;
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', task.id);
    }
  }

  function handleDragEnd() {
    draggingTaskId = null;
    dragOverColumn = null;
  }

  function handleDragOver(e: DragEvent, status: TaskStatus) {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    dragOverColumn = status;
  }

  function handleDragLeave(e: DragEvent, colEl: HTMLElement) {
    // Only clear if we're leaving the column entirely (not entering a child)
    if (!colEl.contains(e.relatedTarget as Node)) {
      dragOverColumn = null;
    }
  }

  async function handleDrop(e: DragEvent, targetStatus: TaskStatus) {
    e.preventDefault();
    dragOverColumn = null;
    const taskId = draggingTaskId || e.dataTransfer?.getData('text/plain');
    if (!taskId) return;
    const task = tasks.find(t => t.id === taskId);
    if (!task) return;
    const currentStatus = (task.metadata?.status || 'todo') as TaskStatus;
    if (currentStatus === targetStatus) return;
    draggingTaskId = null;
    await handleStatusChange(taskId, targetStatus);
  }

  // Inline editing state
  let editingId: string | null = null;
  let editingContent: string = '';
  let savingId: string | null = null;

  function startEdit(task: Episode) {
    editingId = task.id;
    editingContent = task.content;
  }

  function cancelEdit() {
    editingId = null;
    editingContent = '';
  }

  async function saveEdit(taskId: string) {
    if (savingId) return;
    savingId = taskId;
    try {
      await updateEpisode(taskId, { content: editingContent });
      editingId = null;
      editingContent = '';
      await loadTasks();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to update task';
    } finally {
      savingId = null;
    }
  }

  function handleEditKeydown(e: KeyboardEvent, taskId: string) {
    if (e.key === 'Escape') {
      cancelEdit();
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      saveEdit(taskId);
    }
  }

  function autoResize(node: HTMLTextAreaElement) {
    function resize() {
      node.style.height = 'auto';
      node.style.height = node.scrollHeight + 'px';
    }
    resize();
    node.addEventListener('input', resize);
    return { destroy() { node.removeEventListener('input', resize); } };
  }
</script>

<div class="task-board">
  <div class="header">
    <h2>Tasks</h2>
    <div class="header-actions">
      <button class="btn-secondary" onclick={toggleDone}>
        {#if showDone}
          <ChevronUp size={14} />
          Hide Done
        {:else}
          <ChevronDown size={14} />
          Show Done
        {/if}
      </button>
      <button class="btn-primary" onclick={() => showAddForm = !showAddForm}>
        <Plus size={14} />
        Add Task
      </button>
    </div>
  </div>

  {#if showAddForm}
    <div class="add-form">
      <textarea
        bind:value={newTaskContent}
        placeholder="Task description..."
        rows="2"
        onkeydown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleAddTask())}
      ></textarea>
      <div class="add-form-actions">
        <select bind:value={newTaskPriority}>
          <option value="p0">P0 - Critical</option>
          <option value="p1">P1 - Normal</option>
          <option value="p2">P2 - Low</option>
        </select>
        <button class="btn-primary" onclick={handleAddTask} disabled={addingTask || !newTaskContent.trim()}>
          {addingTask ? 'Adding...' : 'Create Task'}
        </button>
        <button class="btn-secondary" onclick={() => showAddForm = false}>Cancel</button>
      </div>
    </div>
  {/if}

  {#if loading}
    <div class="loading">Loading tasks...</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if tasks.length === 0}
    <div class="empty">No tasks yet. Create one to get started.</div>
  {:else}
    <div class="columns">
      {#each columns as col}
        {@const colTasks = tasksByStatus(col.status)}
        {#if col.status !== 'done' || showDone}
          <div class="column">
            <div class="column-header">
              <span class="column-icon status-{col.status}">
                <svelte:component this={col.icon} size={16} />
              </span>
              <span class="column-label">{col.label}</span>
              <span class="column-count">{colTasks.length}</span>
            </div>
            <div
              role="list"
              class="column-body"
              class:drag-over={dragOverColumn === col.status}
              ondragover={(e) => handleDragOver(e, col.status)}
              ondragleave={(e) => handleDragLeave(e, e.currentTarget as HTMLElement)}
              ondrop={(e) => handleDrop(e, col.status)}
            >
              {#each colTasks as task (task.id)}
                <div
                  role="listitem"
                  class="task-card priority-border-{task.metadata?.priority || 'p1'}"
                  class:dragging={draggingTaskId === task.id}
                  class:editing={editingId === task.id}
                  draggable={editingId !== task.id}
                  ondragstart={(e) => editingId !== task.id && handleDragStart(e, task)}
                  ondragend={handleDragEnd}
                >
                  {#if task.metadata?.priority}
                    <span class="task-priority priority-{task.metadata.priority}">{task.metadata.priority}</span>
                  {/if}
                  {#if task.title}
                    <div class="task-title">{task.title}</div>
                  {/if}
                  {#if editingId === task.id}
                    <div class="task-edit">
                      <textarea
                        bind:value={editingContent}
                        class="edit-textarea"
                        onkeydown={(e) => handleEditKeydown(e, task.id)}
                        use:autoResize
                      ></textarea>
                      <div class="edit-actions">
                        <button class="edit-save" onclick={() => saveEdit(task.id)} disabled={savingId === task.id}>
                          {savingId === task.id ? 'Saving…' : 'Save'}
                        </button>
                        <button class="edit-cancel" onclick={cancelEdit}>Cancel</button>
                        <span class="edit-hint">⌘↵ to save · Esc to cancel</span>
                      </div>
                    </div>
                  {:else}
                    <div class="task-content-wrap" role="button" tabindex="0" onclick={() => startEdit(task)} onkeydown={(e) => e.key === 'Enter' && startEdit(task)}>
                      <div class="task-content">{task.content}</div>
                      <span class="edit-icon" title="Edit content"><Pencil size={11} /></span>
                    </div>
                  {/if}
                  {#if task.entity_ids.length > 0}
                    <div class="task-entities">
                      {#each task.entity_ids as entityId}
                        <span class="entity-tag">{entityId}</span>
                      {/each}
                    </div>
                  {/if}
                  {#if task.metadata?.blocked_reason}
                    <div class="blocked-reason">Blocked: {task.metadata.blocked_reason}</div>
                  {/if}
                  <div class="task-footer">
                    <span class="task-date">{formatDate(task.timestamp)}</span>
                    <div class="task-actions">
                      {#each getNextStatuses(task.metadata?.status || 'todo') as nextStatus}
                        <button
                          class="status-btn status-{nextStatus}"
                          onclick={() => handleStatusChange(task.id, nextStatus)}
                          title="Move to {nextStatus}"
                        >
                          <svelte:component this={columns.find(c => c.status === nextStatus)?.icon || Circle} size={12} />
                        </button>
                      {/each}
                    </div>
                  </div>
                </div>
              {/each}
              {#if colTasks.length === 0}
                <div class="column-empty">No tasks</div>
              {/if}
            </div>
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .task-board {
    max-width: 1200px;
    margin: 0 auto;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-xl);
  }

  h2 {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    color: var(--color-text);
  }

  .header-actions {
    display: flex;
    gap: var(--space-sm);
  }

  .btn-primary, .btn-secondary {
    display: inline-flex;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-md);
    font-size: var(--font-size-sm);
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-primary {
    background: var(--color-primary);
    color: white;
    border: 1px solid var(--color-primary);
  }

  .btn-primary:hover:not(:disabled) {
    opacity: 0.9;
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-secondary {
    background: var(--color-surface);
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
  }

  .btn-secondary:hover {
    background: var(--color-surface-hover);
  }

  .add-form {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    margin-bottom: var(--space-xl);
    box-shadow: var(--shadow-sm);
  }

  .add-form textarea {
    width: 100%;
    padding: var(--space-sm) var(--space-md);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font-size: var(--font-size-sm);
    resize: vertical;
    font-family: inherit;
  }

  .add-form textarea:focus {
    border-color: var(--color-primary);
    outline: none;
    box-shadow: 0 0 0 2px var(--color-primary-bg);
  }

  .add-form-actions {
    display: flex;
    gap: var(--space-sm);
    margin-top: var(--space-md);
    align-items: center;
  }

  .add-form-actions select {
    padding: var(--space-sm) var(--space-md);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--font-size-sm);
    color: var(--color-text);
  }

  .columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: var(--space-lg);
  }

  .column {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .column-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-md) var(--space-lg);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-surface);
  }

  .column-icon {
    display: flex;
    align-items: center;
  }

  .column-icon.status-todo { color: var(--color-zinc-500, #71717a); }
  .column-icon.status-in_progress { color: var(--color-blue); }
  .column-icon.status-done { color: var(--color-success); }
  .column-icon.status-blocked { color: var(--color-error, #dc2626); }

  .column-label {
    font-weight: 600;
    font-size: var(--font-size-sm);
    color: var(--color-text);
  }

  .column-count {
    margin-left: auto;
    font-size: var(--font-size-xs);
    font-weight: 600;
    background: var(--color-zinc-100, #f4f4f5);
    color: var(--color-text-secondary);
    padding: 2px 8px;
    border-radius: var(--radius-full);
  }

  :global([data-theme="dark"]) .column-count {
    background: var(--color-zinc-800, #27272a);
  }

  .column-body {
    padding: var(--space-md);
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
    min-height: 100px;
  }

  .task-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-md);
    box-shadow: var(--shadow-sm);
    transition: box-shadow 0.15s ease;
  }

  .task-card:hover {
    box-shadow: var(--shadow-md);
  }

  .priority-border-p0 { border-left: 3px solid var(--color-error, #dc2626); }
  .priority-border-p1 { border-left: 3px solid var(--color-warning, #f59e0b); }
  .priority-border-p2 { border-left: 3px solid var(--color-zinc-300, #d4d4d8); }

  .task-priority {
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: var(--radius-sm);
    text-transform: uppercase;
    margin-bottom: var(--space-xs);
  }

  .priority-p0 { background: var(--color-error-bg, #fee2e2); color: var(--color-error, #dc2626); }
  .priority-p1 { background: var(--color-warning-bg); color: var(--color-warning); }
  .priority-p2 { background: var(--color-zinc-100, #f4f4f5); color: var(--color-zinc-500, #71717a); }

  .task-title {
    font-weight: 600;
    font-size: var(--font-size-sm);
    color: var(--color-text);
    margin-bottom: var(--space-xs);
  }

  .task-content {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    line-height: 1.5;
    white-space: pre-wrap;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
  }

  .task-entities {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: var(--space-sm);
  }

  .entity-tag {
    padding: 2px 6px;
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    font-size: 10px;
    font-family: var(--font-mono);
    color: var(--color-text-muted);
    border: 1px solid var(--color-border);
  }

  .blocked-reason {
    margin-top: var(--space-sm);
    font-size: var(--font-size-xs);
    color: var(--color-error, #dc2626);
    font-style: italic;
  }

  .task-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--space-sm);
    padding-top: var(--space-sm);
    border-top: 1px solid var(--color-border);
  }

  .task-date {
    font-size: 10px;
    color: var(--color-text-muted);
    font-family: var(--font-mono);
  }

  .task-actions {
    display: flex;
    gap: 4px;
  }

  .status-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-border);
    background: var(--color-surface);
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .status-btn:hover {
    transform: scale(1.1);
  }

  .status-btn.status-todo { color: var(--color-zinc-500, #71717a); }
  .status-btn.status-todo:hover { background: var(--color-zinc-100, #f4f4f5); }
  .status-btn.status-in_progress { color: var(--color-blue); }
  .status-btn.status-in_progress:hover { background: var(--color-blue-bg); }
  .status-btn.status-done { color: var(--color-success); }
  .status-btn.status-done:hover { background: var(--color-success-bg); }
  .status-btn.status-blocked { color: var(--color-error, #dc2626); }
  .status-btn.status-blocked:hover { background: var(--color-error-bg, #fee2e2); }

  .column-empty {
    text-align: center;
    padding: var(--space-xl);
    color: var(--color-text-muted);
    font-size: var(--font-size-sm);
  }

  .column-body.drag-over {
    background: var(--color-primary-bg);
    border-radius: var(--radius-md);
    outline: 2px dashed var(--color-primary);
    outline-offset: -4px;
  }

  .task-card[draggable="true"] {
    cursor: grab;
  }

  .task-card[draggable="true"]:active {
    cursor: grabbing;
  }

  .task-card.dragging {
    opacity: 0.4;
  }

  .task-card.editing {
    cursor: default;
  }

  .task-content-wrap {
    position: relative;
    cursor: text;
    border-radius: var(--radius-sm);
    padding: 2px 4px;
    margin: -2px -4px;
    transition: background 0.15s ease;
  }

  .task-content-wrap:hover {
    background: var(--color-bg);
  }

  .edit-icon {
    position: absolute;
    top: 3px;
    right: 3px;
    opacity: 0;
    color: var(--color-text-muted);
    display: flex;
    align-items: center;
    pointer-events: none;
    transition: opacity 0.15s ease;
  }

  .task-content-wrap:hover .edit-icon {
    opacity: 1;
  }

  .task-edit {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .edit-textarea {
    width: 100%;
    min-height: 60px;
    padding: var(--space-xs) var(--space-sm);
    border: 1px solid var(--color-primary);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-text);
    font-size: var(--font-size-sm);
    font-family: inherit;
    line-height: 1.5;
    resize: none;
    box-shadow: 0 0 0 2px var(--color-primary-bg);
    box-sizing: border-box;
    overflow: hidden;
  }

  .edit-textarea:focus {
    outline: none;
  }

  .edit-actions {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    flex-wrap: wrap;
  }

  .edit-save {
    padding: 3px 10px;
    background: var(--color-primary);
    color: white;
    border: none;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    font-weight: 500;
    cursor: pointer;
    transition: opacity 0.15s ease;
  }

  .edit-save:hover:not(:disabled) {
    opacity: 0.9;
  }

  .edit-save:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .edit-cancel {
    padding: 3px 10px;
    background: transparent;
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .edit-cancel:hover {
    background: var(--color-surface-hover);
  }

  .edit-hint {
    font-size: 10px;
    color: var(--color-text-muted);
    margin-left: auto;
  }

  .loading,
  .error,
  .empty {
    padding: var(--space-2xl);
    text-align: center;
    color: var(--color-text-secondary);
    background: var(--color-surface);
    border-radius: var(--radius-lg);
    border: 1px solid var(--color-border);
  }

  .error {
    color: var(--color-error);
    background: var(--color-error-bg);
    border-color: var(--color-error);
  }
</style>
