# style/reports/ - example reports for the house style

Put reports whose **writing style, layout and techniques** the brief should imitate here
(`.md`, `.txt`, `.html`, `.pdf` - up to 8 are read, the first ~6,000 characters of each).
Everything in this folder except this README is **git-ignored**: examples are often licensed
broker documents and must not be committed.

```bash
cre-monitor style learn          # analyse the examples -> style/profile.json (+ profile.md to review)
cre-monitor style show           # see what was learned
cre-monitor brief                # briefs now follow the house style
cre-monitor brief --no-style     # ...unless switched off (or REPORT_STYLE=0)
cre-monitor style clear          # back to the built-in style
```

What gets imitated: voice and tone, section order and headings, headline and paragraph
style, number conventions (e.g. "£190 psf", "bp"), and signature techniques. What never
changes: the facts - figures come only from the agent's research, and a guard rejects any
restyled text that alters or invents a number. The profile *describes* the style; it does
not copy text from the examples.

Check the licence of a report before using it here (some publishers prohibit use of their
reports with AI tools).
