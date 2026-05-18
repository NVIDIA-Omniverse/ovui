# Connection pooling strategies in PostgreSQL

Connection pooling sits between your application and Postgres to reuse expensive TCP + authentication handshakes. This note compares the three dominant approaches and when to pick each.

## Why you need a pool

Every new Postgres connection forks a backend process (~2–10 MB RSS) and runs through authentication. Without pooling, a burst of short-lived requests can exhaust `max_connections` within seconds.

> [!IMPORTANT]
> `max_connections` is a hard cap. Once reached, *every* new connection fails until an existing one closes — including admin sessions.

## Three common patterns

### 1. Application-side pool (e.g., HikariCP, SQLAlchemy)

Lives inside your app process. Fast, language-native, but one pool per process — N app replicas means N pools.

### 2. Session-level proxy (PgBouncer `session` mode)

One backend per client session. Safe for everything Postgres supports, including prepared statements and `LISTEN`/`NOTIFY`.

### 3. Transaction-level proxy (PgBouncer `transaction` mode)

Backends are handed out per *transaction*. Dramatically higher multiplexing, but breaks features that rely on session state.

## Comparison

| Strategy              | Max concurrency | Prepared stmts | `LISTEN/NOTIFY` | `SET LOCAL` |
| --------------------- | --------------- | -------------- | --------------- | ----------- |
| App-side (HikariCP)   | Low–Medium      | ✅              | ✅               | ✅           |
| PgBouncer `session`   | Medium          | ✅              | ✅               | ✅           |
| PgBouncer `transaction` | **High**      | ⚠️ protocol-aware | ❌            | ⚠️ per-tx    |

## Worked example

A Rails app serving 5 000 req/s with 50 app workers and a 2-connection-per-worker pool:

```ruby
# config/database.yml
production:
  adapter: postgresql
  pool: 2
  prepared_statements: false  # required for pgbouncer transaction mode
  advisory_locks: false
```

Place PgBouncer in `transaction` mode in front of Postgres, sized to `2 × workers × replicas`. With five replicas, that's `2 × 50 × 5 = 500` client connections fan-ing into ~50 real backends.

## Rules of thumb

- [x] Start with an application-side pool. It's simplest and correct.
- [x] Add PgBouncer `session` mode when you outgrow a single process.
- [ ] Move to `transaction` mode only after you've audited every feature your ORM uses.
- [ ] **Never** enable `transaction` mode without disabling prepared statements at the driver level — subtle, silent bugs follow.

---

**Further reading:** the [PgBouncer docs](https://www.pgbouncer.org/) are the canonical source; [Citus's write-up](https://www.citusdata.com/blog/) on pooling at scale is the clearest second opinion.
