# Paragraphs and Line Breaks

A short paragraph.

A second paragraph separated by a blank line. Paragraphs should have
visible vertical spacing between them so the reader can easily tell
where one ends and the next begins.

This is a longer paragraph that exists specifically to test word-wrap
behaviour at the target width. When a paragraph exceeds one visual
line, the renderer must break on whitespace, carry styling across
breaks, and indent wrapped lines to the same left margin as the first
line. Long continuous prose like this one verifies all of that in one
go — the paragraph extends long enough that at a standard width it
should wrap at least three or four times.

Hard line breaks with trailing spaces below  
Line two after two-space hard break  
Line three after another two-space hard break

Hard line breaks with trailing backslash below\
Line two after backslash hard break\
Line three after another backslash hard break

Soft break folding test below
where this line should flow into the previous line
rather than starting a new paragraph.

Single.

Word.

Paragraphs.

A final paragraph with an extremely long unbroken token like
supercalifragilisticexpialidocious mixed with normal prose to check
that the wrapper still behaves reasonably when long and short tokens
appear in the same paragraph.
