#!/usr/bin/env bash
set -euo pipefail

find assets -type f -print0 | while IFS= read -r -d '' src; do
  base=$(basename "$src")
  case "$base" in
    *_48k.ogg|*.orig|*.bak|*.ogg|*.wav|.*) continue ;;
  esac

  dir=$(dirname "$src")
  if [[ "$base" == *.* ]]; then
    name="${base%.*}"
  else
    name="$base"
  fi
  dest="${dir}/${name}_48k.ogg"

  echo "Converting $src -> $dest"
  ffmpeg -y -hide_banner -loglevel error \
    -i "$src" -ac 1 -ar 48000 -codec:a libvorbis -qscale:a 4 "$dest"

done
