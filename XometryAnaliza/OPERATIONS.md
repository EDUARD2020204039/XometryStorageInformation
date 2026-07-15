# XometryAnaliza Operations Runbook

Ultima verificare manuala: 2026-07-15 21:51 +03:00.

## Verificare rapida

1. Health aplicatie:
   `GET http://192.168.2.23:4468/health`

2. Watchdog:
   `GET http://192.168.2.23:4468/api/watchdog`
   `GET http://192.168.2.23:4468/api/watchdog/view`

3. Coada live:
   `GET http://192.168.2.23:4468/api/queue/live`

4. Istoric:
   `GET http://192.168.2.23:4468/api/agents/history/view`

5. Metrici Prometheus:
   `GET http://192.168.2.23:4468/metrics`

## Cum interpretam statusurile

- `geo_ready`: exista cel putin un fisier `.geo` confirmat pe disk.
- `geo_requested`: TecZone a primit/planificat export GEO, dar fisierul nu este confirmat gata. Acest status trebuie sa fie tranzitoriu sau investigat.
- `failed`: TecZone/Ofertare a esuat explicit. Exemple: nu poate deschide STEP-ul, nu poate exporta GEO, eroare interactiva TecZone.
- `blocked_documentation`: Xometry nu a livrat documentatie/STEP suficienta pentru procesare.
- `blocked_login`: browserul de pe laptopul de ofertare a ajuns la login Xometry.
- `agent_busy`: laptopul TecZone/Ofertare proceseaza deja alt job si coada trebuie sa reia mai tarziu.

## Semne ca aplicatia nu este moarta, dar fluxul nu produce GEO

- `/health` este OK.
- `/api/watchdog` este OK.
- `/api/queue/live` are `queued_count=0`, `running=false`, dar istoricul are multe `geo_requested` cu `ready_geo_count=0`.
- In log apar mesaje de forma `Nu am reusit sa deschid fisierul sursa in TecZone`.

In cazul acesta problema este in fluxul TecZone/STEP, nu in API-ul XometryAnaliza. Jobul trebuie marcat `failed`, nu `geo_requested`.

## Metrici utile

- `xometryanaliza_up`: 1 inseamna ca serviciul raspunde.
- `xometryanaliza_queue_jobs{state="queued"}`: cate joburi asteapta.
- `xometryanaliza_queue_running`: daca workerul XometryAnaliza ruleaza.
- `xometryanaliza_queue_worker_alive`: daca thread-ul cozii este viu.
- `xometryanaliza_jobs_total{status="..."}`: distributia istorica pe status.
- `xometryanaliza_geo_files_total{state="ready"}` versus `{state="requested"}`: diferenta mare inseamna ca se cer GEO-uri, dar nu se confirma pe disk.
- `xometryanaliza_events_recent_total{type="..."}`: tipuri de evenimente recente.

## Cand avem nevoie de loguri Docker

Daca API-ul raspunde, se folosesc endpointurile de mai sus.

Daca API-ul nu raspunde sau containerul reporneste, este nevoie de SSH pe Unraid:

- host: `192.168.2.23`
- user: `root`
- comenzi utile:
  - `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`
  - `docker logs --tail 200 XometryAnaliza`
  - `docker logs --tail 200 XometryBot`
  - `docker logs --tail 200 XometryScraper`

Parolele nu se trec in documentatie; se iau din canalul sigur folosit pentru administrare.

## Linear

Linear este util pentru urmarire de bug-uri, decizii si prioritati, dar nu inlocuieste observabilitatea tehnica.

Recomandare:

- task-uri si bug-uri in Linear;
- runbook-uri si decizii tehnice in repo;
- loguri runtime in XometryAnaliza + Prometheus/Grafana;
- incidente majore: un ticket Linear cu link catre `/api/watchdog/view`, `/api/agents/history/view` si commit-ul care a reparat problema.
