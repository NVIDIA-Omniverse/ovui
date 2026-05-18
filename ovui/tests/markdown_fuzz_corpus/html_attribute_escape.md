# Entity heavy

Named entities: &AElig; &OElig; &copy; &trade; &amp; &lt; &gt; &quot;.

Numeric decimal: &#35; &#97; &#8364; &#128512;.

Numeric hexadecimal: &#x22; &#x2F; &#x1F600; &#x1F680; &#xABCD;.

Invalid / unknown: &MadeUpEntity; &#; &#x; &zzz; &invalid&nbsp; trailing.

Zero-value numeric (should become U+FFFD): &#0; &#x0;.

Over-max codepoint (should become U+FFFD): &#x110000; &#1114112;.

Entities inside a link: [title](https://example.com?a=1&amp;b=2 "Title &copy;").

Entities inside an image alt: ![alt &copy; text](./missing.png "Image &trade;").
