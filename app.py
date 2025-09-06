"""
Aplicația FastAPI pentru gestionarea ofertelor Xometry
"""
import os
import logging
from typing import List, Optional
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import pandas as pd
from pathlib import Path

from xometry.db import init_db, get_db
from xometry.models import Offer, Part, Attachment

# Încarcă variabilele de mediu
load_dotenv()

# Configurare logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inițializează FastAPI
app = FastAPI(title="Xometry Offer Helper", version="1.0.0")

# Configurare CORS pentru extensia Chrome
app.add_middleware(
    CORSMiddleware,
    allow_origins=["chrome-extension://*", "http://localhost:*", "http://127.0.0.1:*", "http://86.123.232.23:*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inițializează baza de date
database_url = os.getenv('DATABASE_URL', 'sqlite:///xometry_offers.db')
init_db(database_url)

# Configurare template-uri și fișiere statice
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    """Eveniment la pornirea aplicației"""
    logger.info("Aplicația Xometry Offer Helper a pornit")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    """Pagina principală cu lista ofertelor"""
    try:
        # Obține toate ofertele
        offers = db.query(Offer).order_by(Offer.created_at.desc()).all()
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "offers": offers
        })
    except Exception as e:
        logger.error(f"Eroare la încărcarea paginii principale: {e}")
        raise HTTPException(status_code=500, detail="Eroare internă")

@app.get("/offer/{offer_id}", response_class=HTMLResponse)
async def offer_detail(request: Request, offer_id: int, db: Session = Depends(get_db)):
    """Pagina de detalii pentru o ofertă"""
    try:
        # Obține oferta
        offer = db.query(Offer).filter(Offer.id == offer_id).first()
        if not offer:
            raise HTTPException(status_code=404, detail="Oferta nu a fost găsită")
            
        # Obține reperele
        parts = db.query(Part).filter(Part.offer_id == offer_id).all()
        
        # Verifică și curăță datele înainte de a le trimite la template
        for part in parts:
            # Asigură-te că toate câmpurile numerice au valori valide
            if part.unit_price is None:
                part.unit_price = 0.0
            if part.discount is None:
                part.discount = 0.0
            if part.quantity is None:
                part.quantity = 1
            if part.total_price is None:
                part.total_price = 0.0
            if part.lead_time is None:
                part.lead_time = 0
        
        return templates.TemplateResponse("offer_detail.html", {
            "request": request,
            "offer": offer,
            "parts": parts
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Eroare la încărcarea detaliilor ofertei: {e}")
        raise HTTPException(status_code=500, detail="Eroare internă")

@app.post("/update_part")
async def update_part(
    part_id: int = Form(...),
    unit_price: Optional[float] = Form(None),
    discount: Optional[float] = Form(0.0),
    lead_time: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    """Actualizează datele unui reper"""
    try:
        # Găsește reperul
        part = db.query(Part).filter(Part.id == part_id).first()
        if not part:
            raise HTTPException(status_code=404, detail="Reperul nu a fost găsit")
            
        # Actualizează datele
        if unit_price is not None:
            part.unit_price = unit_price
        if discount is not None:
            part.discount = discount
        if lead_time is not None:
            part.lead_time = lead_time

            
        # Calculează prețul total
        if part.unit_price and part.quantity:
            part.total_price = part.unit_price * part.quantity * (1 - part.discount / 100)
            
        db.commit()
        
        return {"success": True, "message": "Reperul a fost actualizat cu succes"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Eroare la actualizarea reperului: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Eroare internă")

@app.get("/export/{offer_id}/csv")
async def export_csv(offer_id: int, db: Session = Depends(get_db)):
    """Exportă oferta în format CSV"""
    try:
        # Obține oferta și reperele
        offer = db.query(Offer).filter(Offer.id == offer_id).first()
        if not offer:
            raise HTTPException(status_code=404, detail="Oferta nu a fost găsită")
            
        parts = db.query(Part).filter(Part.offer_id == offer_id).all()
        
        # Creează DataFrame-ul
        data = []
        for part in parts:
            data.append({
                'ID Reper': part.part_id,
                'Denumire': part.part_name,
                'Material': part.material or '',
                'Observații': part.remarks or '',
                'Greutate (kg)': part.weight or '',
                'Lungime (mm)': part.length or '',
                'Lățime (mm)': part.width or '',
                'Înălțime (mm)': part.height or '',
                'Cantitate': part.quantity,
                'Preț unitar (€)': part.unit_price or '',
                'Discount (%)': part.discount or 0,
                'Lead time (zile)': part.lead_time or '',
                'Procese': ', '.join(part.processes) if part.processes else '',
                'Preț total (€)': part.total_price or ''
            })
            
        df = pd.DataFrame(data)
        
        # Salvează CSV-ul
        csv_path = f"exports/offer_{offer_id}.csv"
        os.makedirs("exports", exist_ok=True)
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        return FileResponse(
            csv_path,
            media_type='text/csv',
            filename=f"oferta_{offer.offer_id}.csv"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Eroare la exportul CSV: {e}")
        raise HTTPException(status_code=500, detail="Eroare internă")

@app.get("/export/{offer_id}/xlsx")
async def export_xlsx(offer_id: int, db: Session = Depends(get_db)):
    """Exportă oferta în format XLSX"""
    try:
        # Obține oferta și reperele
        offer = db.query(Offer).filter(Offer.id == offer_id).first()
        if not offer:
            raise HTTPException(status_code=404, detail="Oferta nu a fost găsită")
            
        parts = db.query(Part).filter(Part.offer_id == offer_id).all()
        
        # Creează DataFrame-ul
        data = []
        for part in parts:
            data.append({
                'ID Reper': part.part_id,
                'Denumire': part.part_name,
                'Material': part.material or '',
                'Observații': part.remarks or '',
                'Greutate (kg)': part.weight or '',
                'Lungime (mm)': part.width or '',
                'Lățime (mm)': part.width or '',
                'Înălțime (mm)': part.height or '',
                'Cantitate': part.quantity,
                'Preț unitar (€)': part.unit_price or '',
                'Discount (%)': part.discount or 0,
                'Lead time (zile)': part.lead_time or '',
                'Preț total (€)': part.total_price or ''
            })
            
        df = pd.DataFrame(data)
        
        # Salvează XLSX-ul
        xlsx_path = f"exports/offer_{offer_id}.xlsx"
        os.makedirs("exports", exist_ok=True)
        
        with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Ofertă', index=False)
            
            # Adaugă informații despre ofertă
            offer_info = pd.DataFrame([{
                'Câmp': 'ID Ofertă',
                'Valoare': offer.offer_id
            }, {
                'Câmp': 'Titlu',
                'Valoare': offer.title or ''
            }, {
                'Câmp': 'Client',
                'Valoare': offer.customer or ''
            }, {
                'Câmp': 'URL',
                'Valoare': offer.url
            }, {
                'Câmp': 'Data creării',
                'Valoare': offer.created_at.strftime('%Y-%m-%d %H:%M:%S')
            }])
            
            offer_info.to_excel(writer, sheet_name='Informații Ofertă', index=False)
        
        return FileResponse(
            xlsx_path,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            filename=f"oferta_{offer.offer_id}.xlsx"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Eroare la exportul XLSX: {e}")
        raise HTTPException(status_code=500, detail="Eroare internă")

@app.get("/api/offers")
async def get_offers(db: Session = Depends(get_db)):
    """API endpoint pentru obținerea ofertelor"""
    try:
        offers = db.query(Offer).order_by(Offer.created_at.desc()).all()
        return [{
            'id': offer.id,
            'offer_id': offer.offer_id,
            'title': offer.title,
            'customer': offer.customer,
            'url': offer.url,
            'created_at': offer.created_at.isoformat(),
            'parts_count': len(offer.parts)
        } for offer in offers]
    except Exception as e:
        logger.error(f"Eroare la obținerea ofertelor: {e}")
        raise HTTPException(status_code=500, detail="Eroare internă")

@app.get("/api/offer/{offer_id}/parts")
async def get_offer_parts(offer_id: int, db: Session = Depends(get_db)):
    """API endpoint pentru obținerea reperelor unei oferte"""
    try:
        parts = db.query(Part).filter(Part.offer_id == offer_id).all()
        return [{
            'id': part.id,
            'part_id': part.part_id,
            'part_name': part.part_name,
            'material': part.material,
            'remarks': part.remarks,
            'weight': part.weight,
            'length': part.length,
            'width': part.width,
            'height': part.height,
            'quantity': part.quantity,
            'unit_price': part.unit_price,
            'discount': part.discount,
            'lead_time': part.lead_time,
            'total_price': part.total_price
        } for part in parts]
    except Exception as e:
        logger.error(f"Eroare la obținerea reperelor: {e}")
        raise HTTPException(status_code=500, detail="Eroare internă")

@app.post("/api/scrape")
async def scrape_offer_from_extension(request: Request, db: Session = Depends(get_db)):
    """API endpoint pentru primirea datelor de la extensia Chrome"""
    try:
        # Parsează datele JSON de la extensie
        offer_data = await request.json()
        
        logger.info(f"Primit date de la extensie pentru oferta: {offer_data.get('offer_id')}")
        
        # Verifică dacă oferta există deja
        existing_offer = db.query(Offer).filter(Offer.offer_id == offer_data['offer_id']).first()
        
        if existing_offer:
            logger.info(f"Oferta {offer_data['offer_id']} există deja, actualizez")
            existing_offer.title = offer_data.get('title')
            existing_offer.customer = offer_data.get('customer')
            existing_offer.url = offer_data['url']
            offer_id = existing_offer.id
        else:
            # Creează oferta nouă
            offer = Offer(
                offer_id=offer_data['offer_id'],
                url=offer_data['url'],
                title=offer_data.get('title'),
                customer=offer_data.get('customer')
            )
            db.add(offer)
            db.commit()
            offer_id = offer.id
            logger.info(f"Oferta nouă creată cu ID: {offer_id}")
            
        # Salvează reperele
        parts_added = 0
        for part_data in offer_data.get('parts', []):
            # Verifică dacă reperul există
            existing_part = db.query(Part).filter(
                Part.offer_id == offer_id,
                Part.part_id == part_data.get('part_id')
            ).first()

            # Procesează procesele - dacă sunt string, convertește la list
            processes = part_data.get("processes", [])
            if isinstance(processes, str):
                processes = [p.strip() for p in processes.split(",") if p.strip()]
                # Procesează imaginea dacă există
                image_url = part_data.get("image_url")
                if image_url:
                    attachment = Attachment(
                        part_id=part.id,
                        filename=f"part_{part.part_id}_image.jpg",
                        file_path=image_url,
                        file_size=0
                    )
                    db.add(attachment)

            if existing_part:
                # Actualizează reperul existent
                existing_part.part_name = part_data.get('part_name', '')
                logger.info(f"Nume nou reper: {existing_part.part_name}")
                existing_part.material = part_data.get('material', '')
                existing_part.remarks = part_data.get('remarks', '')
                existing_part.weight = part_data.get('weight')
                existing_part.length = part_data.get('length')
                existing_part.width = part_data.get('width')
                existing_part.height = part_data.get('height')
                existing_part.quantity = part_data.get('quantity', 1)
                existing_part.processes = part_data.get('processes')  # listă sau None
                existing_part.image_url = part_data.get('image_url', '')
                logger.info(f"Reperul {part_data.get('part_id')} actualizat")
            else:
                # Creează reper nou
                logger.info(f"Nume nou: {part_data.get('part_name')} cu image: {part_data.get('part_name')}")
                part = Part(
                    offer_id=offer_id,
                    part_id=part_data.get('part_id', f"part_{parts_added}"),
                    name=part_data.get('part_name', 'Reper Xometry'),
                    material=part_data.get('material', 'Material nespecificat'),
                    image_url=part_data.get('image_url', ''),
                    remarks=part_data.get('remarks', ''),
                    weight=part_data.get('weight'),
                    length=part_data.get('length'),
                    width=part_data.get('width'),
                    height=part_data.get('height'),
                    quantity=part_data.get('quantity', 1),
                    processes=part_data.get('processes'),  # 👈 JSON nativ
                    volume_cm3=part_data.get('volume_cm3'),
                )
                db.add(part)
                parts_added += 1
                logger.info(f"Reper nou creat: {part_data.get('part_id')}")
                
        db.commit()
        logger.info(f"Oferta și {parts_added} reperele noi salvate cu succes")
        
        return {
            "success": True,
            "message": f"Oferta salvată cu succes! {parts_added} reper(e) nou(e) adăugat(e).",
            "offer_id": offer_id,
            "parts_added": parts_added
        }
        
    except Exception as e:
        logger.error(f"Eroare la salvarea datelor de la extensie: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Eroare la salvarea datelor: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
