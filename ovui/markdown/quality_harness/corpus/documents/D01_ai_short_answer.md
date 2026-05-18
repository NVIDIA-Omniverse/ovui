The difference between `let` and `const` in JavaScript comes down to reassignment, not immutability.

- **`let`** declares a variable whose binding can be reassigned later.
- **`const`** declares a variable whose binding is fixed after initialization.

Crucially, `const` does **not** freeze the value itself — only the binding:

```javascript
const user = { name: "Ada" };
user.name = "Grace";   // allowed: mutating the object
user = { name: "Bob" }; // TypeError: Assignment to constant variable
```

Use `const` by default and reach for `let` only when you genuinely need to rebind. For true immutability, use `Object.freeze()` or a library like Immer.
