<script lang="ts">
  import {
    queryResult,
    queryLoading,
    queryError,
    currentDb,
    chatMessages,
    chatLoading,
    chatError,
    chatContext,
  } from '../lib/stores';
  import { executeQuery, streamChat } from '../lib/api';
  import type { ChatMessage } from '../lib/types';

  let queryText = '';
  let k = 5;
  let chatInput = '';
  let chatMessagesContainer: HTMLDivElement;
  let wasLoading = false;

  // Scroll to bottom once when assistant finishes responding
  $: {
    if (wasLoading && !$chatLoading && chatMessagesContainer) {
      setTimeout(() => {
        chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
      }, 0);
    }
    wasLoading = $chatLoading;
  }

  async function handleQuery() {
    if (!queryText.trim() || !$currentDb) return;

    queryLoading.set(true);
    queryError.set(null);
    queryResult.set(null);
    // Reset chat when starting a new query
    chatMessages.set([]);
    chatError.set(null);
    chatContext.set('');

    try {
      const result = await executeQuery(queryText, { k });
      queryResult.set(result);

      // Auto-answer: start chat with the query if we have results
      if (result.concepts.length > 0 && result.formatted) {
        chatContext.set(result.formatted);
        await sendChatMessage(queryText, true);
      }
    } catch (e) {
      queryError.set(e instanceof Error ? e.message : 'Query failed');
    } finally {
      queryLoading.set(false);
    }
  }

  async function sendChatMessage(message: string, isInitial = false) {
    if (!message.trim()) return;

    // Add user message
    const userMessage: ChatMessage = { role: 'user', content: message };
    chatMessages.update(msgs => [...msgs, userMessage]);

    if (!isInitial) {
      chatInput = '';
    }

    // Add empty assistant message for streaming
    const assistantMessage: ChatMessage = { role: 'assistant', content: '' };
    chatMessages.update(msgs => [...msgs, assistantMessage]);

    chatLoading.set(true);
    chatError.set(null);

    try {
      const allMessages = [...$chatMessages.slice(0, -1)]; // Exclude the empty assistant message
      await streamChat(
        allMessages,
        { context: $chatContext },
        (chunk) => {
          chatMessages.update(msgs => {
            const updated = [...msgs];
            const lastMsg = updated[updated.length - 1];
            if (lastMsg.role === 'assistant') {
              lastMsg.content += chunk;
            }
            return updated;
          });
        }
      );
    } catch (e) {
      chatError.set(e instanceof Error ? e.message : 'Chat failed');
      // Remove the empty assistant message on error
      chatMessages.update(msgs => {
        const last = msgs[msgs.length - 1];
        if (last.role === 'assistant' && !last.content) {
          return msgs.slice(0, -1);
        }
        return msgs;
      });
    } finally {
      chatLoading.set(false);
    }
  }

  function handleChatKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendChatMessage(chatInput);
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      handleQuery();
    }
  }

  function getConfidenceClass(confidence: number): string {
    if (confidence >= 0.7) return 'high';
    if (confidence >= 0.4) return 'medium';
    return 'low';
  }

  function formatActivation(activation: number): string {
    return activation.toFixed(2);
  }

  const relationTypeLabels: Record<string, string> = {
    implies: 'Implies',
    contradicts: 'Contradicts',
    specializes: 'Specializes',
    generalizes: 'Generalizes',
    causes: 'Causes',
    correlates: 'Correlates',
    part_of: 'Part of',
    context_of: 'Context of',
  };
</script>

<div class="query-interface" class:has-results={$queryResult && $queryResult.concepts.length > 0}>
  <div class="main-content">
    <div class="header">
      <h2>Query Memory</h2>
    </div>

    <div class="query-form">
      <div class="query-input-wrapper">
        <textarea
          class="query-input"
          bind:value={queryText}
          onkeydown={handleKeydown}
          placeholder="Ask a question about your memories...

Examples:
- What programming languages does the user prefer?
- How does the authentication system work?
- What decisions have been made about caching?"
          rows="4"
        ></textarea>
      </div>

      <div class="query-options">
        <div class="option">
          <label for="k-value">Results:</label>
          <input
            id="k-value"
            type="number"
            bind:value={k}
            min="1"
            max="20"
          />
        </div>

        <button
          class="query-button"
          onclick={handleQuery}
          disabled={$queryLoading || !queryText.trim()}
        >
          {$queryLoading ? 'Searching...' : 'Search'}
        </button>
      </div>

      <div class="shortcut-hint">
        Press <kbd>Cmd</kbd>+<kbd>Enter</kbd> to search
      </div>
    </div>

    {#if $queryError}
      <div class="error-message">{$queryError}</div>
    {/if}

    {#if $queryResult}
      <div class="results">
        <h3>Results ({$queryResult.concepts.length} concepts found)</h3>

        {#if $queryResult.concepts.length === 0}
          <div class="no-results">
            No relevant concepts found. Try a different query or check if the database has been consolidated.
          </div>
        {:else}
          <div class="concept-results">
            {#each $queryResult.concepts as result, i}
              <div class="result-item">
                <div class="result-header">
                  <span class="result-rank">#{i + 1}</span>
                  <span class="result-activation">
                    Activation: {formatActivation(result.activation)}
                  </span>
                  <span class="result-source source-{result.source}">
                    {result.source === 'embedding' ? 'Direct match' : `Via association (${result.hops} hop${result.hops > 1 ? 's' : ''})`}
                  </span>
                </div>

                <div class="result-body">
                  <div class="result-meta">
                    <span class="confidence confidence-{getConfidenceClass(result.concept.confidence)}">
                      {Math.round(result.concept.confidence * 100)}% confidence
                    </span>
                    <span class="instance-count">
                      {result.concept.instance_count} instance{result.concept.instance_count > 1 ? 's' : ''}
                    </span>
                  </div>

                  <div class="result-summary">{result.concept.summary}</div>

                  {#if result.concept.conditions}
                    <div class="result-conditions">
                      <strong>Applies when:</strong> {result.concept.conditions}
                    </div>
                  {/if}

                  {#if result.concept.exceptions.length > 0}
                    <div class="result-exceptions">
                      <strong>Exceptions:</strong>
                      <ul>
                        {#each result.concept.exceptions as exception}
                          <li>{exception}</li>
                        {/each}
                      </ul>
                    </div>
                  {/if}

                  {#if result.concept.relations.length > 0}
                    <div class="result-relations">
                      <strong>Related concepts:</strong>
                      <div class="relations-list">
                        {#each result.concept.relations.slice(0, 5) as rel}
                          <span class="relation-badge relation-{rel.type}">
                            {relationTypeLabels[rel.type]} → {rel.target_id}
                          </span>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  {#if result.concept.tags.length > 0}
                    <div class="result-tags">
                      {#each result.concept.tags as tag}
                        <span class="tag">{tag}</span>
                      {/each}
                    </div>
                  {/if}
                </div>
              </div>
            {/each}
          </div>

          {#if $queryResult.formatted}
            <details class="formatted-output">
              <summary>Formatted for LLM</summary>
              <pre>{$queryResult.formatted}</pre>
            </details>
          {/if}
        {/if}
      </div>
    {/if}
  </div>

  <!-- Chat Panel - appears when results are available -->
  {#if $queryResult && $queryResult.concepts.length > 0}
    <div class="chat-panel">
      <div class="chat-header">
        <h3>Chat</h3>
      </div>

      <div class="chat-messages" bind:this={chatMessagesContainer}>
        {#each $chatMessages as message}
          <div class="chat-message chat-message-{message.role}">
            <div class="chat-message-role">
              {message.role === 'user' ? 'You' : 'Assistant'}
            </div>
            <div class="chat-message-content">
              {message.content}{#if message.role === 'assistant' && $chatLoading && message === $chatMessages[$chatMessages.length - 1]}<span class="typing-cursor">|</span>{/if}
            </div>
          </div>
        {/each}

        {#if $chatError}
          <div class="chat-error">{$chatError}</div>
        {/if}
      </div>

      <div class="chat-input-area">
        <textarea
          class="chat-input"
          bind:value={chatInput}
          onkeydown={handleChatKeydown}
          placeholder="Ask a follow-up question..."
          rows="2"
          disabled={$chatLoading}
        ></textarea>
        <button
          class="chat-send-button"
          onclick={() => sendChatMessage(chatInput)}
          disabled={$chatLoading || !chatInput.trim()}
        >
          Send
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .query-interface {
    max-width: 900px;
  }

  .query-interface.has-results {
    display: grid;
    grid-template-columns: 1fr 380px;
    gap: var(--space-lg);
    max-width: 1400px;
  }

  .main-content {
    min-width: 0;
  }

  .header {
    margin-bottom: var(--space-lg);
  }

  h2 {
    font-size: var(--font-size-2xl);
  }

  .query-form {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    margin-bottom: var(--space-lg);
  }

  .query-input-wrapper {
    margin-bottom: var(--space-md);
  }

  .query-input {
    width: 100%;
    padding: var(--space-md);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    font-family: inherit;
    font-size: var(--font-size-base);
    resize: vertical;
    min-height: 100px;
  }

  .query-input:focus {
    outline: none;
    border-color: var(--color-primary);
  }

  .query-options {
    display: flex;
    align-items: center;
    gap: var(--space-lg);
  }

  .option {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }

  .option label {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .option input {
    width: 60px;
    padding: var(--space-xs) var(--space-sm);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
  }

  .query-button {
    padding: var(--space-sm) var(--space-xl);
    background: var(--color-primary);
    color: white;
    border: none;
    border-radius: var(--radius-md);
    font-weight: 500;
    cursor: pointer;
    margin-left: auto;
  }

  .query-button:hover:not(:disabled) {
    background: var(--color-primary-hover);
  }

  .query-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .shortcut-hint {
    margin-top: var(--space-sm);
    font-size: var(--font-size-xs);
    color: var(--color-text-muted);
  }

  kbd {
    padding: 2px 6px;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
  }

  .error-message {
    padding: var(--space-md);
    background: #ffeef0;
    border: 1px solid #ffc8cf;
    border-radius: var(--radius-md);
    color: #c00;
    margin-bottom: var(--space-lg);
  }

  .results h3 {
    margin-bottom: var(--space-md);
    font-size: var(--font-size-lg);
  }

  .no-results {
    padding: var(--space-xl);
    text-align: center;
    color: var(--color-text-muted);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
  }

  .concept-results {
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
  }

  .result-item {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .result-header {
    display: flex;
    align-items: center;
    gap: var(--space-md);
    padding: var(--space-sm) var(--space-md);
    background: var(--color-bg);
    border-bottom: 1px solid var(--color-border);
    font-size: var(--font-size-sm);
  }

  .result-rank {
    font-weight: 600;
    color: var(--color-primary);
  }

  .result-activation {
    font-family: var(--font-mono);
    color: var(--color-text-secondary);
  }

  .result-source {
    margin-left: auto;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
  }

  .source-embedding {
    background: #e3f2fd;
    color: #1565c0;
  }

  .source-spread {
    background: #f3e5f5;
    color: #7b1fa2;
  }

  .result-body {
    padding: var(--space-md);
  }

  .result-meta {
    display: flex;
    gap: var(--space-md);
    margin-bottom: var(--space-sm);
    font-size: var(--font-size-sm);
  }

  .confidence {
    font-weight: 500;
  }

  .confidence-high { color: var(--color-confidence-high); }
  .confidence-medium { color: var(--color-confidence-medium); }
  .confidence-low { color: var(--color-confidence-low); }

  .instance-count {
    color: var(--color-text-muted);
  }

  .result-summary {
    font-size: var(--font-size-base);
    line-height: 1.6;
    margin-bottom: var(--space-md);
  }

  .result-conditions,
  .result-exceptions {
    margin-bottom: var(--space-sm);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .result-conditions strong,
  .result-exceptions strong {
    color: var(--color-text);
  }

  .result-exceptions ul {
    margin: var(--space-xs) 0 0 var(--space-lg);
    padding: 0;
  }

  .result-relations {
    margin-top: var(--space-md);
    font-size: var(--font-size-sm);
  }

  .relations-list {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    margin-top: var(--space-xs);
  }

  .relation-badge {
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    background: var(--color-bg);
    border-left: 3px solid;
  }

  .relation-implies { border-color: var(--color-implies); }
  .relation-contradicts { border-color: var(--color-contradicts); }
  .relation-specializes { border-color: var(--color-specializes); }
  .relation-generalizes { border-color: var(--color-generalizes); }
  .relation-causes { border-color: var(--color-causes); }
  .relation-correlates { border-color: var(--color-correlates); }
  .relation-part_of { border-color: var(--color-part-of); }
  .relation-context_of { border-color: var(--color-context-of); }

  .result-tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    margin-top: var(--space-md);
  }

  .tag {
    padding: 2px 8px;
    background: var(--color-border);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .formatted-output {
    margin-top: var(--space-xl);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
  }

  .formatted-output summary {
    padding: var(--space-md);
    cursor: pointer;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    user-select: none;
  }

  .formatted-output summary:hover {
    color: var(--color-text);
  }

  .formatted-output pre {
    margin: 0;
    padding: var(--space-md);
    background: var(--color-bg);
    border-radius: 0 0 var(--radius-lg) var(--radius-lg);
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* Chat Panel Styles */
  .chat-panel {
    display: flex;
    flex-direction: column;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    height: calc(100vh - 120px);
    position: sticky;
    top: var(--space-lg);
  }

  .chat-header {
    padding: var(--space-md);
    border-bottom: 1px solid var(--color-border);
  }

  .chat-header h3 {
    margin: 0;
    font-size: var(--font-size-lg);
  }

  .chat-messages {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--space-md);
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
  }

  .chat-message {
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-md);
  }

  .chat-message-user {
    background: var(--color-primary);
    color: white;
    margin-left: var(--space-xl);
  }

  .chat-message-assistant {
    background: var(--color-bg);
    margin-right: var(--space-xl);
  }

  .chat-message-role {
    font-size: var(--font-size-xs);
    font-weight: 600;
    margin-bottom: var(--space-xs);
    opacity: 0.8;
  }

  .chat-message-content {
    font-size: var(--font-size-sm);
    line-height: 1.6;
    white-space: pre-wrap;
  }

  .typing-cursor {
    animation: blink 1s step-end infinite;
  }

  @keyframes blink {
    50% { opacity: 0; }
  }

  .chat-error {
    padding: var(--space-sm) var(--space-md);
    background: #ffeef0;
    border: 1px solid #ffc8cf;
    border-radius: var(--radius-md);
    color: #c00;
    font-size: var(--font-size-sm);
  }

  .chat-input-area {
    padding: var(--space-md);
    border-top: 1px solid var(--color-border);
    display: flex;
    gap: var(--space-sm);
    align-items: flex-end;
  }

  .chat-input {
    flex: 1;
    padding: var(--space-sm);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    font-family: inherit;
    font-size: var(--font-size-sm);
    resize: none;
    min-height: 40px;
    max-height: 120px;
  }

  .chat-input:focus {
    outline: none;
    border-color: var(--color-primary);
  }

  .chat-input:disabled {
    opacity: 0.6;
    background: var(--color-bg);
  }

  .chat-send-button {
    padding: var(--space-sm) var(--space-md);
    background: var(--color-primary);
    color: white;
    border: none;
    border-radius: var(--radius-md);
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
  }

  .chat-send-button:hover:not(:disabled) {
    background: var(--color-primary-hover);
  }

  .chat-send-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  /* Responsive: stack on smaller screens */
  @media (max-width: 1024px) {
    .query-interface.has-results {
      grid-template-columns: 1fr;
    }

    .chat-panel {
      position: relative;
      top: 0;
      height: 500px;
    }
  }
</style>
