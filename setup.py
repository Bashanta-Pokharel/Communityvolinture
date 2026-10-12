"""
setup.py  —  Run this ONCE when setting up the project on a new machine.

What it does:
  1. Creates the MySQL database  (community_volinturee)
  2. Creates all tables          (from schema.sql)
  3. Seeds skill/interest/education catalogs
  4. Creates the default admin account (admin@gmail.com / admin123)

After running this, start the app normally:
  python3 app.py

NOTE: XAMPP MySQL must be running before you run this script.
"""

from app import app
from database import init_db

print("Setting up Community Volunteer System database...")

with app.app_context():
    init_db()

print("Done! You can now run:  python3 app.py")
print("Admin login: admin@gmail.com / admin123")
