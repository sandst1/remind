import { writable, derived } from 'svelte/store';
import type {
  Stats,
  Concept,
  Episode,
  Entity,
  DatabaseInfo,
  EntityGraphData,
  GraphData,
} from './types';

// Current database
export const currentDb = writable<string>('');
export const databases = writable<DatabaseInfo[]>([]);

// Stats
export const stats = writable<Stats | null>(null);
export const statsLoading = writable(false);
export const statsError = writable<string | null>(null);

// Concepts
export const concepts = writable<Concept[]>([]);
export const conceptsTotal = writable(0);
export const conceptsLoading = writable(false);
export const conceptsError = writable<string | null>(null);
export const selectedConceptId = writable<string | null>(null);
export const selectedConcept = writable<Concept | null>(null);
// Horizontal tree navigation - array of concepts forming the path
export const conceptPath = writable<Concept[]>([]);

// Episodes
export const episodes = writable<Episode[]>([]);
export const episodesTotal = writable(0);
export const episodesLoading = writable(false);
export const episodesError = writable<string | null>(null);

// Entities
export const entities = writable<Entity[]>([]);
export const entitiesTotal = writable(0);
export const entitiesLoading = writable(false);
export const entitiesError = writable<string | null>(null);

// Navigation
export type View = 'dashboard' | 'entities' | 'episodes' | 'concepts' | 'concept-map' | 'entity-graph';
export const currentView = writable<View>('dashboard');

// Concept Map (circle packing) visualization state
export const conceptMapData = writable<GraphData | null>(null);
export const conceptMapLoading = writable(false);
export const conceptMapError = writable<string | null>(null);

// Entity Graph (network) visualization state
export const entityGraphData = writable<EntityGraphData | null>(null);
export const entityGraphLoading = writable(false);
export const entityGraphError = writable<string | null>(null);

// Theme
export type Theme = 'system' | 'light' | 'dark';

const savedTheme = typeof localStorage !== 'undefined' ? localStorage.getItem('theme') as Theme : null;
export const theme = writable<Theme>(savedTheme || 'system');

if (typeof localStorage !== 'undefined') {
  theme.subscribe((val) => {
    localStorage.setItem('theme', val);
  });
}

// Derived stores
export const hasDatabase = derived(currentDb, ($db) => $db.length > 0);

export const isLoading = derived(
  [statsLoading, conceptsLoading, episodesLoading, entitiesLoading],
  ([$s, $c, $e, $ent]) => $s || $c || $e || $ent
);
