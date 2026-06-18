import os
import psycopg2
from contextlib import contextmanager
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

pool = SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=DATABASE_URL
)

@contextmanager
def get_db():
    conn = pool.getconn()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        pool.putconn(conn)

def init_db():
    with get_db() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customer (
                cust_id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                phone_no VARCHAR(15) NOT NULL,
                gender VARCHAR(10) NOT NULL,
                age INTEGER NOT NULL,
                address TEXT
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS booking (
                bid SERIAL PRIMARY KEY,
                cust_id INTEGER REFERENCES customer(cust_id) ON DELETE CASCADE,
                source VARCHAR(100) NOT NULL,
                destination VARCHAR(100) NOT NULL,
                ticket_status VARCHAR(20) NOT NULL
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment (
                bid INTEGER REFERENCES booking(bid) ON DELETE CASCADE,
                cust_id INTEGER REFERENCES customer(cust_id) ON DELETE CASCADE,
                payment_status VARCHAR(20) NOT NULL
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id SERIAL PRIMARY KEY,
                cust_id INTEGER REFERENCES customer(cust_id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                priority VARCHAR(20) NOT NULL,
                status VARCHAR(20) DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ticket_comments (
                comment_id SERIAL PRIMARY KEY,
                ticket_id INTEGER REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                cust_id INTEGER REFERENCES customer(cust_id) ON DELETE CASCADE,
                comment TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')