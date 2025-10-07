#!/usr/bin/env bash
set -euo pipefail

find assets -type f \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.ogg' \) | while IFS= read -r src; do
  if [ ! -f "$src" ]; then
    continue
  fi

  dir=$(dirname "$src")
  base=$(basename "$src")
  name="${base%.*}"

  tmp="${dir}/${name}.tmp.wav"

  ffmpeg -y -hide_banner -loglevel error \
    -i "$src" -ac 1 -ar 48000 "$tmp"

  mv "$src" "${src}.orig"
  mv "$tmp" "$dir/$name.wav"
  echo "Converted $src -> $dir/$name.wav"
done
