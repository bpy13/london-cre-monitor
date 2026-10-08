# merge-in/

Drop data from another installation here before merging it into this one. Everything in
this folder except this README is **git-ignored**, so colleagues' data is never committed.

Put each source in its own sub-folder:

```
merge-in/
  colleague-jane/
    data/        metrics.sqlite, conversations.sqlite, checkpoints.sqlite
    reports/     optional - their briefs
  codespace-2026-10/
    data/
```

Then, with the app stopped:

```bash
cre-monitor merge merge-in/colleague-jane --dry-run   # preview, changes nothing
cre-monitor merge merge-in/colleague-jane             # preview, confirm, merge
```

The source is only read, never modified. Once a merge has succeeded you can delete its
sub-folder; re-merging the same data later is harmless either way.
See [docs/USAGE.md → Merging installations](../docs/USAGE.md#merging-installations).
