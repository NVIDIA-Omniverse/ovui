# Building a Distributed Vector Index in Rust

A production design note covering the whole stack — from the WAL write
path to the cross-shard query planner — for a million-QPS approximate
nearest-neighbour service. The same engine that powers the **Atlas**
recommendation pipeline.

> [!IMPORTANT]
> This document assumes familiarity with HNSW graphs and Raft replication.
> If you're new to either, start with the [original HNSW paper][hnsw] and
> the [Raft thesis][raft].

[hnsw]: https://arxiv.org/abs/1603.09320
[raft]: https://raft.github.io/raft.pdf

## Goals

- **Latency:** p99 query under **8 ms** at 256-d, 1 B vectors, top-50 recall ≥ 0.95.
- **Throughput:** 1.0 M QPS sustained; 1.6 M QPS burst.
- **Durability:** RPO = 0, RTO ≤ 30 s on single-AZ failure.
- **Cost:** ≤ $0.50 per million queries amortised.

## Mathematical core

Cosine similarity over normalised vectors $u, v \in \mathbb{R}^{256}$:

$$
\operatorname{sim}(u, v) = \frac{u \cdot v}{\lVert u \rVert \, \lVert v \rVert}
$$

Recall@k against an exact index $E$ with returned set $R_k$:

$$
\operatorname{recall@k} = \frac{1}{|Q|} \sum_{q \in Q} \frac{|R_k(q) \cap E_k(q)|}{k}
$$

Memory budget per shard, assuming HNSW with degree $M = 32$ and float-16
storage, follows $\text{bytes}(N) = N \cdot (256 \cdot 2 + 4M)$, so a
**128 M-vector** shard fits in roughly 80 GiB.

## Architecture

| Layer        | Component         | Language | Replication        |
| :----------- | :---------------- | :------- | :----------------- |
| Edge         | Query router      | Rust     | Anycast, stateless |
| Coordinator  | Plan / fan-out    | Rust     | Raft (5 nodes)     |
| Shard        | HNSW + filters    | Rust     | Raft (3 nodes)     |
| Storage      | WAL + segments    | —        | S3 + local NVMe    |
| Control      | Schema, balancer  | Go       | Raft (3 nodes)     |

### Why Rust on the data path

1. ✅ Zero-cost abstractions land on tight inner loops.
2. ✅ Predictable memory (no GC pauses during candidate expansion).
3. ✅ `unsafe` is opt-in and auditable per crate.
4. ⚠️  Compile times bite us in CI — we ship `cargo-chef` warm caches.

## Hot path: query execution

```rust
pub async fn query(
    &self,
    req: QueryRequest,
) -> Result<QueryResponse, QueryError> {
    let plan = self.planner.plan(&req).await?;          // 0.2 ms
    let mut candidates = Vec::with_capacity(plan.k * 4);

    for shard in plan.shards {
        let partial = shard
            .search(req.vector(), plan.k_per_shard, plan.filter())
            .await?;                                    // 1.5–4 ms
        candidates.extend(partial);
    }

    candidates.sort_unstable_by(|a, b| b.score.total_cmp(&a.score));
    candidates.truncate(req.k);
    Ok(QueryResponse::from_top(candidates))             // 0.05 ms
}
```

The shard `search` itself is the hottest function in the codebase. Its
canonical microbenchmark — `ann_search/256d_M32_ef64` — must stay under
**3.5 ms p95** on a `c7gn.4xlarge` node. We gate every PR on this.

```python
# bench harness — runs on every CI commit
import subprocess

CMD = ["cargo", "bench", "--bench", "ann", "--",
       "--baseline", "main", "--save-baseline", "pr"]

def main() -> int:
    out = subprocess.run(CMD, check=True, capture_output=True, text=True)
    p95 = parse_p95(out.stdout)
    if p95 > 3.5:
        print(f"❌  regression: p95 = {p95:.2f} ms (limit 3.5 ms)")
        return 1
    print(f"✅  ok: p95 = {p95:.2f} ms")
    return 0
```

## Operator surface

### Commands every on-call should know

> [!TIP]
> All commands respect `--dry-run`. Use it. Always. The control plane
> records every mutation in the audit log regardless.

- `atlas shard inspect <shard-id>` — graph stats, segment list, pending
  compactions, last successful snapshot.
- `atlas shard rebalance` — moves replicas to honour the placement
  constraint set in `atlas/policy.yaml`.
- `atlas index reseed --from <s3-uri>` — bulk-loads a frozen index dump;
  required after a schema-incompatible upgrade.
- `atlas query trace <trace-id>` — replays the plan, per-shard timings,
  and final candidate set. The single best debugging tool we have.

### Dashboards

- 📈 **Latency** — `grafana/atlas/latency` (p50 / p95 / p99 by region).
- 🧠 **Recall** — `grafana/atlas/recall` (oracle-shadow comparison job).
- 💾 **Storage** — `grafana/atlas/storage` (segment-age histogram).
- 🔥 **Hot keys** — `grafana/atlas/hotkeys` (top-N queried vectors).

## Failure modes we have observed

> [!WARNING]
> Section is appended after every retro. If you hit a new mode, file a
> PR — even a one-liner is enough to start the conversation.

1. **Slow-shard skew.** A single shard with elevated GC pressure
   poisons every fan-out. Mitigation: per-shard hedged requests at
   `t = p50 + 1 ms`, capped at one hedge.
2. **Filter cardinality explosion.** A query with a high-cardinality
   pre-filter (`tenant_id IN (...)` with ~10 K values) blows out the
   inner loop. Mitigation: planner falls back to exact scan above
   1 K candidates.
3. **WAL rotation stall.** Old NVMe firmware caused 250 ms hiccups
   on segment seal. Mitigation: rotate at half-full instead of
   full, and pin firmware via the boot config.

## Roll-out plan

| Phase | Date       | Traffic | Gate                                |
| ----- | :--------- | ------: | :---------------------------------- |
| α     | 2026-05-04 |    1 %  | recall ≥ 0.93, p99 ≤ 12 ms          |
| β     | 2026-05-18 |   10 %  | recall ≥ 0.94, p99 ≤ 10 ms          |
| GA    | 2026-06-01 |  100 %  | recall ≥ 0.95, p99 ≤ 8 ms, DR drill |

## Outcome

> [!NOTE]
> The first α slice flipped on **2026-05-04** at 14:07 UTC. p99 landed
> at **6.8 ms** with recall **0.961** — well inside the gate. We're
> proceeding to β a week early.

For the architecture context that led to these choices, see the
[design doc][design] and the [post-mortem][pm] from the v1 outage that
shaped most of the failure-mode list.

[design]: https://atlas.example.com/design/v2
[pm]: https://atlas.example.com/pm/2026-03-incident
