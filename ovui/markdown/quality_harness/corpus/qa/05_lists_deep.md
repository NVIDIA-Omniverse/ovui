# Lists — Deep Nesting

## Unordered — three markers

* asterisk item 1
* asterisk item 2

- dash item 1
- dash item 2

+ plus item 1
+ plus item 2

## Ordered

1. One
2. Two
3. Three
4. Four

## Ordered starting at 5

5. Five
6. Six
7. Seven

## Nested three levels deep

- Level 0 item A
  - Level 1 item A.1
    - Level 2 item A.1.a
    - Level 2 item A.1.b
  - Level 1 item A.2
- Level 0 item B
  - Level 1 item B.1
- Level 0 item C

## Mixed ordered + unordered

1. Ordered outer
   - Unordered inner
     1. Ordered deepest
     2. Second deepest
   - Unordered inner two
2. Ordered outer second

## Task list

- [ ] Unchecked task
- [x] Checked task
- [ ] Another unchecked
- [X] Uppercase-X checked

## Task list with nesting

- [x] Parent task done
  - [x] Child task done
  - [ ] Child task pending
- [ ] Parent task pending

## List items with paragraphs

- Item with a single line.

- Item with multiple paragraphs. This first paragraph is a bit longer
  so that it wraps onto a second visual line and we can verify the
  continuation indent under the marker.

  Second paragraph inside the same list item. Should be indented to
  align with the first paragraph's text.

- Item after a multi-paragraph item.

## List items with code and quotes

- Item with `inline code` inline.

- Item containing a fenced block:

  ```
  code inside list item
  ```

- Item containing a block quote:

  > quoted content inside a list item
