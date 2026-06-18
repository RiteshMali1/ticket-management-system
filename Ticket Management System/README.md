# 🎫 Ticket Management System

A comprehensive ticket management system built with FastAPI and Supabase.

## Features
- JWT Authentication
- User Registration & Login
- Profile Management
- Ticket CRUD
- Comments System
- Admin Panel
- Statistics

## Tech Stack
- FastAPI
- PostgreSQL (Supabase)
- JWT Authentication
- bcrypt Password Hashing

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env

# Run
uvicorn app.main:app --reload