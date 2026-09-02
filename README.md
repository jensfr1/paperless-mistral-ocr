# paperless-mistral-ocr

[Mistral OCR](https://mistral.ai/news/mistral-ocr) (`mistral-ocr-latest`) as an
OCR engine for [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) —
shipped as a plugin, with no changes to the core and no custom Docker image
required.

## Why

Paperless-ngx 3.1 ships a remote OCR parser, but it only supports Azure AI
Document Intelligence. Since 3.1 there is also an official plugin interface for
parsers via the `paperless_ngx.parsers` entrypoint group. This package uses it
instead of forking the core: no self-built image, no merge conflicts on updates.

The OCR logic originates from
[PR paperless-ngx#13085](https://github.com/paperless-ngx/paperless-ngx/pull/13085).

## What it does

Mistral returns markdown text plus paragraph-level bounding boxes, but no PDF.
The searchable archive is therefore assembled locally:

1. Each page of the original is rasterised at 200 dpi
2. An invisible text layer is positioned from the bounding boxes
3. ocrmypdf's fpdf2 renderer draws image and text layer together
4. `pikepdf` merges the pages into the final PDF

Note that ocrmypdf is used **purely as a renderer** here — no OCR engine is
involved, Tesseract is not called at all.

Born-digital PDFs for which Paperless requests no archive are never uploaded,
which saves both money and a redundant second text layer.

## Results

Measured on 16 real-world German documents (47 pages), comparing the stored
Tesseract text against Mistral:

| | |
|---|---|
| Total text | 74,944 → **83,223 characters** (+11 %) |
| Additional monetary amounts found | **7** |
| Failures | 0 |
| Time per document | 2.6 – 8.9 s |

The character count understates the difference. What actually changes is that
words survive intact. Typical failure modes seen in the sample, with the
specifics generalised:

| Failure mode | Tesseract | Mistral |
|---|---|---|
| Street name in a letterhead | umlaut dropped, letters swapped | read correctly |
| Long compound noun across a line break | split into two fragments | reassembled |
| Compound with hyphenation | `gesetzli` + `chen` | `gesetzlichen` |
| Low-contrast stamp | ignored entirely | read including the amount |
| Noisy margin | `rrrrrr` | *(nothing — correctly ignored)* |

German compounds are where this hurts most: Tesseract breaks them at line ends
and hyphenation, Mistral reassembles them. For full-text search that is the real
win — a document containing a 20-character compound noun was simply not findable
by searching for that word before.

Two concrete error classes it fixed in the sample:

- A **decimal digit misread** in a form table (`4.25` where the document said
  `1.25`) — the kind of error that is invisible unless you compare against the
  scan
- A **stamped amount** that Tesseract skipped entirely, so the value never
  entered the index

## Requirements

- Paperless-ngx **3.1** or newer (needs the parser plugin interface)
- A [Mistral API key](https://console.mistral.ai/)

No extra Python packages: httpx, pikepdf, ocrmypdf, Pillow and pdf2image all
ship with the official paperless-ngx image.

## Installation

### Without a custom image (recommended)

The official image runs every script in `/custom-cont-init.d/` on start, so the
plugin reinstalls itself on every container start — including after updates.
`docker compose pull` keeps working as usual.

```bash
# 1. Copy the plugin onto the server
scp -r paperless-mistral-ocr your-server:/opt/paperless-ngx/plugins/

# 2. Install the init hook (must be owned by root, not world-writable)
ssh your-server '
  mkdir -p /opt/paperless-ngx/custom-init
  cp /opt/paperless-ngx/plugins/paperless-mistral-ocr/deploy/custom-init/*.sh \
     /opt/paperless-ngx/custom-init/
  chown -R root:root /opt/paperless-ngx/custom-init
  chmod 755 /opt/paperless-ngx/custom-init
  chmod 744 /opt/paperless-ngx/custom-init/*.sh
'
```

Then add the mounts to the `webserver` service in `docker-compose.yml`:

```yaml
    volumes:
      - /opt/paperless-ngx/custom-init:/custom-cont-init.d:ro
      - /opt/paperless-ngx/plugins:/opt/plugins:ro
```

Set the API key in `docker-compose.env` and restart:

```bash
PAPERLESS_MISTRAL_OCR_API_KEY=your-key-here
```

The log must show:

```
[mistral-ocr] Installation successful.
[mistral-ocr] OK - parser loads.
Loaded third-party parser 'Mistral OCR Parser' v0.2.0
```

> **Line endings matter.** The shell scripts need Unix line endings (LF). If
> they are edited on Windows and transferred with CRLF, the init hook aborts
> with `$'\r': command not found` — Paperless then starts normally but
> **without** the plugin and silently falls back to Tesseract. Transfer safely
> with `cat script.sh | ssh host "tr -d '\r' > /target/path"`.

### With a custom image

Only worth it if the container starts without network access, or the few
seconds of install time on startup bother you. See [deploy/Dockerfile](deploy/Dockerfile).
The downside: you have to rebuild on every Paperless update, `docker compose
pull` no longer gets you new versions.

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `PAPERLESS_MISTRAL_OCR_API_KEY` | yes | – | API key. Without it the parser declines and Paperless keeps using Tesseract. |
| `PAPERLESS_MISTRAL_OCR_ENDPOINT` | no | `https://api.mistral.ai` | For self-hosted deployments. |
| `PAPERLESS_MISTRAL_OCR_MODEL` | no | `mistral-ocr-latest` | Model identifier. |
| `PAPERLESS_MISTRAL_OCR_SCORE` | no | `30` | Priority. The built-in remote parser scores 20, Tesseract 10 — higher wins. |
| `PAPERLESS_MISTRAL_OCR_PREPROCESS` | no | `true` | Run ocrmypdf first to deskew and rotate pages, so the archive PDF is upright. Costs roughly 8 s per document. |
| `PAPERLESS_MISTRAL_OCR_FALLBACK` | no | `true` | Fall back to Tesseract when the API call fails, instead of storing empty text. |

Registered MIME types: PDF, PNG, JPEG, TIFF, BMP, GIF, WebP.

## Health check

```bash
./deploy/check-mistral.sh
```

```
Plugin installed:  yes (v0.2.0)
Parser loads:      yes
API key:           set
RESULT: Mistral OCR is active.
```

Exit code 0 when active, 1 otherwise — suitable for a cron job alongside your
backup.

## FAQ

### Do I lose any functionality compared to Tesseract?

Two of the three original trade-offs are handled by the plugin; one remains.

**Page rotation and deskewing: handled.** `PAPERLESS_OCR_DESKEW` and
`PAPERLESS_OCR_ROTATE_PAGES` are options of the ocrmypdf *pipeline*, and that
pipeline does not run here — ocrmypdf only renders. Left alone, a sideways scan
would stay sideways in the archive.

The plugin therefore runs ocrmypdf as a geometry-only pass before the API call
(`PAPERLESS_MISTRAL_OCR_PREPROCESS`, on by default). `tesseract_timeout=0` stops
it from adding its own text layer, so only the page images are corrected and the
text still comes from Mistral. Verified on a document scanned 90° sideways: the
archive comes out upright and fully readable. Costs about 8 seconds per document.

Worth knowing: Mistral reads rotated pages correctly *either way*. On that same
sideways scan Tesseract returned nothing but mirrored character noise, while
Mistral reconstructed the full table from the un-rotated original. The
preprocessing pass is about how the PDF *looks* when you page through it, not
about text quality — so if you never look at your scans, you can turn it off and
save the time.

**Archive PDFs get roughly 4× larger** (~115 KB → ~500 KB in our samples),
because every page is re-rasterised at 200 dpi instead of reusing the original
PDF. This one has no workaround; it follows from how the text layer is built.

**`PAPERLESS_OCR_LANGUAGE` is ignored.** Mistral detects the language itself.
For mixed-language archives this is an advantage rather than a loss.

Unaffected: thumbnails, page counting, date detection from text, metadata
extraction, and your existing tags and correspondents. PDF/A is not produced —
but note that Paperless only produces PDF/A when `output_type` is set
accordingly; with the default `pdf` nothing changes here.

### What happens if the Mistral API is unreachable?

Tesseract takes over for that document (`PAPERLESS_MISTRAL_OCR_FALLBACK`, on by
default). You get the same result you would have had without the plugin, and a
warning in the log.

This matters because the parser registry picks an engine *before* processing and
does not retry with a different one on failure. Without the fallback the
document would be stored with **empty text** — silently, since consumption
itself still succeeds. If you would rather have the failure be loud, set
`PAPERLESS_MISTRAL_OCR_FALLBACK=false`.

### Does my data leave my server?

Yes. Document contents are sent to Mistral (an EU provider, which may matter for
GDPR compared to US-based services). Mistral OCR can also be self-hosted; point
`PAPERLESS_MISTRAL_OCR_ENDPOINT` at your own deployment in that case.

### What does it cost?

Roughly 1 USD per 1,000 pages at the time of writing. For a private archive of a
few dozen documents a month this is negligible.

### Will it survive Paperless updates?

The install hook runs on every container start, so normally yes. The plugin
subclasses `paperless.parsers.remote.RemoteDocumentParser` though — if upstream
renames or moves that class, the import breaks. That case is handled loudly
rather than silently: the init hook verifies the import and logs a prominent
warning, and `check-mistral.sh` reports it. Paperless keeps running on Tesseract
in the meantime, so nothing breaks, it just stops getting better.

### Can I convert existing documents?

Yes, per document:

```bash
docker exec -u paperless -w /usr/src/paperless/src paperless-webserver-1 \
  python3 manage.py document_archiver -f -d <DOCUMENT_ID>
```

This replaces text and archive PDF; the original scan and all metadata stay
untouched. Back up first — `document_exporter` or a database dump.

## Background

The OCR logic was originally written for the core and submitted upstream as
[paperless-ngx#13085](https://github.com/paperless-ngx/paperless-ngx/pull/13085).
An automated filter closed that PR 17 seconds after it was opened, before any
human review — the CI checks that ran afterwards passed.

In hindsight that turned out for the better: since 3.1 the parser plugin
interface exists, and a plugin is the more appropriate shape for this anyway.
No core patch to keep rebasing, and users can adopt it without waiting on a
release cycle.

## Contributing

Issues and pull requests are welcome. Run the checks before submitting:

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests && pytest -q
```

## License

GPL-3.0-or-later, same as Paperless-ngx.
