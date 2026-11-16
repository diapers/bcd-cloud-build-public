# bcd-cloud-build

Builds an unsigned BCD IPA on GitHub Actions from the public source of a
[thebcd69/bcd-games](https://github.com/thebcd69/bcd-games) release, with this
repository's patches applied.

Nothing from BCD is stored here. Each run downloads the release's
`BCD-source.tar.xz` (the source) and `BCD.ipa` (only for Apple's
`libmetalirconverter.dylib`, which the public source leaves out).

## Patches

- `patches/external-drives-uikit-picker.patch`: Settings › Storage › External
  drives. "Add a drive or folder" and "Reconnect" open the folder picker from
  UIKit (`UIDocumentPickerViewController`, folders, in place) instead of
  SwiftUI's `.fileImporter`, which on some devices never appears (the log shows
  `[ext-storage] picker opened` and nothing after it).
- `patches/dxc-in-tree-generated-headers.patch`: `tools/build-dxcompiler.sh`
  builds DXC with `HLSL_DISABLE_SOURCE_GENERATION=ON`. The runner's
  Homebrew clang-format formats DXC's regenerated headers differently from
  the copies in DXC's tree, so the build stopped at "Verifying clang-format
  results"; the in-tree copies are what the build compiles either way.

KosmicKrisp (Mesa's Vulkan on Metal 4) does not build on the runner (its
Homebrew LLVM is newer than BCD's pinned translator supports); BCD's workflow
then ships without it, which only matters for a game set to
`vulkan = kosmickrisp`.

## Build

Actions › **Build BCD IPA** › Run workflow. Inputs:

- `tag`: the bcd-games release to build (default `v0.1.665`);
- `build_number`: the app's version is `0.1.<this>` (default `666`, one above
  the release, so it installs over it).

The IPAs are kept for 7 days as the run's artifact
`BCD-0.1.<n>-unsigned` (`Madeira-…` and `Madeira2-…`). Sign and install one
with your usual tool (Feather, SideStore, …).

## A newer BCD release

Run `python3 tools/make-fork-workflow.py <new source>/.github/workflows/build-ipa.yml`
to regenerate `.github/workflows/build-ipa.yml` from that release's own
workflow, check the patches still apply, then build with the new `tag`.
