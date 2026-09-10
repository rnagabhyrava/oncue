#!/bin/sh
set -eu
umask 077
fail() { printf 'OnCue: %s\n' "$*" >&2; exit 1; }
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
prefix="$HOME/.local"
start=yes
open=yes
startup=no
while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix) [ "$#" -ge 2 ] || fail '--prefix requires a path'; prefix=$2; shift 2;;
    --no-start) start=no; shift;;
    --no-open) open=no; shift;;
    --startup) startup=yes; shift;;
    --help) printf '%s\n' 'Usage: sh install.sh [--prefix PATH] [--no-start] [--no-open] [--startup]'; exit 0;;
    *) fail "Unknown option: $1";;
  esac
done
case "$prefix" in /*) ;; *) fail 'Install prefix must be an absolute path';; esac
case "$prefix" in *'
'*) fail 'Install prefix cannot contain a newline';; esac
[ -x "$source_dir/oncue" ] || fail 'The bundled OnCue executable is missing.'
"$source_dir/oncue" --help >/dev/null || fail 'This bundle cannot run here. Linux x86_64 with glibc 2.38+ is required.'
for name in oncue codex-local-scheduler; do
  target="$prefix/bin/$name"
  if [ -e "$target" ] || [ -L "$target" ]; then
    [ -L "$target" ] && [ "$(readlink "$target")" = "$prefix/share/oncue/bin/oncue" ] || fail "Refusing to replace unrelated command: $target"
  fi
done
mkdir -p "$prefix/share/oncue" "$prefix/bin"
base=$(CDPATH= cd -- "$prefix/share/oncue" && pwd)
install_dir="$base/bin"
[ "$source_dir" != "$install_dir" ] || fail 'Already installed here. Use oncue open to start the app.'
# Serialize installs; this directory contains no user data.
mkdir "$base/.install-lock" 2>/dev/null || fail "Another install is in progress. If it was interrupted, remove $base/.install-lock and retry."
stage=$(mktemp -d "$base/.install-XXXXXX")
backup=
cleanup() {
  rm -rf "$stage"
  rmdir "$base/.install-lock" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM
cp -a "$source_dir/." "$stage/"
if ! "$stage/oncue" prepare-update; then
  [ ! -x "$install_dir/oncue" ] || "$install_dir/oncue" start >/dev/null 2>&1 || true
  fail 'Update stopped before replacing the app. Let active tasks finish, then retry.'
fi
if [ -e "$install_dir" ]; then
  backup="$base/.previous-$$"
  [ ! -e "$backup" ] || fail 'Backup directory already exists.'
  mv "$install_dir" "$backup"
fi
if ! mv "$stage" "$install_dir"; then
  [ -z "$backup" ] || mv "$backup" "$install_dir"
  fail 'Could not activate the new app; previous installation restored.'
fi
ln -sfn "$install_dir/oncue" "$prefix/bin/oncue"
ln -sfn "$install_dir/oncue" "$prefix/bin/codex-local-scheduler"
if [ "$start" = yes ]; then
  if [ "$open" = yes ]; then action=open; else action=start; fi
  if ! "$install_dir/oncue" "$action"; then
    "$install_dir/oncue" stop >/dev/null 2>&1 || true
    rm -rf "$install_dir"
    if [ -n "$backup" ]; then
      mv "$backup" "$install_dir"
      "$install_dir/oncue" start >/dev/null 2>&1 || true
    else
      rm -f "$prefix/bin/oncue" "$prefix/bin/codex-local-scheduler"
    fi
    fail 'OnCue could not start. Previous app restored when available. Task data was retained.'
  fi
fi
"$install_dir/oncue" install-launcher --prefix "$prefix"
if [ "$startup" = yes ]; then
  "$install_dir/oncue" install-startup || printf '%s\n' 'Automatic startup could not be enabled. You can still use oncue open.' >&2
fi
[ -z "$backup" ] || rm -rf "$backup"
printf '\nOnCue installed.\nStart: %s/bin/oncue open\nStop: %s/bin/oncue stop\nUninstall: %s/bin/oncue uninstall\n' "$prefix" "$prefix" "$prefix"
case ":$PATH:" in *":$prefix/bin:"*) ;; *) printf 'Add %s/bin to PATH to use the short oncue command.\n' "$prefix";; esac
