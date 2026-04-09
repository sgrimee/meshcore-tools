---
name: update-readme
description: Update README.md with new features, keybindings, configuration options, or screenshots. Use when the user asks to update the readme, document new features, or keep the readme in sync with recent changes.
user-invocable: true
---

Update `README.md` at the project root to reflect new features and changes since it was last updated.

## Step 1 — Determine what changed

Run: `git describe --tags --abbrev=0 2>/dev/null`

- If a tag is found (e.g. `v0.2.0`): collect commits in range `v0.2.0..HEAD`
- If no tags: collect all commits

Run: `git log --oneline --no-merges [<range>]`

Exclude commits whose message starts with `chore:`, `chore(changelog)`, `chore: update changelog`, or `ci:`.

## Step 2 — Identify documentation-worthy changes

From the commit list, focus on commits with these prefixes as likely candidates for README updates:

| Prefix | Likely README impact |
|---|---|
| `feat:` | New feature — almost always warrants a README entry |
| `fix:` | Only if it corrects user-visible behaviour described in the README |
| `refactor:` | Only if it changes user-facing behaviour (CLI flags, keybindings, config keys) |
| `docs:` | May already update the README directly |

Ignore pure `test:`, `build:`, `style:`, `ci:` commits — they have no user-visible impact.

## Step 3 — Read the current README and relevant source files

Read `README.md` in full to understand the current documented state.

Then read the source files relevant to the changed areas:
- `src/meshcore_tools/**/*.py` — CLI flags, keybindings, tab structure, providers, config
- `CHANGELOG.md` — already-categorised description of recent changes (good cross-reference)

Check `assets/` for any new screenshots that are not yet referenced in the README:
```sh
ls assets/
```

## Step 4 — Determine what to update

Compare the commit list against the current README content and identify gaps. Typical update types:

- **New feature section or subsection** — a whole new tab, connection type, or major capability
- **New bullet in Features list** — a notable new capability within an existing area
- **New keybinding row** — a new key added to the monitor or app
- **New CLI flag** — added to the Usage options table
- **New config key** — added to the `settings.toml` reference table
- **New screenshot** — image exists in `assets/` but is not in the README
- **Corrected fact** — a documented behaviour that no longer matches the code (e.g. wrong keybinding)

**Do not add** entries for internal refactors, test coverage, CI changes, or fixes that don't change documented behaviour.

## Step 5 — Update README.md

Apply only the changes identified in Step 4. Follow the existing README style exactly:

- Match heading levels, table formatting, and code block style of surrounding content
- For new Features bullets: place under the correct group (Monitor mode / Companion mode / Node database CLI)
- For new keybindings: insert in the Monitor keybindings table in a logical position; correct any stale entries
- For new config keys: append a row to the `settings.toml` reference table
- For new screenshots: add in the Screenshots section using the same `assets/` relative path pattern
- Keep the WIP notice accurate — update it if the scope of "work in progress" changes
- **Do not rewrite or restructure** sections that are not affected by the new changes
- **Do not add entries that are already present** (check verbatim before inserting)

## Step 6 — Verify

After editing, confirm:
- All image paths referenced in the README exist in `assets/`
- No stale facts remain (e.g. wrong keybinding, removed CLI flag)
- The README still reads coherently — spot-check the sections you touched

## Output

Report concisely:
- Which sections were updated and what was added/changed
- Any new screenshots included
- Any stale facts corrected
- Full path to the file
