# style/reports/ - the reference report library

Reports you supply live here (`.md`, `.txt`, `.html`, `.pdf`). Everything in this folder except
this README is **git-ignored**: reports are often licensed broker documents and must not be
committed. Manage them in the web UI (**📚 Reference reports** tab) or by copying files here.

Each report can serve two purposes. Tick them in the UI library; they're stored in
`style/library.json`, and new files default to *style example*:

| Role | What it does |
|---|---|
| **Style example** | The **house style** imitates its voice, layout, number conventions and techniques (up to 8 files, first ~6,000 characters each) |
| **Benchmark** | The **performance check** measures the agent against the figures and themes it states ([docs/EVALUATION.md](../../docs/EVALUATION.md)) |

```bash
cre-monitor style learn          # analyse the style examples -> style/profile.json (+ profile.md to review)
cre-monitor style show           # see what was learned
cre-monitor brief                # briefs now follow the house style
cre-monitor brief --no-style     # ...unless switched off (or REPORT_STYLE=0)
cre-monitor style clear          # back to the built-in style

cre-monitor --live bench key FILE --accept-safe   # answer key for a benchmark report (moderate in the UI)
cre-monitor --live bench run FILE                 # can the agent find those figures? (designed for < $1)
cre-monitor --live bench judge FILE               # how does the latest brief compare?
```

What the house style never changes: the facts. Figures come only from the agent's research,
and a guard rejects any restyled text that alters or invents a number. The profile and answer
keys *describe* the reports; they never copy their text.

Check the licence of a report before using it here: some publishers (e.g. Knight Frank)
prohibit use of their reports with AI tools.
