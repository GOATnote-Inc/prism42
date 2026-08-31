#!/usr/bin/env bash
# Build the 44ms reveal motion graphic — wow moment #1.
# 7 seconds: 1655 ms (red, strike-through animates) → white flash → 44 ms (mint green, hold).
# 1920x1080 24fps H.264. Hard silence.

set -euo pipefail

OUT=~/prism42/findings/runway-aiff/clips/HERO_44ms.mp4
FONT=/System/Library/Fonts/Helvetica.ttc

# Color palette
BG="0x0a0e14"        # Tokyo-night charcoal
RED="0xc24545"       # baseline-bad red (muted, not Mario)
MINT="0x66ddaa"      # mint green
SUB="0x808a99"       # subtle subtitle

# Geometry — 1920x1080
# Big number centered, smaller "ms" trailing, "p95 TTFT" small caption above

ffmpeg -y -f lavfi -i "color=c=${BG}:s=1920x1080:d=7:r=24" \
  -vf "
    drawtext=fontfile=${FONT}:text='p95 · TTFT':fontcolor=${SUB}:fontsize=44:x=(w-text_w)/2:y=h*0.22:enable='between(t,0.0,7.0)',
    drawtext=fontfile=${FONT}:text='1655':fontcolor=${RED}:fontsize=320:x=(w-text_w)/2-90:y=h*0.34:enable='between(t,0.0,2.4)',
    drawtext=fontfile=${FONT}:text='ms':fontcolor=${RED}:fontsize=140:x=(w/2)+200:y=h*0.46:enable='between(t,0.0,2.4)',
    drawbox=x=(w/2)-330:y=(h*0.5):w=if(lte(t\,1.0)\,0\,if(lte(t\,2.0)\,(t-1.0)*660\,660)):h=20:color=${RED}@0.95:t=fill:enable='between(t,1.0,2.4)',
    drawbox=x=0:y=0:w=w:h=h:color=white@1.0:t=fill:enable='between(t,2.42,2.50)',
    drawtext=fontfile=${FONT}:text='44':fontcolor=${MINT}:fontsize=480:x=(w-text_w)/2-110:y=h*0.28:enable='gte(t,2.5)',
    drawtext=fontfile=${FONT}:text='ms':fontcolor=${MINT}:fontsize=180:x=(w/2)+200:y=h*0.46:enable='gte(t,2.5)',
    drawtext=fontfile=${FONT}:text='91.6%% reduction':fontcolor=${MINT}:fontsize=54:x=(w-text_w)/2:y=h*0.78:enable='gte(t,3.0)',
    drawtext=fontfile=${FONT}:text='vLLM 0.20 · Nemotron Nano 3 MoE · sm_103 native':fontcolor=${SUB}:fontsize=32:x=(w-text_w)/2:y=h*0.86:enable='gte(t,3.5)'
  " \
  -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -an "${OUT}"

ls -la "${OUT}"
ffprobe -v error -show_entries format=duration -show_entries stream=codec_name,width,height -of default=noprint_wrappers=1 "${OUT}"
