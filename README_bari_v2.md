# Bari Practice

A single-page practice tool for E♭ baritone saxophone with a low A key.
All notation is at written pitch, in treble clef.

No build step, no dependencies, no server code. One HTML file.

## Running it

**Hosted (recommended).** Put `index.html` in a repository and turn on
GitHub Pages under Settings → Pages → Deploy from a branch → `main` / root.
Pages serves over HTTPS, which the microphone features require.

**Locally.** Browsers restrict microphone access on `file://` pages, so serve
it over localhost instead of double-clicking the file:

```
python3 -m http.server 8000
```

Then open `http://localhost:8000/`.

## What's in it

**Scales & arpeggios** — major, natural and harmonic minor, chromatic, blues,
pentatonic, and major/minor/dominant-7th arpeggios in all twelve keys, one or
two octaves. Up-and-back note groups of 2, 3 or 4. Playback with a tempo
slider, count-in, metronome and loop. Fingering diagram and large note letter
follow the current note.

**Note flashcards** — staff, note name and fingering as independently
toggleable faces. One, two or three notes per card, picked close together so
groups read like real fragments. Filter by register and by key. Missed notes
resurface more often.

**Songs** — six original blues and jazz études, fully notated, with per-phrase
coaching, swing playback, a tempo ladder and note-by-note mic scoring. Add
your own pieces with a compact text notation (`G4:1 Bb4:0.5 B4:0.5 D5:2`,
one bar per line).

**Progress** — proficiency per scale, piece and individual note, built from
microphone sessions. Scores are a weighted running average, held back until
you have a few reps, and faded for time since last practice. All-time best is
tracked alongside.

## Microphone

Pitch detection uses the YIN algorithm over the Web Audio API, entirely on
device. Nothing is recorded, stored or transmitted. The browser will ask for
permission the first time a listening feature is switched on.

If the prompt never appears, the page is most likely being served over
`file://`, or the browser is blocked at the OS level (on macOS: System
Settings → Privacy & Security → Microphone).

## Data

Practice history, scores and preferences live in `localStorage`, so they are
per browser and per origin. A locally served copy and a hosted copy keep
separate histories.

## Notes on the music

The six pieces are original compositions written for this tool, so the
notation, the fingerings and the practice plans are all free to use and modify.

## Licence

Do what you like with it.
