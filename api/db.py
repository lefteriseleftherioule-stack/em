import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_db_connection():
    """
    Create a database connection using environment variables
    """
    try:
        conn = psycopg2.connect(
            os.getenv('DATABASE_URL'),
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
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
        query = "SELECT * FROM draws"
        params = []
        
        if year:
            query += " WHERE EXTRACT(YEAR FROM draw_date) = %s"
            params.append(year)
        
        query += " ORDER BY draw_date DESC"
        
        if limit:
            query += " LIMIT %s"
            params.append(limit)
            
        cur.execute(query, params)
        draws = cur.fetchall()
        cur.close()
        conn.close()
        return draws
    except Exception as e:
        print(f"Error fetching draws: {e}")
        if conn:
            conn.close()
        return []