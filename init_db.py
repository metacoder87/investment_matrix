import psycopg2
from app.config import settings

def init_db():
    conn = None
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB
        )
        cur = conn.cursor()
        with open("schema.sql", "r") as f:
            cur.execute(f.read())
        conn.commit()
        cur.close()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Error initializing database: {e}")
    finally:
        if conn is not None:
            conn.close()

if __name__ == "__main__":
    init_db()
