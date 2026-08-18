#!/usr/bin/env python3
"""
Rasterize monospace diagrams so they survive e-reader reflow.

Mirrors a directory of markdown into an output directory, converting untagged
fenced code blocks (ASCII/Unicode diagrams, tree listings) into styled PNGs and
replacing them with image references. Language-tagged fenced blocks (real source
code) are always left untouched -- pandoc/CSS handles those as wrapped
<pre><code> with soft-wrap, which keeps them searchable and copyable.

Untagged blocks are only rasterized when leaving them as reflowable text would
actually risk breaking their layout: when a line is wide enough to wrap on a
small screen, or when the block uses box-drawing/arrow characters whose
alignment depends on every glyph having identical monospace width (not
guaranteed by every e-reader font).

Usage:
    render_diagrams.py <src_dir> <out_src_dir> <out_img_dir>

On an obook manuscript this is often a near no-op -- opencode's docs are mostly
tagged code blocks. It stays in the pipeline because the cost of running it is
nil and the cost of shipping a mangled diagram is a bad page in a finished book.
"""
import re
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

_args = sys.argv[1:]
SRC_DIR = Path(_args[0]) if len(_args) > 0 else Path("build/chapters")
OUT_SRC_DIR = Path(_args[1]) if len(_args) > 1 else Path("build/publish/src")
OUT_IMG_DIR = Path(_args[2]) if len(_args) > 2 else Path("build/publish/images")
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

BASE_FONT_SIZE = 32
MIN_FONT_SIZE = 18
# Text-area width budget (excludes padding). Chosen so a full-width diagram
# downscales only mildly on a 7" Kindle Oasis reading pane (~1000-1100px)
# while still looking crisp, near-native, on the 10.2" Scribe.
TARGET_TEXT_WIDTH = 1200
PADDING = 48
BORDER_RADIUS = 16
BG_COLOR = (244, 243, 239)
BORDER_COLOR = (201, 197, 186)
TEXT_COLOR = (43, 43, 43)
LINE_SPACING_FACTOR = 1.35

WIDTH_THRESHOLD = 60
MAX_LINES_FOR_IMAGE = 40
STRUCTURAL_CHARS = set("├─└┌┐│┘┴┬┤→←↓↑—")

# A fence line: optional blockquote markers ("> "), OR whitespace indent,
# then the backtick fence itself.
FENCE_LINE_RE = re.compile(
    r"^(?P<prefix>(?:>[ \t]?)+|[ \t]*)```(?P<lang>[a-zA-Z0-9_+-]*)[ \t]*$"
)

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}
_dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def get_font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(FONT_PATH, size)
    return _font_cache[size]


def char_width(size: int) -> float:
    return _dummy_draw.textlength("M", font=get_font(size))


def pick_font_size(max_chars: int) -> int:
    if max_chars == 0:
        return BASE_FONT_SIZE
    base_width = max_chars * char_width(BASE_FONT_SIZE)
    if base_width <= TARGET_TEXT_WIDTH:
        return BASE_FONT_SIZE
    scale = TARGET_TEXT_WIDTH / base_width
    return max(MIN_FONT_SIZE, int(BASE_FONT_SIZE * scale))


def render_block(lines: list[str]) -> Image.Image:
    lines = [ln.expandtabs(4).rstrip() for ln in lines]
    max_chars = max((len(ln) for ln in lines), default=0)

    size = pick_font_size(max_chars)
    font = get_font(size)
    cw = char_width(size)
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * LINE_SPACING_FACTOR)

    width = PADDING * 2 + int(max_chars * cw)
    height = PADDING * 2 + len(lines) * line_h

    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [2, 2, width - 3, height - 3],
        radius=BORDER_RADIUS,
        outline=BORDER_COLOR,
        width=3,
    )
    for i, line in enumerate(lines):
        draw.text((PADDING, PADDING + i * line_h), line, font=font, fill=TEXT_COLOR)

    return img


def should_rasterize(lines: list[str]) -> bool:
    # Long listings (e.g. a full directory tree) become an unwieldy, tall
    # image that can't paginate. As text they're still safe: the tree
    # branches live in the first ~40 columns, so a wrap only pushes a
    # trailing comment to the next line rather than breaking the hierarchy.
    if len(lines) > MAX_LINES_FOR_IMAGE:
        return False
    if any(len(ln.expandtabs(4)) > WIDTH_THRESHOLD for ln in lines):
        return True
    if any(ch in STRUCTURAL_CHARS for ln in lines for ch in ln):
        return True
    return False


def strip_prefix(line: str, prefix: str) -> str:
    if prefix.startswith(">"):
        # blockquote: strip one "> " (or ">") worth of marker, tolerating
        # a missing trailing space on blank quoted lines
        stripped = line
        for marker in ("> ", ">"):
            if stripped.startswith(marker):
                return stripped[len(marker):]
        return stripped
    # whitespace indent: strip exactly that many characters
    return line[len(prefix):] if line.startswith(prefix) else line.lstrip()


def slugify(rel_path: Path, index: int) -> str:
    stem = str(rel_path.with_suffix("")).replace("/", "_")
    return f"{stem}_diagram{index}.png"


def process_file(md_path: Path, counters: dict) -> int:
    raw_lines = md_path.read_text(encoding="utf-8").split("\n")
    rel = md_path.relative_to(SRC_DIR)
    out_md_path = OUT_SRC_DIR / rel
    out_md_path.parent.mkdir(parents=True, exist_ok=True)

    out_lines = []
    i = 0
    n = len(raw_lines)
    block_count = 0

    while i < n:
        m = FENCE_LINE_RE.match(raw_lines[i])
        if not m:
            out_lines.append(raw_lines[i])
            i += 1
            continue

        prefix, lang = m.group("prefix"), m.group("lang")
        # find matching close: same prefix, bare fence
        close_re = re.compile(r"^" + re.escape(prefix) + r"```[ \t]*$")
        j = i + 1
        while j < n and not close_re.match(raw_lines[j]):
            j += 1

        if j >= n:
            # unterminated fence (shouldn't happen) -- pass through untouched
            out_lines.append(raw_lines[i])
            i += 1
            continue

        body_raw = raw_lines[i + 1 : j]

        if lang:
            # tagged: real code, always keep as text, unmodified
            out_lines.extend(raw_lines[i : j + 1])
            i = j + 1
            continue

        body = [strip_prefix(ln, prefix) for ln in body_raw]

        if not should_rasterize(body):
            out_lines.extend(raw_lines[i : j + 1])
            i = j + 1
            continue

        block_count += 1
        img = render_block(body)
        img_name = slugify(rel, block_count)
        img_path = OUT_IMG_DIR / img_name
        img.save(img_path, "PNG", optimize=True)

        # Absolute path: pandoc resolves relative image paths against its
        # working directory, not each source file's own directory, so a
        # path computed relative to this .md file's location is wrong the
        # moment files from different directories are concatenated together.
        image_line = f"![diagram]({img_path.resolve()})"
        if prefix.startswith(">"):
            out_lines.append(f"> {image_line}")
        else:
            out_lines.append(image_line)

        counters["total"] += 1
        i = j + 1

    out_md_path.write_text("\n".join(out_lines), encoding="utf-8")
    return block_count


def main():
    if not SRC_DIR.exists():
        sys.exit(f"source dir not found: {SRC_DIR}")
    OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_SRC_DIR.mkdir(parents=True, exist_ok=True)

    counters = {"total": 0}
    files = sorted(SRC_DIR.rglob("*.md"))
    for md_path in files:
        n = process_file(md_path, counters)
        if n:
            print(f"{md_path.relative_to(SRC_DIR)}: {n} diagram(s)")

    print(f"\n{len(files)} files processed, {counters['total']} diagrams rendered to {OUT_IMG_DIR}")


if __name__ == "__main__":
    main()
