# QA regression suite

`regress.py` opens the app in headless Chromium, runs every feature, records
what each one produces, and compares one build with another. It's run after
every release against the release before it, so nothing that worked stops
working.

```
pip install playwright        # uses Chromium
python3 qa/regress.py --base-ref v1.1 index.html          # this build vs the v1.1 tag
python3 qa/regress.py old.html new.html                   # any two files or URLs
python3 qa/regress.py index.html                          # one build, functional checks only
python3 qa/regress.py --base-ref v1.1 index.html --only songs.   # a subset
```

Each check ends up as one of:

| Result  | Meaning |
|---------|---------|
| `same`  | Same output as the base build. |
| `new`   | The base build doesn't have this feature. |
| `fixed` | The check raised an error on the base build and doesn't now. |
| `DIFF`  | Output changed. A regression unless it's intended, in which case pass `--allow <check>`. |
| `FAIL`  | The check threw, or the page logged an error while it ran. |

It exits 1 on any `DIFF` or `FAIL`. Full values go to `qa/out/results.json`
and screenshots of each tab, desktop and phone width, to
`qa/out/base/` and `qa/out/target/`.

## What it covers

- **Shell and layout**: title, tabs, no sideways scrolling at phone and
  desktop widths.
- **Scales**: every type × key × octaves × start × direction sequence, note
  groups, fingering and diagram for every note from low A to high F, the
  display (staff, big letter, caption, keys pressed), arrow keys and buttons,
  playback, mic follow mode with a skipped and a slurred note, Loop with the
  mic (run after run), saved settings.
- **Flashcards**: options, the note pool for every register/key/accidental
  combination, dealing 1–3 note cards (seeded, so it's repeatable), each
  card face, grading and the trouble-note list, mic mode (wrong note reveals,
  right note advances, multi-note cards), saved settings.
- **Songs**: the library, every piece and section rendered and fingerprinted
  shape by shape, playback, Space key, swing timing, Listen and score with a
  clean and a rough take, adding your own (typed or through the staff
  editor's paste), the parser's error message, reset and delete, and the staff
  editor itself (click to place, lengths, accidentals, rests, drag, keys,
  undo, play, save).
- **Progress**: proficiency maths and decay, the proficiency list in every
  sort order, practice log day/week/4-week/year views and navigation,
  streaks and the weekly goal, achievements, manual entry, the practice
  timer, export and import.
- **Sign-in and sync**: two devices syncing through a fake Firestore (no
  double counting, newest settings win, best scores kept), switching
  accounts, Firebase failing to load, the sign-in popup being closed,
  signing back in, and the embedded preview hiding sign-in and export.

Sign-in and sync run against the stand-in modules in `fake-firebase/`, so
the suite needs no network and never touches the real project.

Randomness is seeded and both builds run on the same day, so the same build
always produces the same values. When adding a feature, add a check for it
that returns `"n/a"` when the feature isn't there, so the comparison with the
previous release reports it as `new`.
