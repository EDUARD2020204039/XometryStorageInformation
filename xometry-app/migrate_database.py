#!/usr/bin/env python3
"""
Script de migrare pentru baza de date Xometry Analysis
Adaugă coloane noi sau actualizează structura bazei de date
"""

import sqlite3
import os
import sys
from pathlib import Path

def get_db_path():
    """Obține calea către baza de date"""
    return os.path.join(os.path.dirname(__file__), 'xometry_offers.db')

def check_column_exists(cursor, table_name, column_name):
    """Verifică dacă o coloană există în tabel"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [column[1] for column in cursor.fetchall()]
    return column_name in columns

def migrate_database():
    """Execută migrarea bazei de date"""
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"❌ Baza de date nu există: {db_path}")
        return False
    
    print(f"🔄 Migrează baza de date: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Verifică și adaugă coloana documentation_path în tabelul offers
        if not check_column_exists(cursor, 'offers', 'documentation_path'):
            print("➕ Adaugă coloana documentation_path în tabelul offers...")
            cursor.execute("ALTER TABLE offers ADD COLUMN documentation_path VARCHAR(500)")
            print("✅ Coloana documentation_path adăugată cu succes")
        else:
            print("✅ Coloana documentation_path există deja")
        
        # Verifică și adaugă alte coloane dacă e necesar
        if not check_column_exists(cursor, 'offers', 'remarks'):
            print("➕ Adaugă coloana remarks în tabelul offers...")
            cursor.execute("ALTER TABLE offers ADD COLUMN remarks TEXT")
            print("✅ Coloana remarks adăugată cu succes")
        else:
            print("✅ Coloana remarks există deja")
        
        # Verifică tabelul parts pentru coloane noi
        if not check_column_exists(cursor, 'parts', 'local_image_path'):
            print("➕ Adaugă coloana local_image_path în tabelul parts...")
            cursor.execute("ALTER TABLE parts ADD COLUMN local_image_path VARCHAR(500)")
            print("✅ Coloana local_image_path adăugată cu succes")
        else:
            print("✅ Coloana local_image_path există deja")
        
        if not check_column_exists(cursor, 'parts', 'processes'):
            print("➕ Adaugă coloana processes în tabelul parts...")
            cursor.execute("ALTER TABLE parts ADD COLUMN processes JSON")
            print("✅ Coloana processes adăugată cu succes")
        else:
            print("✅ Coloana processes există deja")
        
        if not check_column_exists(cursor, 'parts', 'volume_cm3'):
            print("➕ Adaugă coloana volume_cm3 în tabelul parts...")
            cursor.execute("ALTER TABLE parts ADD COLUMN volume_cm3 FLOAT")
            print("✅ Coloana volume_cm3 adăugată cu succes")
        else:
            print("✅ Coloana volume_cm3 există deja")

        # Deviz per reper
        if not check_column_exists(cursor, 'parts', 'deviz_path'):
            print("➕ Adaugă coloana deviz_path în tabelul parts...")
            cursor.execute("ALTER TABLE parts ADD COLUMN deviz_path VARCHAR(500)")
            print("✅ Coloana deviz_path adăugată cu succes")
        else:
            print("✅ Coloana deviz_path există deja")

        if not check_column_exists(cursor, 'parts', 'deviz_url'):
            print("➕ Adaugă coloana deviz_url în tabelul parts...")
            cursor.execute("ALTER TABLE parts ADD COLUMN deviz_url VARCHAR(500)")
            print("✅ Coloana deviz_url adăugată cu succes")
        else:
            print("✅ Coloana deviz_url există deja")
        
        # Verifică tabelul attachments
        if not check_column_exists(cursor, 'attachments', 'file_size'):
            print("➕ Adaugă coloana file_size în tabelul attachments...")
            cursor.execute("ALTER TABLE attachments ADD COLUMN file_size INTEGER")
            print("✅ Coloana file_size adăugată cu succes")
        else:
            print("✅ Coloana file_size există deja")
        
        conn.commit()
        print("🎉 Migrarea completă cu succes!")
        return True
        
    except Exception as e:
        print(f"❌ Eroare la migrarea bazei de date: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def show_database_info():
    """Afișează informații despre baza de date"""
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"❌ Baza de date nu există: {db_path}")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"📊 Informații baza de date: {db_path}")
        print("=" * 50)
        
        # Afișează tabelele
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"📋 Tabele ({len(tables)}):")
        for table in tables:
            print(f"  - {table[0]}")
        
        print()
        
        # Afișează structura fiecărui tabel
        for table in tables:
            table_name = table[0]
            print(f"🔍 Structura tabelului '{table_name}':")
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            for column in columns:
                col_id, name, col_type, not_null, default_val, pk = column
                pk_str = " (PK)" if pk else ""
                not_null_str = " NOT NULL" if not_null else ""
                default_str = f" DEFAULT {default_val}" if default_val else ""
                print(f"  - {name}: {col_type}{not_null_str}{default_str}{pk_str}")
            print()
        
        # Afișează statistici
        for table in tables:
            table_name = table[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"📈 {table_name}: {count} înregistrări")
        
    except Exception as e:
        print(f"❌ Eroare la afișarea informațiilor: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "info":
        show_database_info()
    else:
        print("🚀 Xometry Analysis - Migrare Bază de Date")
        print("=" * 50)
        
        if migrate_database():
            print("\n✅ Migrarea completă cu succes!")
            print("💡 Pentru a vedea informații despre baza de date, rulează:")
            print("   python migrate_database.py info")
        else:
            print("\n❌ Migrarea a eșuat!")
            sys.exit(1)
