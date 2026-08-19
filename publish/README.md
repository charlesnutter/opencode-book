# publish — chapters to EPUB and PDF

> **Status: work in progress. Not yet run end-to-end.**
>
> This directory records the *intended approach* for the final stage, not a
> finished implementation. The pandoc setup in particular needs further
> evaluation and refactoring before it should be trusted:
>
> - It was written against a different input shape (77 hand-authored files) and
>   re-pointed at opencode-book's output without a full test run.
> - The EPUB and PDF invocations duplicate a lot of flags and have drifted
>   apart; they should share one config rather than two near-copies.
> - Whether pandoc is even the right tool here is worth revisiting — the
>   diagram/rasterization workaround exists to route around its reflow
>   behaviour, and a different toolchain might not need it at all.
> - Several stages are unverified against generated chapters (diagram
>   heuristics, TOC depth, chapter splitting).
>
> Treat the **gotchas section below as the durable value here** — those are
> confirmed findings. Treat the scripts as a starting point to be rewritten.

This is the intended final stage of opencode-book: once `opencode-book build` has generated
grounded chapters, this converts them into formats you can actually read on a
device or hand to someone.

```
opencode docs  ->  opencode-book build  ->  build/*.md  ->  publish  ->  .epub / .pdf
```

## Provenance

This approach was worked out end-to-end on a different corpus first — the
community-written *Deep Dive into OpenCode* book, converted from a cloned repo
into a Kindle-ready EPUB and a 755-page PDF. That original pipeline lives at
`~/dev/opencode/epub-build/` (untracked, inside a clone of someone else's
repo — so treat it as scratch, not as a home).

The code here is carried over from that working pipeline but **adapted to
opencode-book's output shape**, and it has not yet been run end-to-end against
opencode-book-generated chapters. The *approach* is proven; the wiring is not. Expect to
debug the first run.

## Running it

```bash
# from repo root, after `opencode-book build`
docker build -t ocbook-publish publish/
docker run --rm -v "$(pwd):/work" ocbook-publish bash /work/publish/build.sh
```

Outputs land in `build/publish/`.

Before the first run you need four files this directory does not ship, because
they're yours to write:

| File | What it is |
|---|---|
| `publish/assets/cover.png` | cover image, ~1600×2560 (5:8) |
| `publish/metadata.yaml` | just `lang: en-US` — see gotcha 3 |
| `publish/epub-metadata.xml` | `<dc:title>`, `<dc:creator>`, `<dc:rights>` |
| `publish/epub-titlepage.md` | hidden `#` heading + cover image (gotcha 4) |
| `publish/frontmatter.md` | "about this edition", structure overview |

## The pipeline

1. **Collect chapters** — read `build/*.md`, strip opencode-book's build-stamp comment.
2. **Rasterize diagrams** — untagged fenced blocks that would break under
   reflow become PNGs; tagged code blocks stay as selectable text.
3. **Build EPUB** — pandoc, with TOC, embedded mono font, cover.
4. **Validate** — `epubcheck`, which must pass clean before you sideload.
5. **Build PDF** — pandoc via weasyprint, with print-specific CSS.

### Why diagrams get split two ways

Real code stays text: it should be searchable, copyable, and allowed to soft-wrap.
Monospace *diagrams* — box drawings, tree listings, aligned columns — break
badly when a reader reflows them, because alignment depends on every glyph being
the same width, which no e-reader guarantees. So those become images.

The heuristic is in `scripts/render_diagrams.py`: rasterize an untagged block if
any line exceeds ~60 chars, or if it contains box-drawing/arrow characters — but
**not** if it exceeds ~40 lines, since a very tall image can't paginate and is
worse as a picture than as text.

## Gotchas that cost real time

These were all found the hard way. They will bite again on a fresh machine.

1. **Debian's `epubcheck` package is broken.** `/usr/bin/epubcheck` is a symlink
   to the jar itself, not a launcher, so it won't run as a command. The
   Dockerfile replaces it with a wrapper. Careful: a naive `> /usr/bin/epubcheck`
   follows the symlink and destroys the jar — remove the symlink first.

2. **`@page` CSS fails epubcheck.** Nested paged-media syntax
   (`@page { @bottom-center { ... } }`) is valid for print but epubcheck's CSS
   parser rejects it. Keep all print rules in `style-print.css`, applied only to
   the PDF build. EPUB readers ignore `@page` anyway.

3. **`--include-before-body` multiplies in EPUB.** The epub writer splits output
   into one xhtml file per chapter and injects the include into *every one* — so
   the cover image appeared on all 442 pages. For EPUB, prepend a title-page
   markdown file as a normal input instead. For PDF (single document) the
   include is fine.

4. **An image-only section gets an empty `<h1>`,** which fails epubcheck with
   "Anchors within nav elements must contain text." Give the title page a real
   heading and hide it with CSS (`.hidden-heading { display: none }`).

5. **`title:` in metadata.yaml emits a visible title header** above the TOC in
   PDF, landing ahead of your cover page. Use `--metadata pagetitle=` for the
   PDF and keep `title` only in the EPUB's `epub-metadata.xml`.

6. **Print pages are narrower than Kindle reflow width.** Diagrams that fit fine
   on a Kindle wrapped mid-structure in the PDF. Fix is a smaller `pre`
   font-size in `style-print.css` (0.68em worked), not a wider page.

7. **Pandoc resolves relative image paths against its working directory,** not
   each source file's location. Once you concatenate files from several
   directories, relative image refs break. Emit absolute paths.

## One EPUB for both Kindles

EPUB is reflowable, so a 7" Oasis and a 10.2" Scribe both apply their own font
and margin settings — you do not need two builds. What you need is CSS that
never forces a fixed width: `pre-wrap` on code, `max-width: 100%` on images, no
fixed-width tables. The two risky content types are long code lines and diagram
images, which is exactly what steps 2 and 6 above address.

Test on the **Oasis at default font size** — the smallest realistic reading
pane. If it's legible there, the Scribe is fine.

## Other formats

Everything below starts from the same generated markdown:

- **AZW3** (pre-2022 Kindle firmware) —
  `ebook-convert book.epub book.azw3 --output-profile=kindle_pw3`.
  Recent Kindles take EPUB directly via Send-to-Kindle or USB, so this is only
  for older devices.
- **HTML (single page)** — `pandoc … -o book.html --standalone --toc --css=…`
- **Static site** — feed `build/*.md` to Astro Starlight, mdBook, or Docusaurus.
  Chapter files are already ordered by filename prefix.
- **DOCX** (for editors who redline) — `pandoc … -o book.docx`
- **LaTeX/print PDF** — swap `--pdf-engine=weasyprint` for `xelatex` if you need
  real typesetting; expect to fight it over code block formatting.

## Licensing

The generated prose is yours. Two things are not automatically:

- opencode's docs are **MIT** (`anomalyco/opencode`), so quoting and building on
  them is fine with attribution — `corpus/lock.json` pins the exact commit.
- Any **third-party sources** you add to the corpus are a separate question. The
  verbatim quotes live in `claims.json` and the prose paraphrases, which helps,
  but if you publish, look at it properly.

Note that the *Deep Dive into OpenCode* book this pipeline was originally built
for has **no license file at all** — default all-rights-reserved. That's a
reason to generate your own text rather than redistribute theirs.
