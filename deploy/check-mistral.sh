#!/bin/bash
# Prueft, ob das Mistral-OCR-Plugin aktiv ist.
# Aufruf: /opt/pruefe-mistral.sh
# Exitcode 0 = alles gut, 1 = Plugin inaktiv (Paperless nutzt Tesseract).

CONTAINER="paperless-webserver-1"
fehler=0

echo "=== Mistral-OCR-Status $(date '+%F %T') ==="

if ! docker ps --filter "name=$CONTAINER" --format '{{.Names}}' | grep -q .; then
    echo "  FEHLER: Container $CONTAINER laeuft nicht."
    exit 1
fi

version=$(docker exec "$CONTAINER" pip show paperless-mistral-ocr 2>/dev/null | awk '/^Version:/{print $2}')
if [ -n "$version" ]; then
    echo "  Plugin installiert:  ja (v$version)"
else
    echo "  Plugin installiert:  NEIN"
    fehler=1
fi

if docker exec -w /usr/src/paperless/src "$CONTAINER" python3 -c "from paperless_mistral_ocr.parser import MistralOcrParser" 2>/dev/null; then
    echo "  Parser ladbar:       ja"
else
    echo "  Parser ladbar:       NEIN  <-- vermutlich durch ein Paperless-Update gebrochen"
    fehler=1
fi

if docker exec "$CONTAINER" sh -c '[ -n "$PAPERLESS_MISTRAL_OCR_API_KEY" ]' 2>/dev/null; then
    echo "  API-Schluessel:      gesetzt"
else
    echo "  API-Schluessel:      FEHLT  <-- ohne ihn meldet sich der Parser ab"
    fehler=1
fi

letzte=$(docker logs "$CONTAINER" 2>&1 | grep -c "handled by third-party parser 'Mistral OCR Parser'")
echo "  Von Mistral verarbeitet (seit Containerstart): $letzte Dokument(e)"

if [ "$fehler" -eq 0 ]; then
    echo "  ERGEBNIS: Mistral OCR ist aktiv."
else
    echo "  ERGEBNIS: Mistral OCR ist INAKTIV - Paperless nutzt Tesseract."
    echo "            Neu einrichten: siehe /opt/paperless-ngx/plugins/mistral-ocr-plugin/EINRICHTUNG.md"
fi
exit $fehler
