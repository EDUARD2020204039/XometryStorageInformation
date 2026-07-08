#!/usr/bin/env python3
import os
import sqlite3
import sys


def get_db_path() -> str:
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "", 1)
    return os.path.join(os.path.dirname(__file__), "xometry_offers.db")


def check_column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return column_name in [column[1] for column in cursor.fetchall()]


def add_column(cursor: sqlite3.Cursor, table_name: str, column_name: str, definition: str) -> None:
    if not check_column_exists(cursor, table_name, column_name):
        print(f"Adding {table_name}.{column_name}")
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def migrate_database() -> bool:
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Database does not exist yet: {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        add_column(cursor, "offers", "documentation_path", "VARCHAR(500)")
        add_column(cursor, "offers", "remarks", "TEXT")
        add_column(cursor, "offers", "dosar_id", "VARCHAR")
        add_column(cursor, "offers", "dosar_path", "VARCHAR(500)")
        add_column(cursor, "offers", "dosar_allocated", "DATETIME")

        add_column(cursor, "parts", "local_image_path", "VARCHAR(500)")
        add_column(cursor, "parts", "processes", "JSON")
        add_column(cursor, "parts", "volume_cm3", "FLOAT")
        add_column(cursor, "parts", "deviz_path", "VARCHAR(500)")
        add_column(cursor, "parts", "deviz_url", "VARCHAR(500)")

        add_column(cursor, "attachments", "file_size", "INTEGER")

        conn.commit()
        print(f"Migration complete: {db_path}")
        return True
    except Exception as e:
        print(f"Migration failed: {e}")
        return False
    finally:
        if "conn" in locals():
            conn.close()


def show_database_info() -> None:
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Database does not exist: {db_path}")
        return
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for (table_name,) in cursor.fetchall():
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            print(f"{table_name}: {cursor.fetchone()[0]}")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "info":
        show_database_info()
    elif not migrate_database():
        sys.exit(1)
