import { Eye, CheckCircle, HelpCircle, Info, Heart, Trophy, FileText } from 'lucide-svelte';

export const DEFAULT_EPISODE_TYPES_LIST = ['observation', 'decision', 'question', 'meta', 'preference', 'outcome', 'fact'];
const icons = { observation: Eye, decision: CheckCircle, question: HelpCircle, meta: Info, preference: Heart, outcome: Trophy, fact: FileText };
const colors: Record<string, string> = { observation: '#3b82f6', decision: '#8b5cf6', question: '#f59e0b', meta: '#71717a', preference: '#ec4899', outcome: '#22c55e', fact: '#14b8a6' };

export function getTypeLabel(type: string): string {
  return type.replaceAll('_', ' ').replace(/^./, character => character.toUpperCase());
}
export function getTypePluralLabel(type: string): string {
  return `${getTypeLabel(type)}s`;
}
export function getTypeIcon(type: string) {
  return icons[type as keyof typeof icons] || FileText;
}
export function getTypeColor(type: string): string {
  return colors[type] || '#71717a';
}
export function isCustomEpisodeTypesProfile(types: string[]): boolean {
  return types.length !== DEFAULT_EPISODE_TYPES_LIST.length || types.some(type => !DEFAULT_EPISODE_TYPES_LIST.includes(type));
}
