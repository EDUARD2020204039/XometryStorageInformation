#!/usr/bin/env python3
"""
Migrație pentru adăugarea câmpurilor dosar în baza de date
"""
import sqlite3
import os
from pathlib import Path

def migrate_database():
    """Adaugă câmpurile dosar în tabelul offers"""
    db_path = "xometry_offers.db"
    
    if not os.path.exists(db_path):
        print("Baza de date nu există. Rulând init_db...")
        from xometry.db import init_db
        init_db(f"sqlite:///{db_path}")
        print("Baza de date creată cu câmpurile dosar.")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Verifică dacă câmpurile există deja
        cursor.execute("PRAGMA table_info(offers)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'dosar_id' not in columns:
            print("Adaugă câmpul dosar_id...")
            cursor.execute("ALTER TABLE offers ADD COLUMN dosar_id VARCHAR")
        
        if 'dosar_path' not in columns:
            print("Adaugă câmpul dosar_path...")
            cursor.execute("ALTER TABLE offers ADD COLUMN dosar_path VARCHAR(500)")
        
        if 'dosar_allocated' not in columns:
            print("Adaugă câmpul dosar_allocated...")
            cursor.execute("ALTER TABLE offers ADD COLUMN dosar_allocated DATETIME")
        
        conn.commit()
        print("✅ Migrația completată cu succes!")
        
    except Exception as e:
        print(f"❌ Eroare la migrație: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()
