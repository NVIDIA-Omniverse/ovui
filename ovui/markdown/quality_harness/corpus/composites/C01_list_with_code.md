To debug a failing test:

1. Reproduce locally with the same seed:

   ```bash
   pytest tests/ -k failing_test --seed 42 -v
   ```

2. Add a breakpoint at the assertion site:

   ```python
   import pdb; pdb.set_trace()
   ```

3. Inspect the captured state and compare against the expected value.

4. If the diff is cosmetic, update the snapshot:

   ```bash
   pytest tests/ --snapshot-update
   ```

Each nested code block should preserve list alignment and not break the numbering rhythm.
