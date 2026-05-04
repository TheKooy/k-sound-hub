# GitHub publishing workflow

Recommended layout:

- commit source code to the Git repository
- do not commit generated release archives
- do not commit `.venv`, caches, local settings, keystores, or generated APK files
- upload installable `.tar.gz`, `.zip`, APK, and checksum files as GitHub Release assets

## Existing repository workflow

This project already has Git history and remote branches.
Do not reinitialize the repository and do not force-push over `main`.

Recommended maintainer flow:

```bash
git checkout feature/native-micro-engine
git fetch origin --prune --tags
git status --short --branch
./scripts/package_release.sh
```

When the release branch is validated, publish from a tag on the commit that contains the release files.
## Create a local release archive

```bash
./scripts/package_release.sh
```

## Publish with GitHub CLI

```bash
VERSION="$(python - <<'PY'
import tomllib
print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])
PY
)"
TAG="v$VERSION"

git tag -a "$TAG" -m "K-Sounds Hub $TAG"
git push origin main "$TAG"

gh release create "$TAG" \
  dist/k-sounds-hub-linux-release-$TAG.tar.gz \
  dist/k-sounds-hub-linux-release-$TAG.zip \
  dist/SHA256SUMS.txt \
  --title "K-Sounds Hub $TAG" \
  --notes-file "RELEASE_NOTES_$TAG.md"
```

## Optional APK asset

Generated APK files should normally be release assets, not Git-tracked source files.
If you have an APK ready, package it with:

```bash
KSH_APK_PATH=/path/to/KSoundsSoundboardRemote.apk ./scripts/package_release.sh
```
