#!/usr/bin/env sh
set -eu

if [ "${1:-}" = "" ]; then
  echo "Usage: ./install.sh /path/to/grocy/config/data/plugins"
  exit 1
fi

target_dir="$1"
mkdir -p "$target_dir"
cp UltimateBarcodeLookupPlugin.php "$target_dir/UltimateBarcodeLookupPlugin.php"
echo "Installed UltimateBarcodeLookupPlugin.php to $target_dir"
