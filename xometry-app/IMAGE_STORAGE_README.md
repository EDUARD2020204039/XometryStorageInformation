# Stocarea Locală a Imaginilor

## Problema Rezolvată

Imaginile reperelor din ofertele Xometry erau stocate ca URL-uri externe (de obicei de la Amazon S3) care expirau după un timp, cauzând afișarea mesajului "Imagine expirată" în interfață.

## Soluția Implementată

Am implementat un sistem de stocare locală pentru imaginile reperelor care:

1. **Descarcă automat imaginile** când se salvează o ofertă nouă
2. **Stochează imaginile local** pe serverul nostru în directorul `static/images/parts/`
3. **Organizează imaginile** pe directoare separate pentru fiecare ofertă
4. **Prioritizează imaginile locale** în interfață, cu fallback la URL-urile externe
5. **Curăță imaginile vechi** care nu mai sunt folosite

## Structura Fișierelor

```
static/images/parts/
├── {offer_id_1}/
│   ├── {part_id_1}_{hash}.jpg
│   └── {part_id_2}_{hash}.jpg
├── {offer_id_2}/
│   └── {part_id_1}_{hash}.jpg
└── ...
```

## Modificări Implementate

### 1. Modelul de Date
- Adăugat câmpul `local_image_path` în tabelul `parts`
- Migrarea bazei de date executată automat

### 2. Utilitare pentru Imagini (`xometry/image_utils.py`)
- `download_and_save_image()` - Descarcă și salvează imagini local
- `get_image_path()` - Returnează calea optimă către imagine
- `cleanup_old_images()` - Șterge imaginile vechi nefolosite

### 3. Logica de Salvare (`app.py`)
- Descărcarea automată a imaginilor la salvarea ofertelor
- Actualizarea câmpului `local_image_path` în baza de date
- Curățarea imaginilor vechi

### 4. Template-uri
- Prioritatea imaginilor locale în `index.html` și `offer_detail.html`
- Fallback la URL-uri externe dacă imaginea locală nu există
- Afișarea mesajului "Imagine expirată" doar pentru URL-uri externe

### 5. Endpoint-uri Noi
- `GET /images/parts/{offer_id}/{filename}` - Servește imaginile locale
- `POST /api/migrate-images` - Migrează imaginile existente

## Utilizare

### Pentru Oferte Noi
Imaginile se descarcă automat când se salvează o ofertă nouă prin extensia Chrome.

### Pentru Oferte Existente
Pentru a migra imaginile existente, apelați endpoint-ul:
```bash
curl -X POST http://localhost:8000/api/migrate-images
```

### Verificare Status
Imaginile locale au prioritate în interfață. Dacă o imagine locală există, aceasta va fi afișată. Altfel, se va încerca URL-ul extern.

## Avantaje

1. **Imaginile nu mai expiră** - sunt stocate permanent pe serverul nostru
2. **Performanță îmbunătățită** - imaginile locale se încarcă mai rapid
3. **Control complet** - nu depindem de serviciile externe
4. **Curățare automată** - imaginile vechi se șterg automat
5. **Fallback robust** - dacă descărcarea eșuează, se păstrează URL-ul extern

## Configurare

Nu sunt necesare configurații suplimentare. Sistemul funcționează automat după migrarea bazei de date.

## Monitorizare

Logurile aplicației vor afișa:
- Imagini descărcate cu succes
- Erori la descărcarea imaginilor
- Imagini vechi șterse
- Statistici de migrare
