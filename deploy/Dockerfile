# Paperless-ngx mit Mistral-OCR-Plugin.
#
# Bei Paperless-Updates aendert sich nur die FROM-Zeile - der Plugin-Code
# bleibt unberuehrt. Kein Fork, keine Merge-Konflikte.
#
#   docker build -t paperless-mistral:latest .
FROM paperlessngx/paperless-ngx:latest

COPY pyproject.toml README.md /opt/mistral-ocr-plugin/
COPY src /opt/mistral-ocr-plugin/src

RUN pip install --no-cache-dir --no-deps /opt/mistral-ocr-plugin
