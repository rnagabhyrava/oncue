#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install_dir="$HOME/.local/share/oncue/bin"
mkdir -p "$install_dir" "$HOME/.local/bin"
if [ "$source_dir" != "$install_dir" ]; then
  cp -a "$source_dir/." "$install_dir/"
fi
ln -sfn "$install_dir/oncue" "$HOME/.local/bin/oncue"
ln -sfn "$install_dir/oncue" "$HOME/.local/bin/codex-local-scheduler"
"$install_dir/oncue" install-startup
"$install_dir/oncue" open
