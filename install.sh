#!/bin/sh
# Install the official OnCue Linux bundle; no Python, Node, or sudo required.
set -eu
umask 077
fail() { printf 'OnCue: %s\n' "$*" >&2; exit 1; }
prefix="$HOME/.local"
version=latest
archive=
start=yes
open=yes
startup=no
while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix|--version|--archive)
      [ "$#" -ge 2 ] || fail "$1 requires a value"
      case "$1" in --prefix) prefix=$2;; --version) version=$2;; --archive) archive=$2;; esac
      shift 2;;
    --no-open) open=no; shift;;
    --no-start) start=no; shift;;
    --startup) startup=yes; shift;;
    --help) printf '%s\n' 'Usage: sh install.sh [--version v0.3.0] [--prefix PATH] [--no-open] [--no-start] [--startup] [--archive FILE]' 'Local archives require FILE.sha256. Startup at sign-in is opt-in.'; exit 0;;
    *) fail "Unknown option: $1";;
  esac
done
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || fail 'Only Linux x86_64 is supported by this bundle.'
glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null) || fail 'This bundle needs glibc Linux; Alpine/musl is not supported.'
printf '%s\n' "$glibc" | awk '{split($2,v,"."); exit !(v[1]>2 || (v[1]==2 && v[2]>=38))}' || fail 'This bundle needs glibc 2.38+ (for example, Ubuntu 24.04+).'
for tool in tar sha256sum mktemp; do command -v "$tool" >/dev/null 2>&1 || fail "Install $tool first."; done
case "$version" in ''|*[!a-zA-Z0-9._-]*) fail 'Invalid release version';; esac
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
asset=oncue-linux-x86_64.tar.gz
fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 20 --output "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget --https-only --tries=3 --timeout=30 -O "$2" "$1"
  else fail 'Install curl or wget first.'; fi
}
if [ -n "$archive" ]; then
  cp "$archive" "$work/$asset"
  cp "$archive.sha256" "$work/checksum"
else
  base=https://github.com/rnagabhyrava/oncue/releases
  if [ "$version" = latest ]; then base=$base/latest/download; else base=$base/download/$version; fi
  printf 'Downloading OnCue (%s)…\n' "$version"
  fetch "$base/$asset" "$work/$asset" || fail 'Could not download this release. Check your connection and release version.'
  fetch "$base/$asset.sha256" "$work/checksum" || fail 'Release checksum is missing; installation stopped.'
fi
# Accept only the checksum for the expected asset, never arbitrary checksum paths.
expected=$(awk -v name="$asset" '$2 == name {print $1}' "$work/checksum")
[ "${#expected}" = 64 ] || fail 'Invalid release checksum.'
case "$expected" in *[!0-9a-fA-F]*) fail 'Invalid release checksum.';; esac
actual=$(sha256sum "$work/$asset"); actual=${actual%% *}
[ "$actual" = "$expected" ] || fail 'Checksum mismatch. Nothing was installed; download again.'
mkdir "$work/extract"
tar -xzf "$work/$asset" -C "$work/extract"
[ -f "$work/extract/oncue/install.sh" ] || fail 'Release bundle is incomplete.'
set -- --prefix "$prefix"
[ "$start" = yes ] || set -- "$@" --no-start
[ "$open" = yes ] || set -- "$@" --no-open
[ "$startup" = no ] || set -- "$@" --startup
sh "$work/extract/oncue/install.sh" "$@"
