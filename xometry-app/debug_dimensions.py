#!/usr/bin/env python3
"""
Script de debug pentru a verifica dimensiunile în baza de date
"""
import sqlite3

def check_dimensions():
    conn = sqlite3.connect('xometry_offers.db')
    cursor = conn.cursor()
    
    # Verifică toate repere cu greutate
    cursor.execute("""
        SELECT part_id, name, length, width, height, weight 
        FROM parts 
        WHERE weight IS NOT NULL AND weight > 0
        ORDER BY weight DESC
        LIMIT 10
    """)
    
    print("=== REPERE CU GREUTATE ===")
    for row in cursor.fetchall():
        print(f"ID: {row[0]}")
        print(f"Nume: {row[1]}")
        print(f"L: {row[2]}, W: {row[3]}, H: {row[4]}")
        print(f"Weight: {row[5]} kg")
        print("-" * 40)
    
    # Verifică repere specifice
    cursor.execute("""
        SELECT part_id, name, length, width, height, weight 
        FROM parts 
        WHERE part_id LIKE '%635528%' OR part_id LIKE '%635527%'
    """)
    
    print("\n=== REPERE SPECIFICE ===")
    for row in cursor.fetchall():
        print(f"ID: {row[0]}")
        print(f"Nume: {row[1]}")
        print(f"L: {row[2]}, W: {row[3]}, H: {row[4]}")
        print(f"Weight: {row[5]} kg")
        print("-" * 40)
    
    conn.close()

if __name__ == "__main__":
    check_dimensions()
