# Changelog

## 1.0.1

- The `ponds` input ignores blank lines and lines starting with `#`. The example workflow keeps its `ponds` lines active with a `# OWNER/REPOSITORY` placeholder, so adding a Pond means replacing one line rather than uncommenting several.
- Documentation and workflow text capitalize Pond.

## 1.0.0

First release.

- Reusable workflow `release.yml`: builds Flatpak bundles for x86_64 and aarch64 on native runners and publishes them as GitHub releases named `<app ID>-<arch>.flatpak`.
- Releases from a version bump in the app's metainfo, or from a pushed `v*` tag.
- Checks on every push and pull request: one manifest, metainfo releases newest first, and optional `version-files` that must agree with the version.
- Release notes from the metainfo release description; `development` releases and hyphenated versions become pre-releases.
- Releases are published only after all bundles are attached, and optionally trigger FrogPak Ponds.
