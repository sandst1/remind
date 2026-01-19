import type {
  Stats,
  Concept,
  Episode,
  Entity,
  GraphData,
  EntityGraphData,
  QueryResult,
  DatabaseInfo,
  EpisodeType,
  EntityType,
  ChatMessage,
  ChatStreamChunk,
} from './types';

const API_BASE = '/api/v1';

/**
 * Get the database name from URL query params
 */
export function getDbParam(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get('db') || '';
}

/**
 * Build URL with db param
 */
function apiUrl(path: string, params: Record<string, string> = {}): string {
  const db = getDbParam();
  const allParams = new URLSearchParams({ db, ...params });
  return `${API_BASE}${path}?${allParams.toString()}`;
}

/**
 * Fetch wrapper with error handling
 */
async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(error.error || `HTTP ${response.status}`);
  }

  return response.json();
}

// Stats

export async function fetchStats(): Promise<Stats> {
  return fetchJson<Stats>(apiUrl('/stats'));
}

// Concepts

export interface FetchConceptsOptions {
  offset?: number;
  limit?: number;
  search?: string;
}

export interface ConceptsResponse {
  concepts: Concept[];
  total: number;
}

export async function fetchConcepts(options: FetchConceptsOptions = {}): Promise<ConceptsResponse> {
  const params: Record<string, string> = {};
  if (options.offset !== undefined) params.offset = String(options.offset);
  if (options.limit !== undefined) params.limit = String(options.limit);
  if (options.search) params.search = options.search;
  return fetchJson<ConceptsResponse>(apiUrl('/concepts', params));
}

export async function fetchConcept(id: string): Promise<Concept> {
  return fetchJson<Concept>(apiUrl(`/concepts/${id}`));
}

// Episodes

export interface FetchEpisodesOptions {
  offset?: number;
  limit?: number;
  type?: EpisodeType;
  consolidated?: boolean;
  start_date?: string;
  end_date?: string;
  search?: string;
}

export interface EpisodesResponse {
  episodes: Episode[];
  total: number;
}

export async function fetchEpisodes(options: FetchEpisodesOptions = {}): Promise<EpisodesResponse> {
  const params: Record<string, string> = {};
  if (options.offset !== undefined) params.offset = String(options.offset);
  if (options.limit !== undefined) params.limit = String(options.limit);
  if (options.type) params.type = options.type;
  if (options.consolidated !== undefined) params.consolidated = String(options.consolidated);
  if (options.start_date) params.start_date = options.start_date;
  if (options.end_date) params.end_date = options.end_date;
  if (options.search) params.search = options.search;
  return fetchJson<EpisodesResponse>(apiUrl('/episodes', params));
}

export async function fetchEpisode(id: string): Promise<Episode> {
  return fetchJson<Episode>(apiUrl(`/episodes/${id}`));
}

// Entities

export interface FetchEntitiesOptions {
  type?: EntityType;
}

export interface EntitiesResponse {
  entities: Entity[];
  total: number;
}

export async function fetchEntities(options: FetchEntitiesOptions = {}): Promise<EntitiesResponse> {
  const params: Record<string, string> = {};
  if (options.type) params.type = options.type;
  return fetchJson<EntitiesResponse>(apiUrl('/entities', params));
}

export async function fetchEntity(id: string): Promise<Entity> {
  return fetchJson<Entity>(apiUrl(`/entities/${encodeURIComponent(id)}`));
}

export interface EntityEpisodesResponse {
  episodes: Episode[];
}

export async function fetchEntityEpisodes(id: string, limit: number = 50): Promise<EntityEpisodesResponse> {
  return fetchJson<EntityEpisodesResponse>(
    apiUrl(`/entities/${encodeURIComponent(id)}/episodes`, { limit: String(limit) })
  );
}

export interface EntityConceptsResponse {
  concepts: Concept[];
}

export async function fetchEntityConcepts(id: string, limit: number = 50): Promise<EntityConceptsResponse> {
  return fetchJson<EntityConceptsResponse>(
    apiUrl(`/entities/${encodeURIComponent(id)}/concepts`, { limit: String(limit) })
  );
}

// Graph

export async function fetchGraph(): Promise<GraphData> {
  return fetchJson<GraphData>(apiUrl('/graph'));
}

export async function fetchEntityGraph(): Promise<EntityGraphData> {
  return fetchJson<EntityGraphData>(apiUrl('/entity-graph'));
}

// Query

export interface QueryOptions {
  k?: number;
}

export async function executeQuery(query: string, options: QueryOptions = {}): Promise<QueryResult> {
  return fetchJson<QueryResult>(apiUrl('/query'), {
    method: 'POST',
    body: JSON.stringify({ query, k: options.k ?? 5 }),
  });
}

// Databases

export async function fetchDatabases(): Promise<DatabaseInfo[]> {
  const response = await fetchJson<{ databases: DatabaseInfo[] }>(`${API_BASE}/databases`);
  return response.databases;
}

// Chat

export interface ChatOptions {
  context?: string;
}

/**
 * Stream a chat response from the LLM
 * @param messages - Chat history
 * @param options - Optional context (formatted memory)
 * @param onChunk - Callback for each text chunk
 * @returns Promise that resolves when streaming is complete
 */
export async function streamChat(
  messages: ChatMessage[],
  options: ChatOptions = {},
  onChunk: (chunk: string) => void
): Promise<void> {
  const db = getDbParam();
  const url = `${API_BASE}/chat?db=${encodeURIComponent(db)}`;

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      messages,
      context: options.context || '',
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(error.error || `HTTP ${response.status}`);
  }

  if (!response.body) {
    throw new Error('No response body');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Process SSE events
    const lines = buffer.split('\n');
    buffer = lines.pop() || ''; // Keep incomplete line in buffer

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        try {
          const parsed: ChatStreamChunk = JSON.parse(data);
          if (parsed.error) {
            throw new Error(parsed.error);
          }
          if (parsed.chunk) {
            onChunk(parsed.chunk);
          }
          if (parsed.done) {
            return;
          }
        } catch (e) {
          // Skip non-JSON lines
          if (data.trim()) {
            console.warn('Failed to parse SSE data:', data);
          }
        }
      }
    }
  }
}
