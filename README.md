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

**Progress** — a weekly goal (days per week, and how many minutes make a day
count), day and week streaks, achievements, and a practice log with day, week,
four-week and year views. Playing time is counted from the microphone, from the
Start practice timer in the header, or entered by hand. Below that, proficiency
per scale, piece and individual note: a weighted running average of your mic
sessions, held back until you have a few reps and faded for time since you last
practised, with your all-time best alongside.

## Microphone

Pitch detection uses the YIN algorithm over the Web Audio API, entirely on
device. It analyses the newest ~50 ms of audio every 15 ms, with a half-rate
coarse search refined at full rate, so a new note registers in roughly 100 ms. Nothing is recorded, stored or transmitted. The browser will ask for
permission the first time a listening feature is switched on.

If the prompt never appears, the page is most likely being served over
`file://`, or the browser is blocked at the OS level (on macOS: System
Settings → Privacy & Security → Microphone).

## Data and sign-in

Everything saves to the browser first (`localStorage`), so the app works offline
and without an account.

**Sign in to sync** (top right) uses Google sign-in through Firebase. Once signed
in, history follows you to every device you sign in on:

- Each device uploads its own practice log, and the app adds the logs from your
  other devices on top. Practising on two devices on the same day counts both,
  and re-syncing never double-counts.
- Proficiency keeps the most recent reading per item, plus the best score from
  any device. Achievements earned anywhere count everywhere. Settings such as the
  weekly goal keep the most recent change.
- Signing out keeps your history on that device. Signing in to a browser that
  holds a different account's history asks before replacing it.

Data lives in Firestore under `users/{uid}`, with one document per device under
`users/{uid}/devices/`. The Firestore security rules only let a signed-in user
read and write their own folder. The Firebase config in `index.html` is public
by design; the rules are what protect the data.

Sign-in only works from an authorized domain (the GitHub Pages site, or
`localhost`), not from a file opened directly.

**Export everything** and **Import** on the Progress tab still work as a file
backup, with or without an account.

## Notes on the music

The six pieces are original compositions written for this tool, so the
notation, the fingerings and the practice plans are all free to use and modify.

## Licence

Do what you like with it.
