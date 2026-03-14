# Memory Decay

Remind implements usage-based memory decay: concepts that are rarely recalled gradually lose retrieval priority. Like how human memory fades for things you don't think about.

## How it works

1. **Decay passes** — Every N recalls (`decay_interval`, default 20), all concepts have their `decay_factor` reduced by `decay_rate` (default 0.1)

2. **Retrieval impact** — `decay_factor` multiplies the retrieval activation score. A concept with `decay_factor: 0.5` needs twice the raw activation to rank as high as one with `decay_factor: 1.0`.

3. **Rejuvenation** — When a concept is recalled, it gets a boost proportional to how strongly it matched the query. Useful knowledge stays accessible.

4. **Grace window** — Concepts recalled in the last 60 seconds are protected from the current decay pass. Active knowledge is never immediately penalized.

## Configuration

```json
{
  "decay": {
    "enabled": true,
    "decay_interval": 20,
    "decay_rate": 0.1
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Set `false` to disable decay entirely |
| `decay_interval` | `20` | Number of recalls between decay passes |
| `decay_rate` | `0.1` | How much `decay_factor` drops per interval (0.0–1.0) |

## Monitoring

```bash
remind stats
```

Shows: decay enabled/disabled, recall count, next decay pass, average and minimum decay factors across all concepts.

## Design rationale

Without decay, the concept graph grows monotonically — old concepts compete equally with fresh ones for retrieval slots. Decay ensures that knowledge which isn't being used gradually recedes, keeping retrieval results focused on currently relevant concepts.

The rejuvenation mechanism prevents useful but infrequently-queried concepts from disappearing entirely. If you recall a faded concept, it bounces back.
