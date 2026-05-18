A short Python example:

```python
def fibonacci(n: int) -> int:
    """Return the n-th Fibonacci number."""
    if n < 2:
        return n
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b


print(fibonacci(10))  # 55
```

The same logic in TypeScript:

```typescript
function fibonacci(n: number): number {
  if (n < 2) return n;
  let [a, b] = [0, 1];
  for (let i = 0; i < n - 1; i++) {
    [a, b] = [b, a + b];
  }
  return b;
}

console.log(fibonacci(10)); // 55
```
