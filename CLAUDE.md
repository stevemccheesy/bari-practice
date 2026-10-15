# Bari practice

Single-file app: everything is in `index.html` (HTML, CSS and JS inline, no
build). Hosted on GitHub Pages from `main`, root. `ROADMAP.md` is the running
list for the next release.

## Release process

1. Build the roadmap items for the release in `index.html`.
2. Run the regression suite against the previous release tag and fix anything
   it flags before pushing:
   `python3 qa/regress.py --base-ref <previous tag> index.html`
   New features get their own check in `qa/regress.py` (returning `"n/a"`
   on builds without the feature).
3. Move the shipped items in `ROADMAP.md` under **Shipped**, update
   `README.md` if a feature changed.
4. Commit and push to `main`. Tag the release (`vX.Y`).
5. Confirm the Pages deploy for that commit finished
   (`gh api repos/stevemccheesy/bari-practice/actions/runs`).
6. **After every release push, run the full QA regression again on what
   shipped** (the pushed `index.html`, or the live site if reachable) against
   the previous release, and report the result: every check `same`, `new` or
   `fixed`, or the differences explained.
