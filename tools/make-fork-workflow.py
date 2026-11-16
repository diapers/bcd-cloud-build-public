#!/usr/bin/env python3
"""Turn BCD's own .github/workflows/build-ipa.yml into this repository's workflow.

Usage: python3 tools/make-fork-workflow.py <bcd-source>/.github/workflows/build-ipa.yml

The upstream workflow builds from the owner's private repository and keeps the IPA in the owner's private bucket.
Here it builds the public source of a thebcd69/bcd-games release instead:

  - the job is not limited to thebcd69/madeira-bcd;
  - the source is that release's BCD-source.tar.xz, with every patches/*.patch applied;
  - Apple's libmetalirconverter.dylib (not in the public source) comes from the same release's BCD.ipa, and the
    pinned hash in build/madeira-d3d12/deps.sh is changed to that copy's;
  - the source and its submodules are made git checkouts, which some build scripts read with git;
  - the OTA signing step and the private-bucket gate are gone; the unsigned IPAs are kept as an artifact;
  - the "Check ..." steps are left out: they test BCD's source (about 40% of the build's time) and nothing they do goes
    into the IPA. Those that also patch the source (tools/patch-...) stay, and may fail without stopping the build.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / ".github/workflows/build-ipa.yml"

# A "Check ..." step that also changes the source (runs a tools/patch-... script) stays: the build needs what it does.
PATCHES_SOURCE = re.compile(r"^\s+[^#\s].*\btools/patch-", re.M)

ON_UPSTREAM = "on:\n  workflow_dispatch:\n"
ON_FORK = """on:
  workflow_dispatch:
    inputs:
      tag:
        description: "thebcd69/bcd-games release whose source is built"
        default: v0.1.665
      build_number:
        description: "The app's version is 0.1.<this>"
        default: "666"
"""

CHECKOUT_UPSTREAM = """      - uses: actions/checkout@v4
        with:
          submodules: recursive
"""
CHECKOUT_FORK = """      - uses: actions/checkout@v4

      # bcd-cloud-build: the source is the release's public tarball, not this repository; this repository's
      # patches/*.patch are applied on it.
      - name: Get the BCD source (public release) and apply the patches
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
          TAG: ${{ inputs.tag }}
          BUILD_NUMBER: ${{ inputs.build_number }}
        run: |
          set -euo pipefail
          FORK="$RUNNER_TEMP/fork"
          mkdir -p "$FORK" && cp -R patches "$FORK/"
          gh release download "$TAG" -R thebcd69/bcd-games -p BCD-source.tar.xz -D "$RUNNER_TEMP"
          tar -xJf "$RUNNER_TEMP/BCD-source.tar.xz" --strip-components=1 -C "$GITHUB_WORKSPACE"
          rm "$RUNNER_TEMP/BCD-source.tar.xz"
          for p in "$FORK"/patches/*.patch; do
            echo "applying $(basename "$p")"
            git apply --verbose "$p"
          done
          echo "$BUILD_NUMBER" > docs/local-build/BUILD-NUMBER
          echo "::notice::building $TAG as 0.1.$BUILD_NUMBER with $(ls "$FORK"/patches/*.patch | wc -l | tr -d ' ') patch(es)"

      # bcd-cloud-build: Apple's converter library is not in the public source. The official BCD.ipa of the same release
      # carries it; its copy there is signed, so its hash differs from the one deps.sh pins, which is changed to match.
      - name: Get Apple's Metal Shader Converter library (from the release's BCD.ipa)
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
          TAG: ${{ inputs.tag }}
        run: |
          set -euo pipefail
          gh release download "$TAG" -R thebcd69/bcd-games -p BCD.ipa -D "$RUNNER_TEMP"
          ENTRY=$(unzip -Z1 "$RUNNER_TEMP/BCD.ipa" | grep -E '/libmetalirconverter\\.dylib$' | head -1 || true)
          [ -n "$ENTRY" ] || { echo "::error::$TAG's BCD.ipa has no libmetalirconverter.dylib"; exit 1; }
          unzip -p "$RUNNER_TEMP/BCD.ipa" "$ENTRY" > app/Madeira/d3d12/libmetalirconverter.dylib
          rm "$RUNNER_TEMP/BCD.ipa"
          SHA=$(shasum -a 256 app/Madeira/d3d12/libmetalirconverter.dylib | cut -d' ' -f1)
          sed -i '' -E "s/(local ios_lib_sha=\\")[0-9a-f]{64}\\"/\\1$SHA\\"/" build/madeira-d3d12/deps.sh
          grep -q "ios_lib_sha=\\"$SHA\\"" build/madeira-d3d12/deps.sh
          echo "::notice::converter library: $ENTRY from $TAG's BCD.ipa, sha256 $SHA"

      # bcd-cloud-build: some build scripts read the source with git (rev-parse, checkout --, archive, show HEAD:...).
      # Fixed names and dates keep each checkout's commit the same from run to run, so the caches keyed on them hit.
      - name: Make the source and its submodules git checkouts
        shell: bash
        env:
          GIT_AUTHOR_NAME: bcd-cloud-build
          GIT_AUTHOR_EMAIL: bcd-cloud-build@users.noreply.github.com
          GIT_COMMITTER_NAME: bcd-cloud-build
          GIT_COMMITTER_EMAIL: bcd-cloud-build@users.noreply.github.com
          GIT_AUTHOR_DATE: "2026-01-01T00:00:00Z"
          GIT_COMMITTER_DATE: "2026-01-01T00:00:00Z"
          TAG: ${{ inputs.tag }}
        run: |
          set -euo pipefail
          for d in $(git config -f .gitmodules --get-regexp '\\.path$' | awk '{print $2}'); do
            [ -d "$d" ] || continue
            git -C "$d" init -q
            git -C "$d" add -A -f
            git -C "$d" commit -q -m "$TAG $d"
            echo "$d: $(git -C "$d" rev-parse --short HEAD)"
          done
          git add -A -f
          git commit -q -m "$TAG with this repository's patches"
"""

ARTIFACT_FORK = """      # bcd-cloud-build: the unsigned IPAs, kept 7 days. Sign and install them on the device (Feather, SideStore, ...).
      - name: Keep the unsigned IPAs
        uses: actions/upload-artifact@v4
        with:
          name: BCD-0.1.${{ steps.bn.outputs.n }}-unsigned
          path: build-out/*-unsigned.ipa
          if-no-files-found: error
          retention-days: 7
          compression-level: 0

"""


def replace_once(text, old, new, what):
    if text.count(old) != 1:
        sys.exit(f"make-fork-workflow: {what} not found exactly once in the upstream workflow")
    return text.replace(old, new)


def step_spans(lines):
    """(start, end) line ranges of the job's steps: from a '      - ' line to the next one or the job's end."""
    starts = [i for i, l in enumerate(lines) if l.startswith("      - ")]
    spans = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        # Comment lines just before the next step belong to it, not to this one.
        while e - 1 > s and (lines[e - 1].startswith("      #") or not lines[e - 1].strip()):
            e -= 1
        spans.append((s, e))
    return spans


def step_name(lines, s, e):
    for l in lines[s:e]:
        m = re.match(r'^      (?:- |  )name:\s*["\']?(.*?)["\']?\s*$', l)
        if m:
            return m.group(1)
    return ""


def remove_step(text, name):
    lines = text.split("\n")
    for s, e in step_spans(lines):
        if step_name(lines, s, e) == name:
            # Take the step's own comment block (the comment lines right above it) too.
            while s > 0 and lines[s - 1].startswith("      #"):
                s -= 1
            while e < len(lines) and not lines[e].strip():
                e += 1
            return "\n".join(lines[:s] + lines[e:]), s
    sys.exit(f"make-fork-workflow: step {name!r} not found")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    text = Path(sys.argv[1]).read_text(encoding="utf-8")

    text = replace_once(text, "name: Build Madeira IPA (unsigned)\n", "name: Build BCD IPA (bcd-cloud-build, unsigned)\n", "the workflow name")
    text = replace_once(text, ON_UPSTREAM, ON_FORK, "the workflow_dispatch trigger")
    text = replace_once(text, "    # madeira-bcd: runs only in the owner's repository; a fork's run is skipped.\n"
                              "    if: github.repository == 'thebcd69/madeira-bcd'\n", "", "the owner-only condition")
    text = replace_once(text, "      contents: write\n", "      contents: read\n", "the contents permission")
    text = replace_once(text, CHECKOUT_UPSTREAM, CHECKOUT_FORK, "the checkout step")

    text, _ = remove_step(text, "Sign for OTA install (private bucket)")
    text, at = remove_step(text, "Check the IPA reached the private bucket")
    lines = text.split("\n")
    lines[at:at] = ARTIFACT_FORK.rstrip("\n").split("\n") + [""]

    removed = kept = 0
    for s, e in reversed(step_spans(lines)):
        name = step_name(lines, s, e)
        if not name.startswith("Check"):
            continue
        if PATCHES_SOURCE.search("\n".join(lines[s:e])):
            if not any(l.startswith("        continue-on-error:") for l in lines[s:e]):
                lines.insert(s + 1, "        continue-on-error: true")
            kept += 1
            continue
        while s > 0 and lines[s - 1].startswith("      #"):
            s -= 1
        while e < len(lines) and not lines[e].strip():
            e += 1
        del lines[s:e]
        removed += 1
    text = "\n".join(lines)

    header = ("# Generated by tools/make-fork-workflow.py from BCD's own build-ipa.yml (thebcd69/bcd-games).\n"
              "# Change the generator, not this file.\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(header + text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(HERE)}: {removed} Check steps left out, {kept} kept")


if __name__ == "__main__":
    main()
