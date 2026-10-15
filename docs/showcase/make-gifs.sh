#!/bin/sh
# Turns the showcase recordings (media/*.webm) into GIFs for the Markdown page and MP4s for sharing.
# Needs an ffmpeg with libx264: set FFMPEG=/path/to/ffmpeg if it isn't on PATH.
set -e
cd "$(dirname "$0")/media"
FFMPEG="${FFMPEG:-ffmpeg}"
for f in *.webm; do
  n="${f%.webm}"
  "$FFMPEG" -y -loglevel error -i "$f" -vf "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" "$n.gif"
  "$FFMPEG" -y -loglevel error -i "$f" -c:v libx264 -pix_fmt yuv420p -crf 23 -movflags +faststart "$n.mp4"
  echo "$n: $(du -h "$n.gif" | cut -f1) gif, $(du -h "$n.mp4" | cut -f1) mp4"
done
