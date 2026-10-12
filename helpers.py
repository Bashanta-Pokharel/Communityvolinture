"""
helpers.py
Small reusable utilities: auth guard, file upload, ownership check,
volunteer reviews, task matching, and the nav context processor.
"""

import os
from functools import wraps
from uuid import uuid4

from flask import current_app, flash, redirect, session, url_for
from mysql.connector import Error as MySQLError
from werkzeug.utils import secure_filename

from database import run
from services.education import get_education_lists, match_details, ORGANIZATION_TYPE_OPTIONS


# ── Auth decorator ────────────────────────────────────────────────────────────

def require(*roles):
    """
    Protect a route: redirect to login if not logged in,
    or show an error if the user doesn't have the right role.

    Usage:
        @require("volunteer")
        @require("organization", "admin")
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if roles and session.get("role") not in roles:
                flash("You do not have permission for this page.", "danger")
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


# ── Image upload ──────────────────────────────────────────────────────────────

def save_image(upload):
    """
    Save an uploaded image to the uploads folder.
    Returns:
        "uploads/filename.jpg"  — success
        None                    — no file was chosen
        False                   — wrong file type
    """
    if not upload or not upload.filename:
        return None
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
        return False
    filename = f"{uuid4().hex}_{secure_filename(upload.filename)}"
    upload.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
    return f"uploads/{filename}"


# ── Ownership check ───────────────────────────────────────────────────────────

def owns(task):
    """Return True if the logged-in user owns this task or is an admin."""
    return session.get("role") == "admin" or (
        task and task["organization_id"] == session.get("user_id")
    )


# ── Volunteer reviews ─────────────────────────────────────────────────────────

def get_volunteer_reviews(volunteer_id):
    """Return all completed reviews written about a volunteer."""
    try:
        return run(
            "SELECT applications.rating, applications.review_text, tasks.title AS task_title, "
            "COALESCE(organization_profiles.organization_name, users.name, 'Organization') AS organization_name "
            "FROM applications "
            "JOIN tasks ON tasks.id = applications.task_id "
            "LEFT JOIN users ON users.id = tasks.organization_id "
            "LEFT JOIN organization_profiles ON organization_profiles.user_id = tasks.organization_id "
            "WHERE applications.volunteer_id = ? AND applications.status = 'Completed' "
            "AND applications.review_text IS NOT NULL AND applications.review_text != '' "
            "ORDER BY applications.id DESC",
            (volunteer_id,),
        ).fetchall()
    except MySQLError:
        return []


# ── Task + match pairing ──────────────────────────────────────────────────────

def tasks_with_matches(rows):
    """
    Pair each task with a match score for the currently logged-in volunteer.
    Returns a list of (task, match_result_or_None) tuples.
    """
    profile = None
    if session.get("role") == "volunteer":
        profile = run(
            "SELECT * FROM volunteer_profiles WHERE user_id=?",
            (session["user_id"],),
        ).fetchone()
    return [(task, match_details(profile, task) if profile else None) for task in rows]


# ── Navigation context processor ──────────────────────────────────────────────

def nav_context():
    """
    Automatically inject these variables into every HTML template:
      nav_photo               — the current user's profile photo/logo path
      unread_notifications    — count of unread notifications
      VOLUNTEER_EDUCATION_OPTIONS, TASK_MIN_EDUCATION_OPTIONS, ORGANIZATION_TYPE_OPTIONS
    """
    photo        = None
    unread_count = 0

    if session.get("user_id"):
        try:
            row = run(
                "SELECT COUNT(*) AS unread FROM notifications WHERE user_id=? AND is_read=0",
                (session["user_id"],),
            ).fetchone()
            if row:
                unread_count = row["unread"]
        except MySQLError:
            pass

    role = session.get("role")
    try:
        if role == "volunteer":
            row = run("SELECT photo_filename FROM volunteer_profiles WHERE user_id=?",
                      (session["user_id"],)).fetchone()
            if row and row["photo_filename"]:
                photo = row["photo_filename"]
        elif role == "admin":
            row = run("SELECT photo_filename FROM users WHERE id=?",
                      (session["user_id"],)).fetchone()
            if row and row["photo_filename"]:
                photo = row["photo_filename"]
        elif role == "organization":
            row = run("SELECT logo_filename FROM organization_profiles WHERE user_id=?",
                      (session["user_id"],)).fetchone()
            if row and row["logo_filename"]:
                photo = row["logo_filename"]
    except MySQLError:
        pass

    v_opts, t_opts, _, _ = get_education_lists()
    return {
        "nav_photo":                   photo,
        "unread_notifications":        unread_count,
        "VOLUNTEER_EDUCATION_OPTIONS": v_opts,
        "TASK_MIN_EDUCATION_OPTIONS":  t_opts,
        "ORGANIZATION_TYPE_OPTIONS":   ORGANIZATION_TYPE_OPTIONS,
    }
