from fastapi import FastAPI, HTTPException, Depends, Security
from pydantic import BaseModel, EmailStr
from typing import Dict, Optional
import os
from time import time
import jwt
from dotenv import load_dotenv
from passlib.context import CryptContext
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import psycopg2
from contextlib import contextmanager
from psycopg2.pool import SimpleConnectionPool
import traceback

load_dotenv()

# ============ DATABASE ============
DATABASE_URL = os.getenv("DATABASE_URL")
pool = SimpleConnectionPool(minconn=1, maxconn=5, dsn=DATABASE_URL, sslmode='require')

@contextmanager
def get_db():
    conn = pool.getconn()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        cursor.close()
        pool.putconn(conn)

def init_db():
    try:
        with get_db() as db:
            # Check and fix customer table columns
            db.execute("SELECT column_name FROM information_schema.columns WHERE table_name='customer'")
            existing_cols = [row[0] for row in db.fetchall()]
            print(f" Existing columns: {existing_cols}")
            
            # Create table if not exists with all required columns
            db.execute('''
                CREATE TABLE IF NOT EXISTS customer (
                    cust_id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    phone_no VARCHAR(15) NOT NULL,
                    gender VARCHAR(10) NOT NULL,
                    age INTEGER NOT NULL,
                    address TEXT,
                    role VARCHAR(20) DEFAULT 'customer',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            
            # Add missing columns one by one
            if 'password' not in existing_cols:
                db.execute("ALTER TABLE customer ADD COLUMN password VARCHAR(255) NOT NULL DEFAULT 'temp'")
                print(" Added 'password' column")
            if 'address' not in existing_cols:
                db.execute("ALTER TABLE customer ADD COLUMN address TEXT")
                print(" Added 'address' column")
            if 'role' not in existing_cols:
                db.execute("ALTER TABLE customer ADD COLUMN role VARCHAR(20) DEFAULT 'customer'")
                print(" Added 'role' column")
            if 'created_at' not in existing_cols:
                db.execute("ALTER TABLE customer ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                print(" Added 'created_at' column")
            
            # Create other tables
            db.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id SERIAL PRIMARY KEY,
                    cust_id INTEGER REFERENCES customer(cust_id) ON DELETE CASCADE,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    priority VARCHAR(20),
                    status VARCHAR(20) DEFAULT 'Open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            db.execute('''
                CREATE TABLE IF NOT EXISTS ticket_comments (
                    comment_id SERIAL PRIMARY KEY,
                    ticket_id INTEGER REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    cust_id INTEGER REFERENCES customer(cust_id) ON DELETE CASCADE,
                    comment TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            print(" Database initialized successfully!")
    except Exception as e:
        print(f" DB Init Error: {str(e)}")
        print(traceback.format_exc())

# ============ AUTH ============
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(p): return pwd_context.hash(p)
def verify_password(p, h): return pwd_context.verify(p, h)

def create_token(cust_id: int):
    token = jwt.encode({"cust_id": cust_id, "exp": int(time()) + 3600}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

def decode_token(token):
    try: return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except: return None

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    payload = decode_token(credentials.credentials)
    if not payload: raise HTTPException(401, "Invalid or Expired Token")
    return payload["cust_id"]

# ============ SCHEMAS ============
class Customer(BaseModel):
    name: str; email: EmailStr; password: str; phone_no: str; gender: str; age: int; address: str

class Login(BaseModel):
    email: EmailStr; password: str

class TicketCreate(BaseModel):
    title: str; description: str; priority: str

class CommentCreate(BaseModel):
    comment: str

# ============ APP ============
app = FastAPI(title="Ticket Management System")

@app.on_event("startup")
def startup():
    print(" Starting...")
    init_db()

@app.on_event("shutdown")
def shutdown():
    if pool: pool.closeall()

# ============ HEALTH ============
@app.get("/")
def root(): return {"status": "healthy", "message": "Ticket Management System"}

@app.get("/health")
def health():
    try:
        with get_db() as db: db.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except: return {"status": "unhealthy", "database": "disconnected"}

# ============ AUTH ENDPOINTS ============
@app.post("/register")
def register(cust: Customer):
    print(f" Registering: {cust.email}")
    try:
        # Validate input
        if len(cust.password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        if cust.age < 18:
            raise HTTPException(400, "Age must be 18 or older")
            
        hashed = hash_password(cust.password)
        with get_db() as db:
            # Check if email exists
            db.execute("SELECT cust_id FROM customer WHERE email=%s", (cust.email,))
            if db.fetchone():
                raise HTTPException(400, "Email already registered")
                
            db.execute("""
                INSERT INTO customer (name, email, password, phone_no, gender, age, address)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING cust_id
            """, (cust.name, cust.email, hashed, cust.phone_no, cust.gender, cust.age, cust.address))
            cust_id = db.fetchone()[0]
            print(f" Registered: {cust.email} (ID: {cust_id})")
            return {"message": "Registered successfully", "customer_id": cust_id}
    except HTTPException:
        raise
    except psycopg2.IntegrityError as e:
        print(f" Integrity Error: {str(e)}")
        raise HTTPException(400, "Email already registered or data integrity issue")
    except Exception as e:
        print(f" Register Error: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(400, f"Registration failed: {str(e)}")

@app.post("/login")
def login(data: Login):
    try:
        with get_db() as db:
            db.execute("SELECT cust_id, password, name, email, role FROM customer WHERE email=%s", (data.email,))
            result = db.fetchone()
            if not result: raise HTTPException(404, "User not found")
            if not verify_password(data.password, result[1]): raise HTTPException(401, "Invalid password")
            token = create_token(result[0])
            return {
                "access_token": token["access_token"],
                "token_type": "bearer",
                "cust_id": result[0],
                "name": result[2],
                "email": result[3],
                "role": result[4]
            }
    except Exception as e:
        raise HTTPException(400, str(e))

# ============ USER ENDPOINTS ============
@app.get("/profile")
def profile(user_id: int = Depends(get_current_user)):
    with get_db() as db:
        db.execute("SELECT cust_id, name, email, phone_no, gender, age, address, role, created_at FROM customer WHERE cust_id=%s", (user_id,))
        r = db.fetchone()
        if not r: raise HTTPException(404, "User not found")
        return {"cust_id": r[0], "name": r[1], "email": r[2], "phone_no": r[3], "gender": r[4],
                "age": r[5], "address": r[6], "role": r[7], "created_at": r[8].isoformat() if r[8] else None}

@app.get("/customers")
def get_customers():
    with get_db() as db:
        db.execute("SELECT cust_id, name, email, role FROM customer ORDER BY cust_id")
        return [{"cust_id": r[0], "name": r[1], "email": r[2], "role": r[3]} for r in db.fetchall()]

# ============ TICKETS ============
@app.post("/ticket")
def create_ticket(ticket: TicketCreate, user_id: int = Depends(get_current_user)):
    with get_db() as db:
        db.execute("""
            INSERT INTO tickets (cust_id, title, description, priority)
            VALUES (%s, %s, %s, %s) RETURNING ticket_id
        """, (user_id, ticket.title, ticket.description, ticket.priority))
        return {"message": "Ticket created", "ticket_id": db.fetchone()[0]}

@app.get("/my-tickets")
def my_tickets(user_id: int = Depends(get_current_user)):
    with get_db() as db:
        db.execute("SELECT ticket_id, title, description, priority, status, created_at FROM tickets WHERE cust_id=%s ORDER BY created_at DESC", (user_id,))
        return [{"ticket_id": r[0], "title": r[1], "description": r[2], "priority": r[3], "status": r[4],
                "created_at": r[5].isoformat() if r[5] else None} for r in db.fetchall()]

@app.get("/ticket/{ticket_id}")
def get_ticket(ticket_id: int, user_id: int = Depends(get_current_user)):
    with get_db() as db:
        db.execute("""SELECT t.*, c.name, c.email FROM tickets t JOIN customer c ON t.cust_id = c.cust_id WHERE t.ticket_id=%s""", (ticket_id,))
        r = db.fetchone()
        if not r: raise HTTPException(404, "Ticket not found")
        return {"ticket_id": r[0], "cust_id": r[1], "title": r[2], "description": r[3],
                "priority": r[4], "status": r[5], "created_at": r[6].isoformat() if r[6] else None,
                "customer_name": r[7], "customer_email": r[8]}

# ============ ADMIN ============
@app.get("/admin/tickets")
def admin_tickets():
    with get_db() as db:
        db.execute("""SELECT t.*, c.name, c.email FROM tickets t JOIN customer c ON t.cust_id = c.cust_id ORDER BY t.created_at DESC""")
        return [{"ticket_id": r[0], "cust_id": r[1], "title": r[2], "description": r[3],
                "priority": r[4], "status": r[5], "created_at": r[6].isoformat() if r[6] else None,
                "customer_name": r[7], "customer_email": r[8]} for r in db.fetchall()]

@app.put("/admin/ticket/{ticket_id}/status")
def update_status(ticket_id: int, status: str):
    with get_db() as db:
        db.execute("SELECT ticket_id FROM tickets WHERE ticket_id=%s", (ticket_id,))
        if not db.fetchone(): raise HTTPException(404, "Ticket not found")
        db.execute("UPDATE tickets SET status=%s WHERE ticket_id=%s", (status, ticket_id))
        return {"message": f"Status updated to '{status}'", "ticket_id": ticket_id}

# ============ COMMENTS ============
@app.post("/ticket/{ticket_id}/comment")
def add_comment(ticket_id: int, data: CommentCreate, user_id: int = Depends(get_current_user)):
    with get_db() as db:
        db.execute("SELECT ticket_id FROM tickets WHERE ticket_id=%s", (ticket_id,))
        if not db.fetchone(): raise HTTPException(404, "Ticket not found")
        db.execute("""INSERT INTO ticket_comments (ticket_id, cust_id, comment) VALUES (%s,%s,%s) RETURNING comment_id""",
            (ticket_id, user_id, data.comment))
        return {"message": "Comment added", "comment_id": db.fetchone()[0]}

@app.get("/ticket/{ticket_id}/comments")
def get_comments(ticket_id: int):
    with get_db() as db:
        db.execute("""SELECT c.comment_id, c.comment, c.created_at, u.name, u.email
            FROM ticket_comments c JOIN customer u ON c.cust_id = u.cust_id
            WHERE c.ticket_id=%s ORDER BY c.created_at DESC""", (ticket_id,))
        return [{"comment_id": r[0], "comment": r[1], "created_at": r[2].isoformat() if r[2] else None,
                "user_name": r[3], "user_email": r[4]} for r in db.fetchall()]

# ============ STATS ============
@app.get("/my-stats")
def my_stats(user_id: int = Depends(get_current_user)):
    with get_db() as db:
        db.execute("SELECT COUNT(*) FROM tickets WHERE cust_id=%s", (user_id,))
        total = db.fetchone()[0]
        db.execute("SELECT COUNT(*) FROM tickets WHERE cust_id=%s AND status='Open'", (user_id,))
        open_tickets = db.fetchone()[0]
        db.execute("SELECT COUNT(*) FROM tickets WHERE cust_id=%s AND status='Closed'", (user_id,))
        closed = db.fetchone()[0]
        db.execute("SELECT COUNT(*) FROM ticket_comments WHERE cust_id=%s", (user_id,))
        comments = db.fetchone()[0]
        return {"total_tickets": total, "open_tickets": open_tickets, "closed_tickets": closed, "total_comments": comments}
