# Community Volunteer System

A Flask web app where volunteers apply for tasks, organizations post tasks, and an admin manages everything.

---

## Setting up on a new machine (migration / first run)

### Step 1 — Requirements
- **Python 3.10+**
- **XAMPP** with MySQL started

### Step 2 — Clone / copy the project folder, then open a terminal inside it

### Step 3 — Create a virtual environment and install packages

```bash
python3 -m venv venv
source venv/bin/activate          # Mac / Linux
# venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### Step 4 — Start MySQL in XAMPP, then run the app

```bash
python3 app.py
```

That's it. The app **automatically**:
- Creates the `community_volinturee` MySQL database
- Creates all tables (from `schema.sql`)
- Seeds the skill, interest, and education catalogs
- Creates the default admin account

Open `http://127.0.0.1:5000` in your browser.

---

## If you only want to initialize the database (without starting the server)

```bash
python3 setup.py
```

Then start the app separately:

```bash
python3 app.py
```

---

## Default admin login

| Field    | Value               |
|----------|---------------------|
| Email    | `admin@gmail.com`   |
| Username | `admin`             |
| Password | `admin123`          |

> Change the password after first login.

---

## File structure

```
app.py                 ← All routes. Run this to start the system.
setup.py               ← One-time DB setup (optional, app.py does this too)
database.py            ← run(), commit(), init_db()
helpers.py             ← require, save_image, owns, nav, match helpers
services/
  matching.py          ← Jaccard similarity algorithm
  education.py         ← Education levels + match_details
schema.sql             ← MySQL table definitions
requirements.txt       ← Python packages
templates/             ← HTML pages
static/                ← CSS, JS, images, uploads
```

---

## How the app initializes itself (for developers)

When you run `python3 app.py`, at the bottom of the file this runs:

```python
with app.app_context():
    init_db()          # ← in database.py
```

`init_db()` does these steps in order:

1. **Creates the database** — `CREATE DATABASE IF NOT EXISTS community_volinturee`
2. **Creates tables** — runs every statement in `schema.sql`
3. **Safe migrations** — adds any missing columns for older databases
4. **Seeds catalogs** — inserts default skills, interests, and education levels
5. **Admin account** — creates `admin@gmail.com` if it doesn't exist yet

Everything uses `IF NOT EXISTS` or `ON DUPLICATE KEY UPDATE`, so it is **safe to run multiple times** — it will never overwrite existing data.

---

## Jaccard similarity

`J(A, B) = |A ∩ B| / |A ∪ B|`

- **A** = volunteer's skills
- **B** = task's required skills
- A volunteer must score **> 30%**, share at least **one available day**, and meet the **education level** to qualify.
