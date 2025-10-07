#!/usr/bin/env bash
set -euo pipefail

find assets -type f -name '*.orig' -print0 | while IFS= read -r -d '' orig; do
  mv "$orig" "${orig%.orig}"
done

find assets -type f \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.ogg' \) -print0 | while IFS= read -r -d '' src; do
  if [ ! -f "$src" ]; then
    continue
  fi
  dir=$(dirname "$src")
  base=$(basename "$src")
  name="${base%.*}"
  tmp="${dir}/${name}.tmp.ogg"

  ffmpeg -y -hide_banner -loglevel error \
    -i "$src" -ac 1 -ar 48000 -codec:a libvorbis -qscale:a 4 "$tmp"

  mv "$src" "${dir}/${name}.bak"
  mv "$tmp" "$dir/${name}.ogg"
  echo "Converted $src -> $dir/${name}.ogg"
done

find assets -type f -name '*.bak' -print0 | while IFS= read -r -d '' bak; do
  mv "$bak" "${bak%.bak}"
done
