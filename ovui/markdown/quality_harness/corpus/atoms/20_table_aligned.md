A table with per-column alignment:

| Component   | Latency (ms) | Throughput (req/s) | Notes                |
| :---------- | -----------: | -----------------: | :------------------- |
| Gateway     |          1.2 |             12 300 | p99 latency          |
| Auth        |          4.7 |              8 200 | JWT validation       |
| Renderer    |          8.9 |              4 100 | GPU-bound            |
| Persistence |         22.4 |              1 600 | Redis write-through  |
