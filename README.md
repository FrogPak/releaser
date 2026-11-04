# FrogPak releaser

Builds your app's Flatpak for x86_64 and aarch64 and publishes GitHub releases that [FrogPak](https://github.com/FrogPak/engine) Ponds pick up. Bump the version in your metainfo, push, and the tag, release and bundles follow.

Optional: a Pond only needs releases with `.flatpak` files it can match, however they were built.

## Use it

Copy [`examples/release.yml`](examples/release.yml) to `.github/workflows/release.yml` in your app repository.

To release, add a `<release>` to the top of your metainfo's `<releases>` and push it to your default branch:

```xml
<release version="1.2.0" date="2026-11-03">
  <description>
    <p>What changed, shown in software centers and on the GitHub release.</p>
  </description>
</release>
```

Without metainfo, push a tag such as `v1.2.0` instead.

What runs when:

| Event | Result |
| --- | --- |
| Push to the default branch, new metainfo version | Checks, build, tag, release, Ponds triggered |
| Push to the default branch, version already released | Checks |
| Push of a `v*` tag | Checks, build, release, Ponds triggered |
| Pull request or other branch | Checks |
| Manual run | Checks, build, bundles as workflow artifacts |

Versions with a hyphen (`1.2.0-rc1`) and metainfo releases of type `development` become pre-releases, which Ponds ignore.

Bundles are named `<app ID>-<arch>.flatpak`, so `https://github.com/OWNER/REPO/releases/latest/download/<app ID>-x86_64.flatpak` always points at the newest release.

## Inputs

| Input | Default | Purpose |
| --- | --- | --- |
| `manifest` | found automatically | Manifest path, when `build-aux/`, `flatpak/`, `packaging/` and the root hold none or several |
| `metainfo` | found automatically | Metainfo path, when several files match the app ID |
| `version-files` | none | Lines of `path: regex`; each regex's first group must equal the version |
| `tag-prefix` | `v` | Prefix of release tags |
| `arches` | `x86_64 aarch64` | Architectures to build |
| `runners` | `ubuntu-latest`, `ubuntu-26.04-arm` | Lines of `arch: runner label` |
| `ponds` | none | Pond repositories (`owner/repo`), one per line, to trigger after a release; lines starting with `#` are ignored |

Secret `POND_TOKEN`: a fine-grained token with **Actions: Read and write** on the Pond repositories. Without it, Ponds pick releases up at their next hourly check.

The aarch64 runner is free for public repositories only.

## License

GPL-3.0-or-later. Your app and its releases are not covered by it.
