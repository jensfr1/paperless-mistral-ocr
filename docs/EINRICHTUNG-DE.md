# Einrichtung auf dem Debian-Server

Getestet gegen Paperless-ngx 3.1. Es gibt zwei Wege — **Weg A wird empfohlen**,
weil das offizielle Image in Benutzung bleibt.

## Weg A: Ohne eigenes Image (empfohlen)

Das offizielle Image führt beim Start alle Skripte aus `/custom-cont-init.d/`
aus. Das Plugin wird dadurch bei jedem Containerstart installiert — auch nach
jedem Update. `docker compose pull` funktioniert weiter wie gewohnt.

### 1. Dateien auf den Server

    scp -r mistral-ocr-plugin dein-server:/opt/paperless-ngx/plugins/

### 2. Rechte setzen (zwingend)

Das Image verweigert die Ausführung, wenn das Hook-Verzeichnis nicht root
gehört oder für andere schreibbar ist:

    ssh dein-server '
      mkdir -p /opt/paperless-ngx/custom-init
      cp /opt/paperless-ngx/plugins/mistral-ocr-plugin/custom-init/*.sh /opt/paperless-ngx/custom-init/
      chown -R root:root /opt/paperless-ngx/custom-init
      chmod 755 /opt/paperless-ngx/custom-init
      chmod 744 /opt/paperless-ngx/custom-init/*.sh
    '

### 3. Mounts in docker-compose.yml

Beim Dienst `webserver` unter `volumes:` ergänzen:

    - /opt/paperless-ngx/custom-init:/custom-cont-init.d:ro
    - /opt/paperless-ngx/plugins:/opt/plugins:ro

### 4. API-Schlüssel

In `/opt/paperless-ngx/docker-compose.env`:

    PAPERLESS_MISTRAL_OCR_API_KEY=<Schlüssel>

### 5. Starten

    ssh dein-server 'cd /opt/paperless-ngx && docker compose up -d'

Im Log müssen zwei Zeilen erscheinen:

    [custom-init] 10-install-mistral-ocr.sh: executing...
    Loaded third-party parser 'Mistral OCR Parser' v0.3.0

## Weg B: Eigenes Image

Nur sinnvoll, wenn der Container ohne Netzzugang startet oder die paar Sekunden
Installationszeit beim Start stören.

    ssh dein-server 'cd /opt/paperless-ngx/plugins/mistral-ocr-plugin && docker build -t paperless-mistral:latest .'

Dann in `docker-compose.yml` beim Dienst `webserver`:

    image: paperless-mistral:latest

Nachteil: Bei jedem Paperless-Update musst du selbst neu bauen; `docker compose
pull` holt keine neuen Versionen mehr.

## Konfiguration

| Variable | Pflicht | Standard |
|---|---|---|
| `PAPERLESS_MISTRAL_OCR_API_KEY` | ja | – |
| `PAPERLESS_MISTRAL_OCR_ENDPOINT` | nein | `https://api.mistral.ai` |
| `PAPERLESS_MISTRAL_OCR_MODEL` | nein | `mistral-ocr-latest` |
| `PAPERLESS_MISTRAL_OCR_SCORE` | nein | `30` |

## Zurückrollen

Am einfachsten: den API-Schlüssel aus der env-Datei entfernen und neu starten.
Ohne Schlüssel meldet sich der Parser bei der Registry ab, Tesseract übernimmt
wieder — das Plugin bleibt installiert, ist aber wirkungslos.

Vollständig entfernen: die beiden Mount-Zeilen aus der `docker-compose.yml`
löschen und neu starten.

## Nach Paperless-Updates prüfen

Das Plugin erbt von `paperless.parsers.remote.RemoteDocumentParser`. Ändert sich
diese Klasse, kann das Plugin brechen. Nach einem Update einmal:

    ssh dein-server 'docker logs paperless-webserver-1 2>&1 | grep -i "third-party parser\|mistral-ocr"'

Erscheint die "Loaded third-party parser"-Zeile nicht, läuft Paperless still auf
Tesseract weiter — es geht also nichts kaputt, es wird nur nicht mehr besser.

## Achtung bei der Übertragung: Zeilenenden

Die Shell-Skripte **müssen** Unix-Zeilenenden (LF) haben. Werden sie unter
Windows bearbeitet und mit CRLF übertragen, bricht der Init-Hook mit
`$'\r': command not found` ab — Paperless startet dann normal, aber **ohne**
das Plugin, und fällt still auf Tesseract zurück.

Sicher übertragen:

    cat custom-init/10-install-mistral-ocr.sh | ssh dein-server "tr -d '\r' > /opt/paperless-ngx/custom-init/10-install-mistral-ocr.sh"

Prüfen (muss 0 ergeben):

    ssh dein-server 'tr -cd "\r" < /opt/paperless-ngx/custom-init/10-install-mistral-ocr.sh | wc -c'

## Statusprüfung

    ssh dein-server '/opt/pruefe-mistral.sh'

Läuft zusätzlich automatisch beim wöchentlichen Backup (sonntags 03:30) und
schreibt das Ergebnis nach `/var/log/paperless-backup.log`.
