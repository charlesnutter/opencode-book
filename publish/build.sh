#!/usr/bin/env bash
# Convert generated chapters into EPUB and PDF.
#
# Runs inside the ocbook-publish container with the repo mounted at /work.
# Inputs come from `obook build` + `obook assemble`; outputs land in
# build/publish/.
set -euo pipefail

cd /work

DEJAVU_MONO=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf
PUB=build/publish
EPUB="$PUB/opencode-book.epub"
PDF="$PUB/opencode-book.pdf"

mkdir -p "$PUB"

echo "== 1/5 collecting chapters =="
# obook writes one file per chapter, prefixed for reading order. Strip the
# build stamp comment obook embeds at the top of each.
mapfile -t CHAPTERS < <(find build -maxdepth 1 -name "*.md" ! -name "manuscript.md" | sort)
if [ "${#CHAPTERS[@]}" -eq 0 ]; then
  echo "No chapters in build/. Run: obook build" >&2
  exit 1
fi
echo "${#CHAPTERS[@]} chapters"

rm -rf "$PUB/src" "$PUB/images"
mkdir -p "$PUB/src" "$PUB/images"
for f in "${CHAPTERS[@]}"; do
  python3 - "$f" "$PUB/src/$(basename "$f")" <<'PY'
import sys, pathlib
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
text = src.read_text(encoding="utf-8")
if text.startswith("<!--obook\n"):
    end = text.find("\n-->\n")
    if end != -1:
        text = text[end + len("\n-->\n"):]
dst.write_text(text, encoding="utf-8")
PY
done

echo "== 2/5 rasterizing diagrams =="
python3 publish/scripts/render_diagrams.py "$PUB/src" "$PUB/src-img" "$PUB/images"
SRC_DIR="$PUB/src-img"
[ -d "$SRC_DIR" ] || SRC_DIR="$PUB/src"
mapfile -t SRC_FILES < <(find "$SRC_DIR" -name "*.md" | sort)

echo "== 3/5 building EPUB =="
# epub-titlepage.md, NOT --include-before-body: the epub writer splits output
# into one xhtml file per chapter and re-injects an include into every one.
pandoc publish/metadata.yaml publish/epub-titlepage.md publish/frontmatter.md "${SRC_FILES[@]}" \
  -o "$EPUB" \
  --epub-metadata=publish/epub-metadata.xml \
  --metadata pagetitle="The opencode Book" \
  --toc --toc-depth=2 \
  --epub-chapter-level=2 \
  --css=publish/style.css \
  --epub-cover-image=publish/assets/cover.png \
  --epub-embed-font="$DEJAVU_MONO" \
  --no-highlight

echo "== 4/5 validating EPUB =="
epubcheck "$EPUB"

echo "== 5/5 building PDF =="
# metadata.yaml is omitted here on purpose: its `title` makes pandoc render a
# plain-text title header above the TOC, ahead of the cover image. pagetitle
# sets the document title without emitting that header. Single-document output,
# so --include-before-body fires exactly once.
pandoc publish/frontmatter.md "${SRC_FILES[@]}" \
  -o "$PDF" \
  --include-before-body=publish/coverpage.html \
  --metadata pagetitle="The opencode Book" \
  --metadata lang=en-US \
  --toc --toc-depth=2 \
  --css=publish/style.css --css=publish/style-print.css \
  --pdf-engine=weasyprint \
  --no-highlight

echo
echo "Done:"
echo "  $EPUB"
echo "  $PDF"
