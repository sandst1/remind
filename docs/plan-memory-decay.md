# Memory Decay Plan

## Overview

Implement a memory decay mechanism that dynamically adjusts concept prominence based on access patterns, similar to human memory consolidation where frequently recalled memories become more accessible while unused memories fade into the background.

**Key principle**: This is not about deleting memories, but about creating a dynamic "priority" system that surfaces frequently accessed concepts while keeping older, less-used concepts available but lower in the retrieval ranking.

---

## Design Goals

1. **Preserve all memories**: No data loss, all episodes and concepts remain intact
2. **Dynamic relevance**: Concepts accessed more recently/frequently rise in retrieval priority
3. **Gradual decay**: Smooth decay curve, not binary "active/inactive"
4. **Transparent**: Users can see decay scores and understand retrieval ordering
5. **Configurable**: Decay parameters should be tunable via config

---

## Core Concepts

### Decay Score

Each concept will have a **decay score** (0.0 - 1.0) that represents its current prominence:

- **High decay score (0.8-1.0)**: Frequently accessed, recently used, highly relevant
- **Medium decay score (0.4-0.8)**: Moderately accessed, some recency
- **Low decay score (0.0-0.4)**: Rarely accessed, old, low priority

The decay score is **computed dynamically** based on:
- Access frequency (how often retrieved)
- Recency (when last accessed)
- Confidence (original concept confidence) - **independent factor**
- Instance count (number of supporting episodes)

**Important**: Confidence and decay are separate. A concept can have high confidence (reliable) but low decay (not currently relevant), or vice versa.

### Access Tracking

Track accesses for **both** final retrieved concepts AND all concepts reaching activation threshold:
- **Final concepts** (top-k): Full access logging with query hash
- **Threshold concepts** (activation > threshold): Logged for decay computation but not persisted to query history

This gives us:
1. Accurate decay scores (all threshold accesses count)
2. Query analytics (which concepts come up for which queries)

---

## Data Model Changes

### 1. Add to `Concept` model (`models.py`)

```python
@dataclass
class Concept:
    # ... existing fields ...
    
    # Decay tracking
    decay_score: float = 1.0  # 0.0-1.0, computed dynamically (not stored)
    last_accessed: Optional[datetime] = None  # Last time retrieved
    access_count: int = 0  # Total number of retrievals
    access_history: list[tuple[datetime, float]] = field(default_factory=list)  
    # (timestamp, activation_level) pairs for recent accesses (last 100)
```

**Storage implications**:
- `decay_score`: **NOT stored** - computed on-the-fly during retrieval
- `last_accessed`: Stored, updated after each retrieval
- `access_count`: Stored, incremented on each retrieval
- `access_history`: Truncated to last 100 entries, stored as JSON array

### 2. Add retrieval metrics (`retrieval.py`)

```python
@dataclass
class RetrievalMetrics:
    """Metrics for a retrieval operation."""
    
    query: str
    timestamp: datetime = field(default_factory=datetime.now)
    concepts_retrieved: int = 0
    avg_activation: float = 0.0
    concept_accesses: list[str] = field(default_factory=list)  # concept IDs accessed
```

### 3. Add access log table (`store.py`)

```sql
CREATE TABLE retrieval_access_log (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    accessed_at TIMESTAMP NOT NULL,
    activation_level REAL NOT NULL,
    query_hash TEXT NOT NULL,  -- for grouping similar queries
    FOREIGN KEY (concept_id) REFERENCES concepts(id)
);
```

---

## Decay Algorithm

### Formula

```
decay_score = (recency_factor × 0.4) + (frequency_factor × 0.4) + (confidence_boost × 0.2)

where:
  recency_factor = 1 / (1 + days_since_access / decay_half_life)
  
  frequency_factor = min(access_count / frequency_threshold, 1.0)
  
  confidence_boost = base_concept_confidence × 0.5
```

### Parameters (configurable)

```python
@dataclass
class DecayConfig:
    decay_half_life: float = 30.0  # days for recency to halve
    frequency_threshold: int = 10  # accesses to reach max frequency score
    max_access_history: int = 100  # keep last N access records
    min_access_weight: float = 0.1  # minimum weight for any access
```

### Update Logic

After each retrieval:

1. **Increment access_count** for all retrieved concepts
2. **Update last_accessed** to current timestamp
3. **Append to access_history** with activation level
4. **Truncate access_history** to `max_access_history` entries
5. **Persist changes** to store

---

## Integration Points

### 1. Store Layer (`store.py`)

Add methods:

```python
def record_concept_access(
    self, 
    concept_id: str, 
    activation: float, 
    query_hash: str
) -> None:
    """Record that a concept was accessed via retrieval."""
    
def get_concept_access_stats(self, concept_id: str) -> dict:
    """Get access statistics for a concept."""
    
def get_recent_accesses(self, limit: int = 100) -> list[dict]:
    """Get recent retrieval accesses for monitoring."""
```

### 2. Retrieval Layer (`retrieval.py`)

Modify `MemoryRetriever.retrieve()`:

```python
async def retrieve(...) -> list[ActivatedConcept]:
    # ... existing retrieval logic ...
    
    # After computing activations:
    results = []
    for activated_concept in computed_results:
        concept = activated_concept.concept
        
        # Record access
        self.store.record_concept_access(
            concept_id=concept.id,
            activation=activated_concept.activation,
            query_hash=self._compute_query_hash(query)
        )
        
        # Compute decay score
        decay_score = self._compute_decay_score(concept)
        
        # Combine activation with decay for final ranking
        final_score = (
            activated_concept.activation * 0.7 +  # 70% retrieval relevance
            decay_score * 0.3                        # 30% popularity/recency
        )
        
        results.append(ActivatedConcept(
            concept=concept,
            activation=final_score,  # reuse activation field for final score
            source=activated_concept.source,
            hops=activated_concept.hops,
            decay_score=decay_score,
        ))
    
    return results[:k]
```

### 3. Interface Layer (`interface.py`)

Update public API:

```python
class MemoryInterface:
    async def recall(self, query: str, **kwargs) -> list[ActivatedConcept]:
        """
        Recall relevant concepts.
        
        Returns ActivatedConcept objects with:
        - concept: The Concept object
        - activation: Final ranked score (combines retrieval + decay)
        - decay_score: Separate decay component for transparency
        - source: "embedding" or "spread"
        - hops: Number of hops from initial match
        """
```

---

## API & CLI Extensions

### New CLI commands

```bash
# View decay stats for a concept
remind decay inspect <concept_id>

# Reset decay for a concept (force it to top)
remind decay reset <concept_id>

# View recent access patterns
remind decay recent --limit 20

# Configure decay parameters
remind decay config --half-life 45 --frequency-threshold 15
```

### New REST API endpoints

```http
GET  /api/v1/concepts/<id>/decay      # Get decay stats for concept
PUT  /api/v1/concepts/<id>/decay/reset # Reset decay score
GET  /api/v1/decay/recent             # Recent access patterns
GET  /api/v1/decay/config             # Current decay config
PUT  /api/v1/decay/config             # Update decay config
```

### MCP tools

```python
@tool
def get_decay_stats(concept_id: str) -> dict:
    """Get decay score and access statistics for a concept."""

@tool
def reset_decay(concept_id: str) -> dict:
    """Reset decay score to maximum for a concept."""

@tool
def get_recent_accesses(limit: int = 20) -> list[dict]:
    """Get recent memory access patterns."""
```

---

## Configuration

Add to `RemindConfig` in `config.py`:

```python
@dataclass
class DecayConfig:
    enabled: bool = True
    decay_half_life: float = 30.0  # days
    frequency_threshold: int = 10
    access_weighting: str = "exponential"  # "exponential" or "linear"
    min_decay_score: float = 0.1  # never go below this

@dataclass
class RemindConfig:
    # ... existing fields ...
    decay: DecayConfig = field(default_factory=DecayConfig)
```

**Config file example**:

```json
{
  "decay": {
    "enabled": true,
    "decay_half_life": 30,
    "frequency_threshold": 10,
    "access_weighting": "exponential",
    "min_decay_score": 0.1
  }
}
```

---

## Migration Strategy

### Phase 1: Data Model & Storage (Week 1)

1. Add fields to `Concept` dataclass
2. Add `retrieval_access_log` table to schema
3. Implement `record_concept_access()` and related store methods
4. Add migration script for existing databases

### Phase 2: Decay Computation (Week 1-2)

1. Implement `_compute_decay_score()` algorithm
2. Add access tracking to `retrieve()` method
3. Integrate decay into ranking formula
4. Add unit tests for decay calculation

### Phase 3: API & CLI (Week 2)

1. Add CLI commands for decay inspection
2. Add REST API endpoints
3. Add MCP tools
4. Update docs/AGENTS.md with new tools

### Phase 4: UI & Monitoring (Week 2-3)

1. Add decay score display to web UI concept view
2. Add access history visualization
3. Add decay config panel
4. Add export functionality for access logs

### Phase 5: Tuning & Optimization (Week 3)

1. Performance testing with large concept graphs
2. Parameter tuning based on real usage
3. Add decay metrics to `/api/v1/stats`
4. Documentation refinement

---

## Testing Strategy

### Unit Tests

```python
# tests/test_decay.py

def test_decay_score_computation():
    """Test decay score formula with various access patterns."""
    
def test_recency_decay():
    """Test that older accesses decay faster."""
    
def test_frequency_capping():
    """Test that frequency_score caps at 1.0."""
    
def test_access_tracking_persistence():
    """Test that access counts persist across retrieval."""
```

### Integration Tests

```python
async def test_retrieval_includes_decay():
    """Test that retrieval ranking incorporates decay scores."""
    
async def test_access_logging():
    """Test that concept accesses are logged correctly."""
```

---

## Performance Considerations

### Concerns

1. **Query overhead**: Computing decay for all retrieved concepts
2. **Storage bloat**: Access history could grow large
3. **Write amplification**: Recording every access adds writes

### Mitigations

1. **Lazy computation**: Only compute decay for top-k results
2. **History truncation**: Limit `access_history` to 100 entries
3. **Batch logging**: Optionally batch access logs (config option)
4. **Caching**: Cache decay scores in memory for rapid retrieval

### Optimization Options

```python
# Config option for batch logging
"decay": {
  "batch_logging": true,
  "batch_size": 10,
  "batch_interval_ms": 1000
}
```

---

## User Experience

### Transparency

Users should understand **why** concepts appear in certain orders:

1. Show decay score in concept cards (web UI)
2. Display "last accessed" timestamp
3. Show access count (e.g., "Accessed 12 times")
4. Provide decay reset option for important concepts

### Control

- **Auto-decay**: Enabled by default
- **Manual boost**: Users can reset decay on important concepts
- **Configurable**: Advanced users can tune decay parameters
- **Disabled mode**: Option to disable decay entirely (for testing)

---

## Implementation Decisions

### Confirmed Choices

1. **Initial decay score**: New concepts start at 1.0 (fresh and relevant)

2. **Confidence vs. decay**: Independent factors
   - Confidence: How reliable/trustworthy is this concept?
   - Decay: How frequently/recently accessed is this concept?
   - Both factors contribute separately to final ranking

3. **Access tracking scope**: Track both threshold and final concepts
   - Threshold concepts: Count for decay computation
   - Final concepts: Persisted to query access log for analytics

4. **Decay for episodes**: No - only concepts track decay

5. **Decay for relations**: No - relations are structural

6. **Reset behavior**: Sets `decay_score = 1.0`, resets `access_count = 0`, keeps `last_accessed`

7. **UI scope**: Out of scope for initial implementation - focus on core functionality first

---

## Implementation Tasks

### Phase 1: Data Model & Storage (Core Foundation)

#### Task 1.1: Update Concept model (`src/remind/models.py`)
- Add `last_accessed: Optional[datetime] = None`
- Add `access_count: int = 0`
- Add `access_history: list[tuple[datetime, float]] = field(default_factory=list)`
- Update `to_dict()` and `from_dict()` to serialize/deserialize new fields
- **Story**: As a developer, I can store and retrieve concept access tracking data

#### Task 1.2: Add retrieval access log table (`src/remind/store.py`)
- Add `retrieval_access_log` table schema
- Implement `record_concept_access()` method
- Implement `get_concept_access_stats()` method
- Implement migration for existing databases
- **Story**: As a system, I can log concept accesses for decay computation

#### Task 1.3: Add decay configuration (`src/remind/config.py`)
- Add `DecayConfig` dataclass with fields:
  - `enabled: bool = True`
  - `decay_half_life: float = 30.0` (days)
  - `frequency_threshold: int = 10`
  - `min_decay_score: float = 0.1`
- Integrate into `RemindConfig`
- **Story**: As a power user, I can configure decay behavior

### Phase 2: Decay Computation Engine

#### Task 2.1: Implement decay score computation (`src/remind/retrieval.py`)
- Create `_compute_decay_score()` method in `MemoryRetriever`
- Implement formula: `decay_score = (recency × 0.4) + (frequency × 0.4) + (confidence × 0.2)`
- Add helper methods for recency factor and frequency factor
- Write unit tests for edge cases
- **Story**: As a retriever, I can compute decay scores for concepts

#### Task 2.2: Integrate access tracking into retrieval
- Modify `retrieve()` to record accesses for threshold concepts
- Update concept `last_accessed`, `access_count`, `access_history` after retrieval
- Truncate `access_history` to max 100 entries
- **Story**: As a retrieval system, I track concept accesses automatically

### Phase 3: Ranking & Integration

#### Task 3.1: Update retrieval ranking
- Modify final ranking to combine: `final_score = (activation × 0.7) + (decay_score × 0.3)`
- Update `ActivatedConcept` to include `decay_score` field
- Ensure backward compatibility with existing callers
- **Story**: As a user, I see concepts ranked by both relevance and recency

#### Task 3.2: Update interface layer
- Modify `MemoryInterface.recall()` to return updated `ActivatedConcept` objects
- Add documentation for new fields
- **Story**: As an API consumer, I get decay-aware retrieval results

### Phase 4: CLI & API Exposed

#### Task 4.1: Add CLI commands (`src/remind/cli.py`)
- `remind decay inspect <concept_id>` - show decay stats
- `remind decay reset <concept_id>` - reset decay to 1.0
- `remind decay recent --limit N` - show recent accesses
- `remind decay config` - show current config
- **Story**: As a user, I can inspect and manage decay

#### Task 4.2: Add REST API endpoints (`src/remind/api/routes.py`)
- `GET /api/v1/concepts/<id>/decay` - decay stats
- `PUT /api/v1/concepts/<id>/decay/reset` - reset decay
- `GET /api/v1/decay/recent` - recent accesses
- `GET /api/v1/decay/config` - current config
- **Story**: As a web client, I can access decay data via REST

#### Task 4.3: Add MCP tools (`src/remind/mcp_server.py`)
- `get_decay_stats(concept_id)` - inspect decay
- `reset_decay(concept_id)` - boost concept
- `get_recent_accesses(limit)` - view access patterns
- **Story**: As an LLM agent, I can query decay stats

### Phase 5: Testing & Validation

#### Task 5.1: Unit tests
- `tests/test_decay.py`: decay score computation
- `tests/test_decay.py`: recency decay curve
- `tests/test_decay.py`: frequency capping
- `tests/test_decay.py`: access tracking persistence
- **Story**: As a developer, I can verify decay logic

#### Task 5.2: Integration tests
- Test retrieval includes decay in ranking
- Test access logging on retrieval
- Test CLI commands work end-to-end
- Test API endpoints return correct data
- **Story**: As a tester, I can verify end-to-end decay functionality

---

## Success Metrics

1. **Correctness**: Decay scores match expected values for known access patterns
2. **Performance**: Retrieval latency increase < 10ms on average
3. **Persistence**: Access counts survive restarts
4. **Transparency**: CLI/API show clear decay statistics
5. **Control**: Users can reset decay on important concepts

---

## Related Concepts

- **Ebbinghaus forgetting curve**: Human memory decay over time
- **PageRank**: Link analysis algorithm (access = votes)
- **LRU cache**: Least recently used eviction (similar recency tracking)
- **TF-IDF**: Term frequency-inverse document frequency (frequency weighting)