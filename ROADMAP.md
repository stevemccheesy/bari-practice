# Roadmap

A running list of what's planned. Items move to the release notes when they ship.

## Next release (v1.2)

- [ ] **Scales: keep listening when Loop is on.** With **Listen with mic** and
      **Loop** both on, finishing a run logs the score, shows the result for a
      moment, then clears the red and green marks and starts listening again
      from the first note, so you can play run after run without touching the
      mic toggle. Show a run counter in the listening bar (for example
      "Run 3 · 14 of 15 right") so back-to-back progress is visible. With Loop
      off, it stops at the end of the run as it does now.

- [ ] **Songs: build your own piece on a staff instead of typing it.** Replace
      the text box in **Add your own** with a visual editor:
  - A blank treble staff in 4/4 that grows a bar at a time, with ledger lines
    covering the bari's written range (low A to high F).
  - **Click** the staff to place a note at the next open beat, at the pitch
    you clicked. **Drag** a placed note up or down to change its pitch.
  - Each note gets a **dropdown for its length**: eighth, quarter, dotted
    quarter, half, dotted half, whole. The same dropdown turns a note into a
    rest of that length, and sets a sharp, flat or natural.
  - New notes default to the last length you picked, so a run of eighths is
    just a run of clicks.
  - **Every note plays its sound** when it's placed, dragged to a new pitch, or
    changed, so you hear the tune as you build it.
  - Bars fill themselves: a note too long for what's left of a bar starts the
    next one, and each bar shows how many beats are still free.
  - Delete a note (button or Backspace), undo, and **Play** the whole piece
    from any point.
  - Keep the typed format as a secondary **Paste notation** option, for
    importing pieces quickly.

## Shipped

- **v1.1** — Google sign-in and cross-device sync, practice log and weekly
  goal, faster pitch detection, fingering fixes.
- **v1.0** — Scales and arpeggios with mic listening, note flashcards, songs,
  proficiency tracking.
