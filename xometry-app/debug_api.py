#!/usr/bin/env python3
"""
Script de debug pentru a verifica ce primește API-ul
"""
import json
import sqlite3

def check_latest_data():
    conn = sqlite3.connect('xometry_offers.db')
    cursor = conn.cursor()
    
    # Verifică ultimele 5 repere salvate
    cursor.execute("""
        SELECT p.part_id, p.name, p.length, p.width, p.height, p.weight, 
               o.offer_id, o.title, p.id
        FROM parts p 
        JOIN offers o ON p.offer_id = o.id 
        ORDER BY p.id DESC 
        LIMIT 5
    """)
    
    print("=== ULTIMELE 5 REPERE SALVATE ===")
    for row in cursor.fetchall():
        print(f"ID: {row[0]}")
        print(f"Nume: {row[1]}")
        print(f"L: {row[2]}, W: {row[3]}, H: {row[4]}")
        print(f"Weight: {row[5]} kg")
        print(f"Offer: {row[6]} - {row[7]}")
        print(f"Part DB ID: {row[8]}")
        print("-" * 50)
    
    # Verifică dacă există repere cu dimensiuni complete
    cursor.execute("""
        SELECT COUNT(*) as total,
               COUNT(length) as with_length,
               COUNT(width) as with_width, 
               COUNT(height) as with_height,
               COUNT(weight) as with_weight
        FROM parts
    """)
    
    stats = cursor.fetchone()
    print(f"\n=== STATISTICI DIMENSIUNI ===")
    print(f"Total repere: {stats[0]}")
    print(f"Cu lungime: {stats[1]}")
    print(f"Cu lățime: {stats[2]}")
    print(f"Cu înălțime: {stats[3]}")
    print(f"Cu greutate: {stats[4]}")
    
    conn.close()

if __name__ == "__main__":
    check_latest_data()
