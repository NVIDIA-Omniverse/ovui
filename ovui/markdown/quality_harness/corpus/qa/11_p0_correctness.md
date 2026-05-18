# P0 Markdown Correctness

This fixture tracks correctness details that are easy to regress while the
native renderer grows toward full CommonMark and GFM coverage.

## Entities

Named: &amp; &lt; &gt; &quot; &apos; &copy; &reg; &trade; &mdash; &hellip;.

Extended named: &AElig; &frac34; &ClockwiseContourIntegral; &ngE;.

Numeric: &#35; &#1234; &#x22; &#xD06; &#xcab; &#0;.

Unknown named entities must remain literal: &MadeUpEntity;.

Entities inside code stay literal: `&copy; &#35; &amp;`.

## Titles And Attributes

[A titled link](https://example.com/path?a=1&amp;b=2 "Link title &copy; 2026")
should decode the URL and title attributes.

![Local icon alt &copy;](../../examples/test_icon_32.png "Image title &trade;")

## Rich Table Cells

| Feature | Cell content |
|:---|:---|
| Inline styles | **bold**, *italic*, ~~strike~~, and `code` |
| Link | [table link](https://example.com/table?a=1&amp;b=2 "Table link &copy;") with wrapped text |
| Image | ![icon &copy;](../../examples/test_icon_32.png "Table image &trade;") next to text |

## Raw HTML Policy

Inline HTML remains visible as source: <kbd>Ctrl</kbd> + <span data-x="1">K</span>.

<div class="note">
  <strong>HTML block source should render visibly.</strong>
</div>

