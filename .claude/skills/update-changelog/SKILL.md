---
name: update-changelog
description: Update CHANGELOG.md following keepachangelog.com format. Use when the user asks to update the changelog, add changes to the changelog, record recent work, or prepare a release. Automatically reads git history and maps conventional commits to Added/Changed/Fixed/Removed/Security/Deprecated sections.
user-invocable: true
---

Update or create `CHANGELOG.md` at the project root following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

## Step 1 — Get remote URL

Run: `git remote get-url origin 2>/dev/null`

Convert SSH remote (`git@github.com:user/repo.git`) to HTTPS (`https://github.com/user/repo`).

## Step 2 — If CHANGELOG.md does not exist

Create it with this scaffold (substitute the real remote URL):

```
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

[unreleased]: https://github.com/owner/repo/compare/HEAD...HEAD
```

## Step 3 — Determine commit range

Run: `git describe --tags --abbrev=0 2>/dev/null`

- If a tag is found (e.g. `v0.2.0`): use range `v0.2.0..HEAD`
- If no tags exist: use all commits (no range argument)

Run: `git log --oneline --no-merges [<range>]`

Exclude commits whose message starts with `chore: update changelog` or `chore(changelog)`.

## Step 4 — Map commits to keepachangelog categories

| Conventional prefix(es) | Section |
|-------------------------|---------|
| `feat:`, `feat(…):` | Added |
| `fix:`, `fix(…):` | Fixed |
| `refactor:`, `perf:`, `docs:`, `style:`, `chore:`, `test:`, `build:`, `ci:` | Changed |
| `security:` | Security |
| `deprecate:` | Deprecated |
| `remove:` | Removed |

If no prefix matches, put the entry under **Changed**.

Format each entry: strip the `type:` prefix, capitalize the first letter, keep the rest verbatim.
Example: `feat: add resize handle between panels` → `- Add resize handle between panels`

## Step 5 — Insert entries into [Unreleased]

- Locate the `## [Unreleased]` section.
- For each category that has new entries, ensure a `### Category` subsection header exists immediately below `## [Unreleased]` (before the next `## [` version heading).
- Only include subsection headers that have at least one entry — omit empty ones.
- Append new bullet points after any existing ones in that subsection.
- **Deduplication:** skip any commit whose stripped message already appears verbatim in the file.
- Preserve all existing content unchanged.

Order of subsections (use only those present): Added, Changed, Deprecated, Removed, Fixed, Security.

## Step 6 — Update comparison link

At the bottom of the file, update (or add) the `[unreleased]` link:

- If a latest tag exists:
  ```
  [unreleased]: https://github.com/owner/repo/compare/v0.2.0...HEAD
  ```
- If no tags exist, leave the link pointing to the repo root or omit it.

## Output

After updating, report concisely:
- Number of new entries added and which sections were touched
- Full path to the file
