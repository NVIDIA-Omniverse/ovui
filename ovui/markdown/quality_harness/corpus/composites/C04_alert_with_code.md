> [!WARNING]
> Running the migration on a replica before the primary can cause split-brain. Always run on the primary first:
>
> ```bash
> psql -h primary.db.internal -U admin -f migrations/0042_up.sql
> ```
>
> Wait for replication to catch up, **then** run the replica step.

An alert block containing a nested code fence and emphasis should preserve the alert's accent color, icon, and left border on every line.
