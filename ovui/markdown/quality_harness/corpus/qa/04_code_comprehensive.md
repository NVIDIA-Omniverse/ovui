# Code Rendering

## Inline code

A sentence with `inline code` in the middle.

Inline code at the `start` of a sentence. And at the end `here`.

Back-to-back `one` `two` `three` tokens.

Inline code with punctuation: `foo()`, `bar;`, `baz.qux`.

## Fenced code block (no language)

```
plain fenced block
second line with   multiple    spaces   preserved
third line with tab\tseparator (literal backslash-t above)
```

## Fenced code block (python)

```python
def greet(name: str) -> str:
    """Return a friendly greeting."""
    if not name:
        return "Hello, world!"
    return f"Hello, {name}!"


class Widget:
    def __init__(self, text: str) -> None:
        self.text = text
```

## Fenced code block (json)

```json
{
  "name": "ovui-md-native",
  "version": "1.0.0",
  "features": ["headings", "lists", "tables"]
}
```

## Indented code block

    indented code line one
    indented code line two
    indented code line three with some longer content to stretch width

## Code inside a list

1. First step, then run:
   ```bash
   make build
   ```
2. Second step with `inline` code reference.

## Code inside a blockquote

> Quoted paragraph with a code reference: `quoted_code()`.
>
> ```
> fenced-inside-quote
> ```

## Long code line

```
this_is_an_intentionally_long_single_line_of_code_that_exceeds_the_available_width_to_verify_horizontal_overflow_handling_or_clipping_behaviour()
```
