// Types matching Python models.py

export type RelationType =
  | 'implies'
  | 'contradicts'
  | 'specializes'
  | 'generalizes'
  | 'causes'
  | 'correlates'
  | 'part_of'
  | 'context_of';

export type EpisodeType =
  | 'observation'
  | 'decision'
  | 'question'
  | 'meta'
  | 'preference';

export type EntityType =
  | 'file'
  | 'function'
  | 'class'
  | 'module'
  | 'concept'
  | 'subject'
  | 'person'
  | 'project'
  | 'tool'
  | 'other';

export interface Relation {
  type: RelationType;
  target_id: string;
  strength: number;
  context: string | null;
  target_summary?: string; // Added for graph view
}

export interface SourceEpisodeData {
  id: string;
  title?: string;
  content: string;
  type: EpisodeType;
}

export interface Concept {
  id: string;
  title?: string;
  summary: string;
  confidence: number;
  instance_count: number;
  created_at: string;
  updated_at: string;
  relations: Relation[];
  source_episodes: string[];
  source_episodes_data?: SourceEpisodeData[];  // Added for concept detail view
  conditions: string | null;
  exceptions: string[];
  tags: string[];
  // Decay tracking
  decay_factor: number;
  access_count: number;
  last_accessed: string | null;
}

export interface Episode {
  id: string;
  timestamp: string;
  title?: string;
  content: string;
  episode_type: EpisodeType;
  summary: string | null;
  concepts_activated: string[];
  entity_ids: string[];
  consolidated: boolean;
  entities_extracted: boolean;
  confidence: number;
}

export interface Entity {
  id: string;
  type: EntityType;
  display_name: string | null;
  created_at: string;
  mention_count?: number;
  relations?: EntityRelation[];
}

export interface EntityRelation {
  source_id: string;
  target_id: string;
  relation_type: string;  // Free-form string (e.g., "manages", "imports", "authored")
  strength: number;
  context: string | null;
  source_episode_id: string | null;
  created_at: string;
  // Enriched by API
  direction?: 'incoming' | 'outgoing';
  related_entity?: Entity;
}

// API response types

export interface Stats {
  concepts: number;
  episodes: number;
  entities: number;
  relations: number;
  entity_relations: number;
  mentions: number;
  unconsolidated_episodes: number;
  unextracted_episodes: number;
  episode_types: Record<EpisodeType, number>;
  relation_types: Record<RelationType, number>;
  entity_relation_types: Record<string, number>;
  entity_types: Record<EntityType, number>;
  // Decay stats
  concepts_with_decay?: number;
  avg_decay_factor?: number;
  min_decay_factor?: number;
}

export interface GraphNode {
  id: string;
  title?: string;
  summary: string;
  confidence: number;
  instance_count: number;
  conditions: string[];
  exceptions: string[];
  tags: string[];
  source_episodes: Array<{
    id: string;
    title?: string;
    content: string;
    type: EpisodeType;
  }>;
  relations: Array<Relation & { target_summary?: string }>;
  // D3 simulation properties
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

export interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  type: RelationType;
  strength: number;
  context: string | null;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

// Entity Graph types for network visualization
export interface EntityGraphNode {
  id: string;
  type: EntityType;
  display_name: string | null;
  mention_count: number;
  // D3 simulation properties
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

export interface EntityGraphLink {
  source: string | EntityGraphNode;
  target: string | EntityGraphNode;
  type: string;
  strength: number;
  context: string | null;
}

export interface EntityGraphData {
  nodes: EntityGraphNode[];
  links: EntityGraphLink[];
}

export interface QueryResult {
  concepts: Array<{
    concept: Concept;
    activation: number;
    source: 'embedding' | 'spread';
    hops: number;
  }>;
  formatted: string;
}

export interface DatabaseInfo {
  name: string;
  path: string;
}

// Chat types

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatStreamChunk {
  chunk?: string;
  done?: boolean;
  error?: string;
}
