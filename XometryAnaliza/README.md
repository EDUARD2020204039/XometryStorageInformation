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
