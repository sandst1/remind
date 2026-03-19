

"Error code: 400 - {'error': {'message': "Unsupported value: 'temperature' does not support 0.3 with this model. Only the default (1) value is supported.", 'type': 'invalid_request_error', 'param': 'temperature', 'code': 'unsupported_value'}}" <- gpt-5 / 5-mini



---


Here's my thinking on this:

How many concepts per recall: 5 is too many for most queries

The default k=5 in retrieve() and default_recall_k=5 feels high, especially for pointed questions like "who hates Romeo?" where ideally 1-2 highly relevant concepts would suffice, and the rest is noise. The problem compounds because each concept also dumps all its source episodes and relations, making the output massively long.

Looking at the example output:

Montague-Capulet feud - somewhat relevant (feud = hate), but vague
Distraction fails for unrequited love - not relevant at all
Secrecy and deception - not relevant
Authority response to public violence - tangentially relevant
Feud escalates from servants to citizens - tangentially relevant
Only concept #1 is arguably useful, and even it doesn't directly answer "who hates Romeo?" (the answer is Tybalt specifically, plus the Capulets generally).

Two distinct problems here:

k is too high / no quality floor - There's no minimum activation threshold for returning results. The retriever returns the top-k regardless of how weak they are. A concept with activation 0.15 shouldn't be surfaced alongside one at 0.8. The activation_threshold at 0.1 is only used during spreading, not as a floor for the final results.

Concept granularity - This is more of a consolidation issue. The concepts are too thematic/abstract. "Who hates Romeo?" is a factual question that should be answerable from episodes or from more granular concepts like "Tybalt hates Romeo for attending the Capulet ball." The consolidation process over-generalizes, losing the specifics that would directly answer factual queries.

Suggestions:

Lower default k to 3 - For most recall use cases (LLM context injection), 3 relevant concepts is a sweet spot. 5 creates too much noise, especially with all the episode/relation metadata.

Add an activation floor - Don't return concepts below a minimum activation score (e.g., 0.3) even if we haven't hit k yet. Better to return 1 great result than 5 mediocre ones. Something like:

# In retrieve(), after sorting:
results = [r for r in results if r.activation >= min_activation]
return results[:k]
Cap source episodes in output - Each concept currently dumps all source episodes. For a concept built from 17 episodes (like "Secrecy and deception"), that's enormous. Capping to 3-5 most relevant source episodes per concept would tighten the output dramatically.

Consider a factual query path - For short, specific questions, the spreading activation + concept retrieval might not be the right strategy at all. A direct entity lookup ("Romeo" -> episodes mentioning Romeo -> filter for "hate/enemy/feud") could be more precise. This could be detected heuristically or via an LLM classifier on the query.

Want me to implement any of these? I'd probably start with lowering k to 3, adding an activation floor, and capping source episodes in format_for_llm -- those three alone would dramatically tighten the output.