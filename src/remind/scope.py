"""Request-local label constraints, including graph expansion and rendering."""

from copy import deepcopy
from typing import Any

from remind.store import cosine_similarity


class FilteredStore:
    def __init__(self, store: Any, labels: dict[str, str], as_of=None):
        self.base, self.labels = store, labels
        self.as_of = as_of.replace(tzinfo=None) if as_of else None
        self.fact_sources = {f.source_episode_id: f for f in store.get_all_facts()}

    def __getattr__(self, name: str):
        return getattr(self.base, name)

    def matches(self, episode: Any) -> bool:
        if episode is None or not all(value in episode.labels.get(key, []) for key, value in self.labels.items()):
            return False
        fact = self.fact_sources.get(episode.id)
        if fact is not None:
            if self.as_of is None:
                return fact.is_active
            return fact.valid_from.replace(tzinfo=None) <= self.as_of and (
                fact.valid_to is None or self.as_of < fact.valid_to.replace(tzinfo=None))
        return self.as_of is None or getattr(episode, "created_at").replace(tzinfo=None) <= self.as_of

    def fact_allowed(self, fact: Any) -> bool:
        if fact is None:
            return False
        if not self.labels:
            return True
        episode = self.base.get_episode(fact.source_episode_id, include_deleted=True)
        return episode is not None and all(value in episode.labels.get(key, []) for key, value in self.labels.items())

    def concept_allowed(self, concept: Any) -> bool:
        if concept is None:
            return False
        if concept.concept_type in {"fact_cluster", "fact"}:
            return any(self.fact_allowed(f) for f in self.base.get_facts(cluster_id=concept.id,
                active_only=self.as_of is None, as_of=self.as_of))
        return self.matches(concept)

    def clean(self, concept: Any):
        if not self.concept_allowed(concept):
            return None
        concept = deepcopy(concept)
        if not self.labels:
            return concept
        concept.source_episodes = [i for i in concept.source_episodes if self.matches(self.base.get_episode(i))]
        concept.entity_ids = sorted({i for ep in self.base.get_episodes_batch(concept.source_episodes) for i in ep.entity_ids})
        concept.evidence = []  # Unattributed quote caches cannot be scoped safely.
        concept.specifics = [f.statement for f in self.get_facts(cluster_id=concept.id, active_only=True)]
        concept.relations = [r for r in concept.relations if self.concept_allowed(self.base.get_concept(r.target_id))]
        return concept

    def get_concept(self, identifier, **kwargs):
        return self.clean(self.base.get_concept(identifier, **kwargs))

    def get_episode(self, identifier, **kwargs):
        episode = self.base.get_episode(identifier, **kwargs)
        return episode if self.matches(episode) else None

    def get_episodes_batch(self, identifiers):
        return [e for e in self.base.get_episodes_batch(identifiers) if self.matches(e)]

    def get_episodes_mentioning(self, identifier, limit=50):
        return [e for e in self.base.get_episodes_mentioning(identifier, limit=1000000)
                if self.matches(e)][:limit]

    def get_facts(self, **kwargs):
        return [f for f in self.base.get_facts(**kwargs) if self.fact_allowed(f)]

    def get_fact(self, identifier):
        fact = self.base.get_fact(identifier)
        return fact if self.fact_allowed(fact) else None

    def get_concepts_for_entity(self, identifier, **kwargs):
        return [clean for c in self.base.get_concepts_for_entity(identifier, **kwargs)
                if (clean := self.clean(c)) is not None]

    def get_related(self, *args, **kwargs):
        return [(clean, relation) for c, relation in self.base.get_related(*args, **kwargs)
                if (clean := self.clean(c)) is not None]

    def get_incoming_relations(self, *args, **kwargs):
        return [(clean, relation) for c, relation in self.base.get_incoming_relations(*args, **kwargs)
                if (clean := self.clean(c)) is not None]

    def get_conflicts(self, **kwargs):
        return [c for c in self.base.get_conflicts(**kwargs)
                if all(self.get_fact(i) is not None for i in (c.fact_a_id, c.fact_b_id) if i)
                and all(self.get_concept(i) is not None for i in c.concept_ids)]

    def find_by_embedding(self, embedding, k=5, labels=None):
        candidates = {c.id: (self.clean(c), score) for c, score in
                      self.base.find_by_embedding(embedding, k=k, labels=self.labels)
                      if self.concept_allowed(c)}
        # Fact clusters inherit eligibility from matching source episodes.
        for fact in self.base.get_all_facts():
            valid = fact.is_active if self.as_of is None else (
                fact.valid_from.replace(tzinfo=None) <= self.as_of and
                (fact.valid_to is None or self.as_of < fact.valid_to.replace(tzinfo=None)))
            if fact.embedding and fact.cluster_id and valid and self.fact_allowed(fact):
                score = cosine_similarity(embedding, fact.embedding)
                if fact.cluster_id not in candidates or score > candidates[fact.cluster_id][1]:
                    cluster = self.get_concept(fact.cluster_id)
                    if cluster:
                        candidates[cluster.id] = (cluster, score)
        return sorted(candidates.values(), key=lambda item: item[1], reverse=True)[:k]

    def search_concepts_lexical(self, query, k=5, labels=None):
        return [(clean, score) for c, score in self.base.search_concepts_lexical(query, k=k, labels=self.labels)
                if (clean := self.clean(c)) is not None]

    def find_episodes_by_embedding(self, embedding, k=5, labels=None):
        return self.base.find_episodes_by_embedding(embedding, k=k, labels=self.labels)

    def search_episodes_lexical(self, query, k=5, labels=None):
        return self.base.search_episodes_lexical(query, k=k, labels=self.labels)
