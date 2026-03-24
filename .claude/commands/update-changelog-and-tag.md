# Release: Update Changelog and Tag

You are preparing a release. Follow these steps precisely.

## 1. Determine release type

Default to **minor** unless the user specified patch or major in their request.

## 2. Get latest tag and commits since it

Run:
```bash
git describe --tags --abbrev=0
```

Then get all commits since that tag:
```bash
git log <latest-tag>..HEAD --oneline
```

Also get the full commit messages for context:
```bash
git log <latest-tag>..HEAD --pretty=format:"%h %s%n%b"
```

## 3. Compute new version

Parse the latest tag (strip leading `v` if present) as `MAJOR.MINOR.PATCH`.

- **major**: increment MAJOR, reset MINOR and PATCH to 0
- **minor**: increment MINOR, reset PATCH to 0
- **patch**: increment PATCH only

## 4. Categorize commits

Read through the commit messages and group changes under the standard Keep-a-Changelog headings:

- **Added** – new features
- **Changed** – changes to existing behavior
- **Deprecated** – soon-to-be-removed features
- **Removed** – removed features
- **Fixed** – bug fixes
- **Security** – security fixes

Omit any heading that has no entries. Write concise, user-facing bullet points (not git commit hashes).

## 5. Update CHANGELOG.md

Open `CHANGELOG.md`. Replace the `## [Unreleased]` section (keep the heading) and insert a new versioned section **above** the previous release, using today's date (`YYYY-MM-DD`). Keep the `## [Unreleased]` heading empty above it for future use.

Format:
```
## [Unreleased]

## [X.Y.Z] - YYYY-MM-DD

### Added
- ...

### Fixed
- ...
```

## 6. Update version in pyproject.toml

Find the `version` field in `pyproject.toml` and update it to the new version string.

## 7. Sync documentation site

1. **`website/reference/changelog.md`** — Mirror the same new version section you added to `CHANGELOG.md` (same date and bullets; keep the site’s existing formatting style, e.g. bold labels on list items if present).

2. **`website/.vitepress/config.ts`** — In `themeConfig.nav`, find the dropdown whose `items` include Changelog and PyPI. Set its `text` to **`vX.Y.Z`** (must match the release tag). This is the version shown in the top-right corner of the docs site.

## 8. Commit and tag

```bash
git add CHANGELOG.md pyproject.toml website/reference/changelog.md website/.vitepress/config.ts
git commit -m "chore: release vX.Y.Z"
git tag vX.Y.Z
```

## 9. Report

Tell the user:
- The new version
- A summary of what was included in the release
- The git tag that was created
- Remind them to push with: `git push && git push --tags` (the docs site will pick up the VitePress version after the docs deploy workflow runs, if applicable)
