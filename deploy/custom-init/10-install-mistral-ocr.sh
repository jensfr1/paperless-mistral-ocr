#!/bin/bash
# Installiert das Mistral-OCR-Plugin bei jedem Containerstart.
#
# Laeuft ueber den custom-init-Hook des offiziellen paperless-ngx-Images
# (/custom-cont-init.d). Dadurch bleibt das offizielle Image in Benutzung -
# "docker compose pull" funktioniert weiter wie gewohnt, das Plugin wird
# nach jedem Update automatisch neu installiert.
#
# Das Image prueft die Rechte: Verzeichnis und Skript muessen root gehoeren
# und duerfen fuer "others" nicht schreibbar sein, sonst wird nichts
# ausgefuehrt.

set -uo pipefail

QUELLE="/opt/plugins/mistral-ocr-plugin"

if [ ! -d "$QUELLE" ]; then
    echo "[mistral-ocr] $QUELLE nicht gefunden - uebersprungen."
    exit 0
fi

# Immer installieren: pip ist idempotent und erkennt selbst, ob sich etwas
# geaendert hat. Ein Import-Check wuerde eine alte Version stehen lassen,
# wenn der Plugin-Code aktualisiert wurde.
echo "[mistral-ocr] installiere Plugin aus $QUELLE ..."
if ! pip install --no-cache-dir --no-deps --force-reinstall --quiet "$QUELLE"; then
    echo "[mistral-ocr] FEHLER bei der Installation - Paperless laeuft ohne das Plugin weiter."
    exit 0
fi
echo "[mistral-ocr] Installation erfolgreich."

# Verifikation: Das Plugin erbt von einer Core-Klasse. Aendert Paperless
# deren Namen oder Ort, schlaegt der Import fehl und Paperless wuerde
# still auf Tesseract zurueckfallen. Das hier macht es sichtbar.
if (cd /usr/src/paperless/src && python3 -c "from paperless_mistral_ocr.parser import MistralOcrParser") 2>/tmp/mistral-import.err; then
    echo "[mistral-ocr] OK - Parser ist ladbar."
else
    echo "[mistral-ocr] ####################################################"
    echo "[mistral-ocr] WARNUNG: Parser NICHT ladbar - vermutlich hat sich"
    echo "[mistral-ocr] die Paperless-Version geaendert. OCR laeuft ab jetzt"
    echo "[mistral-ocr] wieder ueber Tesseract (schlechtere Qualitaet)."
    echo "[mistral-ocr] Fehler:"
    sed "s/^/[mistral-ocr]   /" /tmp/mistral-import.err | tail -5
    echo "[mistral-ocr] ####################################################"
fi
