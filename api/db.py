import os
import ssl
import json
from urllib.parse import urlparse
from dotenv import load_dotenv
import pg8000

# Load environment variables
load_dotenv()

def get_db_connection():
    """
    Create a database connection using environment variables.
    Uses pg8000 (pure-Python) for serverless compatibility.
    """
    try:
        dsn = os.getenv('DATABASE_URL')
        if not dsn:
            print("Error: DATABASE_URL is not set.", flush=True)
            return None

        # Parse DSN like: postgresql://user:pass@host:port/dbname
        u = urlparse(dsn)
        username = u.username
        password = u.password
        host = u.hostname
        port = u.port or 5432
        database = (u.path or '').lstrip('/')

        if not all([username, password, host, database]):
            print("Error: DATABASE_URL is malformed.", flush=True)
            return None

        # Neon requires SSL; create a default SSL context
        ssl_ctx = ssl.create_default_context()

        conn = pg8000.dbapi.connect(
            user=username,
            password=password,
            host=host,
            port=port,
            database=database,
            ssl_context=ssl_ctx,
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}", flush=True)
        return None

def get_draws(limit=None, year=None):
    """
    Get draws from database with optional filtering
    """
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        query = "SELECT draw_date, numbers, stars, jackpot, winners FROM draws"
        params = []

        if year:
            query += " WHERE EXTRACT(YEAR FROM draw_date) = %s"
            params.append(year)

        query += " ORDER BY draw_date DESC"

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()

        # Build list of dicts using cursor.description for column names
        col_names = [desc[0] for desc in cur.description]
        data = [dict(zip(col_names, row)) for row in rows]

        cur.close()
        conn.close()
        return data
    except Exception as e:
        print(f"Error fetching draws: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return []

def ensure_schema():
    """
    Ensure the 'draws' table exists with the expected schema.
    """
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS draws (
                id SERIAL PRIMARY KEY,
                draw_date DATE UNIQUE NOT NULL,
                numbers JSONB NOT NULL,
                stars JSONB NOT NULL,
                jackpot BIGINT,
                winners JSONB
            );
            """
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error ensuring schema: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return False

def upsert_draw(draw):
    """
    Insert or update a draw by draw_date.
    Expected draw dict keys: draw_date (YYYY-MM-DD), numbers (list), stars (list), jackpot (int), winners (dict)
    """
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO draws (draw_date, numbers, stars, jackpot, winners)
            VALUES (%s, %s::jsonb, %s::jsonb, %s, %s::jsonb)
            ON CONFLICT (draw_date)
            DO UPDATE SET
                numbers = EXCLUDED.numbers,
                stars = EXCLUDED.stars,
                jackpot = EXCLUDED.jackpot,
                winners = EXCLUDED.winners
            """,
            (
                draw.get("draw_date"),
                json.dumps(draw.get("numbers", [])),
                json.dumps(draw.get("stars", [])),
                draw.get("jackpot"),
                json.dumps(draw.get("winners", {})),
            )
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error upserting draw: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return False

def get_latest_draw():
    """
    Return the latest draw by draw_date.
    """
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT draw_date, numbers, stars, jackpot, winners FROM draws ORDER BY draw_date DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            cur.close()
            conn.close()
            return None

        col_names = [desc[0] for desc in cur.description]
        data = dict(zip(col_names, row))

        cur.close()
        conn.close()
        return data
    except Exception as e:
        print(f"Error getting latest draw: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return None
