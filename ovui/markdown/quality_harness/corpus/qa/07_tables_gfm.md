# GFM Tables

## Simple table

| Name  | Role    | Years |
|-------|---------|-------|
| Alice | Dev     | 5     |
| Bob   | Design  | 3     |
| Carol | PM      | 8     |

## Alignment

| Left aligned | Center aligned | Right aligned |
|:-------------|:--------------:|--------------:|
| L1           | C1             | R1            |
| L2           | C2             | R2            |
| Longer left  | Longer center  | Longer right  |

## Wide table

| Col A | Col B | Col C | Col D | Col E |
|-------|-------|-------|-------|-------|
| a1    | b1    | c1    | d1    | e1    |
| a2    | b2    | c2    | d2    | e2    |
| a3    | b3    | c3    | d3    | e3    |

## Inline formatting in cells

| Feature     | Style                  | Status     |
|-------------|------------------------|------------|
| **Bold**    | *italic*               | `code`     |
| ~~strike~~  | [link](https://ex.com) | **done**   |
| plain       | ***bold-italic***      | `inline()` |

## Wrapping cells

| Short | Long cell                                                           |
|-------|---------------------------------------------------------------------|
| A     | This cell contains text long enough that it should wrap across two or more visual lines inside the cell at standard width. |
| B     | Another wrapping cell, less aggressive, but still a mouthful.       |

## Empty cells

| A   | B   | C   |
|-----|-----|-----|
| a1  |     | c1  |
|     | b2  |     |
| a3  | b3  |     |

## Two-column table

| Key       | Value  |
|-----------|--------|
| alpha     | 1      |
| beta      | 22     |
| gamma     | 333    |
