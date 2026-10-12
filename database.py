"""
database.py — All database helpers in one place.

Every other file imports run() and commit() from here.
"""

import os
import re

import mysql.connector
from flask import current_app, g
from mysql.connector import Error as MySQLError
from werkzeug.security import generate_password_hash


# ── Connection ───────────────────────────────────────────────────────────────

def connect_db(with_database=True):
    """Open a raw connection to XAMPP MySQL."""
    socket = "/Applications/XAMPP/xamppfiles/var/mysql/mysql.sock"
    if not os.path.exists(socket):
        raise MySQLError("XAMPP MySQL is OFF. Please start it in the XAMPP control panel.")

    cfg = {
        "unix_socket":      socket,
        "user":             current_app.config["MYSQL_USER"],
        "password":         current_app.config["MYSQL_PASSWORD"],
        "connection_timeout": 3,
    }
    if with_database:
        cfg["database"] = current_app.config["MYSQL_DATABASE"]
    return mysql.connector.connect(**cfg)


def get_db():
    """Return one shared DB connection per request (create it on first call)."""
    if "db" not in g:
        g.db = connect_db()
    return g.db


# ── Query helpers ────────────────────────────────────────────────────────────

def run(query, values=()):
    """Run a SQL query. Use ? as the placeholder — easier to read than %s."""
    cursor = get_db().cursor(dictionary=True, buffered=True)
    cursor.execute(query.replace("?", "%s"), values)
    return cursor


def commit():
    """Save (commit) all pending database changes."""
    get_db().commit()


def close_db(error=None):
    """Close the DB connection at the end of every request automatically."""
    conn = g.pop("db", None)
    if conn:
        try:
            conn.close()
        except Exception:
            pass


# ── Safe schema migration helper ─────────────────────────────────────────────

def _add_column_if_missing(table, column, definition):
    """Add a column to a table only if it does not already exist."""
    exists = run(
        "SELECT COUNT(*) AS n FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=? AND column_name=?",
        (table, column),
    ).fetchone()
    if exists["n"] == 0:
        run(f"ALTER TABLE `{table}` ADD `{column}` {definition}")


# ── Database initialisation ──────────────────────────────────────────────────

def init_db():
    """
    Called once on startup:
    1. Create the database if missing.
    2. Run schema.sql to create tables.
    3. Apply any missing column migrations.
    4. Seed skill / interest / education catalogs.
    5. Create the default admin account.
    """
    try:
        db_name = current_app.config["MYSQL_DATABASE"]
        if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
            raise ValueError("Database name must only contain letters, numbers, or underscores.")

        # Step 1 — create the database schema if it does not exist.
        conn = connect_db(with_database=False)
        cur  = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4")
        conn.commit()
        cur.close()
        conn.close()

        os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)

        # Step 2 — run schema.sql (CREATE TABLE IF NOT EXISTS statements).
        with current_app.open_resource("schema.sql") as f:
            for stmt in f.read().decode().split(";"):
                if stmt.strip():
                    run(stmt)

        # Step 3 — safe migrations for users upgrading from an older database.
        migrations = [
            ("users",                 "username",          "VARCHAR(60) NULL UNIQUE AFTER name"),
            ("users",                 "photo_filename",     "VARCHAR(255) NULL"),
            ("applications",          "review_text",        "TEXT NULL"),
            ("applications",          "rating",             "INT NULL DEFAULT 5"),
            ("applications",          "updated_at",         "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            ("volunteer_profiles",    "education_level",    "VARCHAR(100) NULL DEFAULT 'Intermediate (10+2) / High School'"),
            ("tasks",                 "min_education",      "VARCHAR(100) NULL DEFAULT 'No Formal Education Required'"),
            ("notifications",         "link_url",           "VARCHAR(255) NULL"),
            ("organization_profiles", "organization_type",  "VARCHAR(100) NULL DEFAULT 'Non-Governmental Organization (NGO)'"),
            ("organization_profiles", "contact_email",      "VARCHAR(190) NULL"),
        ]
        for table, column, definition in migrations:
            _add_column_if_missing(table, column, definition)

        # Step 4a — seed default skills.
        default_skills = (
            "Communication,Teaching,First Aid,Computer,Programming,Graphic Design,"
            "Photography,Cooking,Driving,Organizing,Teamwork,Gardening,Fundraising,"
            "Social Media,Translation,Accounting,Counselling,Childcare,Elder Care,"
            "Event Planning,Cleaning,Research"
        )
        for skill in default_skills.split(","):
            run("INSERT INTO skill_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (skill,))

        # Step 4b — seed default interests.
        default_interests = (
            "Education,Technology,Environment,Community,Food Support,Health,Sports,"
            "Animals,Arts,Music,Reading,Youth,Women Empowerment,Disaster Relief,Culture,Outdoors"
        )
        for interest in default_interests.split(","):
            run("INSERT INTO interest_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (interest,))

        # Step 4c — seed education levels.
        education_levels = [
            ("Uneducated / Basic Literacy",      "volunteer", 1),
            ("SEE / SLC (Secondary School)",      "both",      2),
            ("Intermediate (10+2) / High School", "both",      3),
            ("Bachelor's Running",                "volunteer", 4),
            ("Bachelor's Level",                  "task",      4),
            ("Bachelor's Degree",                 "volunteer", 5),
            ("Master's Running",                  "volunteer", 6),
            ("Master's Level",                    "task",      6),
            ("Master's Degree",                   "volunteer", 7),
            ("M.Phil / Ph.D.",                    "volunteer", 8),
            ("Ph.D. / Specialised Degree",        "task",      8),
            ("No Formal Education Required",       "task",      1),
        ]
        for name, category, rank in education_levels:
            run(
                "INSERT INTO education_catalog(name, category, rank_level) VALUES(?,?,?) "
                "ON DUPLICATE KEY UPDATE category=category",
                (name, category, rank),
            )

        # Step 5 — create the default admin account if it doesn't exist yet.
        if not run("SELECT id FROM users WHERE email=?", ("admin@gmail.com",)).fetchone():
            run(
                "INSERT INTO users(name,username,email,password,role) VALUES(?,?,?,?,?)",
                ("System Administrator", "admin", "admin@gmail.com",
                 generate_password_hash("admin123"), "admin"),
            )

        commit()
    except (MySQLError, ValueError) as error:
        current_app.logger.warning("DB startup notice: %s", error)
