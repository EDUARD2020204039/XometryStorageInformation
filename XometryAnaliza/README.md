# XometryAnaliza

Serviciu de agenti pentru ofertele Xometry.

Flux:

- `RouterAgent` primeste joburile de la scraper.
- `CncAgent` marcheaza joburile CNC pentru analiza separata.
- `SheetMetalLaserAgent` trimite ofertele sheet/laser/bending catre Ofertare-Automata, care genereaza `.geo`.
- evenimentele se scriu in `/app/data/agent_events.jsonl` si se pot trimite pe Telegram.

Endpointuri:

- `GET /health`
- `POST /api/agents/jobs` cu payload `{ "source": "scraper", "jobs": [{ ... }] }`
- `GET /api/agents/logs`
- `GET /api/agents/jobs`
- `GET /api/agents/geo/{offer_id}`

## Istoric si versionare

- Evolutia codului se pastreaza in Git/GitHub prin commit-uri. Cand revine un prompt nou, istoricul real al implementarii se verifica din `git log`, nu din memorie.
- Evolutia joburilor procesate se pastreaza in `/app/data/jobs/*.json`.
- Evenimentele operationale se scriu in `/app/data/agent_events.jsonl` si apar in dashboard/loguri.
- Diagnozele TecZone/Xometry se scriu in dosarul proiectului cand exista acces la el sau, ca fallback, in `/app/data/diagnostics/<job_id>/`.

## Structura dosar proiect

Structura recomandata pentru dosarele create/procesate de XometryAnaliza:

- `DOC`: documentatia originala si fisierele sursa primite/descarcate.
- `OFERTA`: fisierele finale folosite pentru ofertare si predare interna.
- `WORK`: fisiere tehnice/intermediare folosite de automatizare ca sa poata relua sau verifica fluxul. Nu este dosar de lucru manual zilnic.
- `EROARE`: se creeaza doar cand apare o problema. Aici intra capturi, urme de rulare si rapoarte de diagnoza.

`DOC` si `OFERTA` sunt folderele utile pentru lucrul normal. `WORK` si `EROARE` sunt foldere de suport pentru automatizare/debug si pot fi ignorate cand fluxul este curat.

## Diagnoza TecZone/Hermes

Cand `SheetMetalLaserAgent` termina cu un status care nu este `geo_ready`, aplicația creeaza un raport de diagnostic. Raportul clasifica local cauze precum login Xometry, documentatie lipsa, token Ofertare invalid, mapare de cale sau geometrie care nu se poate desfasura.

Daca sunt setate variabilele `HERMES_AGENT_URL` si `HERMES_API_KEY`, raportul se trimite si catre Hermes prin endpoint compatibil OpenAI `POST /v1/chat/completions`.
