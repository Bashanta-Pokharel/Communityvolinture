"""
app.py  ←  Run this file to start the whole system: python3 app.py

This file only handles:
  1. Flask app setup (config, error handler, teardown)
  2. All URL routes  (@app.route)

All heavy logic lives in:
  database.py          — run(), commit(), init_db()
  helpers.py           — require, save_image, owns, reviews, matching, nav
  services/education.py — education levels, match_details, refresh_applications
  services/matching.py  — Jaccard similarity algorithm
"""

import os
import re

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from mysql.connector import Error as MySQLError
from werkzeug.security import check_password_hash, generate_password_hash

# ── Our own modules ───────────────────────────────────────────────────────────
from database import close_db, commit, init_db, run
from helpers import get_volunteer_reviews, nav_context, owns, require, save_image, tasks_with_matches
from services.education import match_details, refresh_applications
from services.matching import jaccard_similarity, terms

# =============================================================================
#  APP SETUP
# =============================================================================

app = Flask(__name__)
app.secret_key = "change-this-before-deploying"

app.config["MYSQL_USER"]     = os.environ.get("MYSQL_USER", "root")
app.config["MYSQL_PASSWORD"] = os.environ.get("MYSQL_PASSWORD", "")
app.config["MYSQL_DATABASE"] = "community_volinturee"
app.config["UPLOAD_FOLDER"]  = os.path.join(app.root_path, "static", "uploads")

# Close DB at end of every request
app.teardown_appcontext(close_db)

# Show a friendly flash when MySQL is unreachable
@app.errorhandler(MySQLError)
def handle_db_error(error):
    app.logger.error("MySQL Error: %s", error)
    flash("Database is offline. Start MySQL in XAMPP and try again.", "warning")
    return redirect(url_for("home"))

# Inject nav variables into every template (photo, unread count, option lists)
app.context_processor(nav_context)


# =============================================================================
#  PUBLIC ROUTES
# =============================================================================

@app.route("/")
def home():
    try:
        tasks_list = run(
            "SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'System Administrator') AS organization_name "
            "FROM tasks LEFT JOIN users ON users.id=tasks.organization_id "
            "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
            "ORDER BY tasks.id DESC LIMIT 10"
        ).fetchall()
    except MySQLError:
        tasks_list = []
    return render_template("index.html", tasks=tasks_list)


@app.route("/health")
def health():
    try:
        run("SELECT 1").fetchone()
        return jsonify(status="online", database="MySQL connected")
    except Exception as e:
        return jsonify(status="offline", error=str(e)), 503


@app.route("/tasks")
def tasks():
    try:
        rows = run(
            "SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'System Administrator') AS organization_name "
            "FROM tasks LEFT JOIN users ON users.id=tasks.organization_id "
            "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
            "ORDER BY tasks.id DESC"
        ).fetchall()
        matches = tasks_with_matches(rows)
    except MySQLError:
        matches = []
    return render_template("tasks.html", task_matches=matches)


@app.route("/compare", methods=("GET", "POST"))
def compare():
    result = None
    if request.method == "POST":
        s, a, b, c, u = jaccard_similarity(request.form["volunteer_terms"], request.form["task_terms"])
        result = {"score": s, "volunteer": sorted(a), "task": sorted(b), "common": sorted(c), "all": sorted(u)}
    return render_template("compare.html", result=result)


# =============================================================================
#  AUTH ROUTES  (register / login / logout)
# =============================================================================

@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        email    = request.form["email"].lower()
        username = request.form["username"].strip()
        if request.form["password"] != request.form["confirm_password"]:
            flash("Passwords do not match.", "warning")
        elif not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
        elif run("SELECT id FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
            flash("That username is already taken.", "warning")
        elif run("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("That email is already registered.", "warning")
        else:
            run("INSERT INTO users(name,username,email,password,role,date_of_birth) VALUES(?,?,?,?,'volunteer',?)",
                (request.form["name"], username, email,
                 generate_password_hash(request.form["password"]), request.form["date_of_birth"]))
            commit()
            flash("Volunteer account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/register-organization", methods=("GET", "POST"))
def register_organization():
    if request.method == "POST":
        email    = request.form["email"].lower()
        username = request.form["username"].strip()
        if request.form["password"] != request.form["confirm_password"]:
            flash("Passwords do not match.", "warning")
        elif not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
        elif run("SELECT id FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
            flash("That username is already taken.", "warning")
        elif run("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("That email is already registered.", "warning")
        else:
            name     = request.form["organization_name"]
            org_type = request.form.get("organization_type", "Non-Governmental Organization (NGO)").strip()
            logo     = save_image(request.files.get("logo"))
            if logo is False:
                flash("Logo must be PNG, JPG, GIF, or WEBP.", "danger")
                return render_template("register_organization.html")
            uid = run("INSERT INTO users(name,username,email,password,role) VALUES(?,?,?,?,'organization')",
                      (name, username, email, generate_password_hash(request.form["password"]))).lastrowid
            run("INSERT INTO organization_profiles(user_id,organization_name,organization_type,contact_person,contact_email,phone,location,description,logo_filename) VALUES(?,?,?,?,?,?,?,?,?)",
                (uid, name, org_type, request.form["contact_person"], email,
                 request.form["phone"], request.form["location"], request.form["description"], logo))
            commit()
            flash("Organization account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register_organization.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        identifier = request.form["identifier"].strip()
        user = run("SELECT * FROM users WHERE lower(email)=lower(?) OR lower(username)=lower(?)",
                   (identifier, identifier)).fetchone()
        if user and check_password_hash(user["password"], request.form["password"]):
            session.clear()
            session["user_id"]   = user["id"]
            session["user_name"] = user["name"]
            session["role"]      = user["role"]
            flash("Login successful. Welcome back!", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            elif user["role"] == "organization":
                return redirect(url_for("organization_dashboard"))
            else:
                return redirect(url_for("volunteer_dashboard"))
        flash("Incorrect email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# =============================================================================
#  VOLUNTEER ROUTES
# =============================================================================

@app.route("/user/dashboard")
@require("volunteer")
def volunteer_dashboard():
    profile      = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (session["user_id"],)).fetchone()
    recent_tasks = run(
        "SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'Organization') AS organization_name "
        "FROM tasks LEFT JOIN users ON users.id=tasks.organization_id "
        "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
        "ORDER BY tasks.id DESC LIMIT 6"
    ).fetchall()
    task_matches = [(t, match_details(profile, t) if profile else None) for t in recent_tasks]
    counts = {
        "applications": run("SELECT COUNT(*) AS n FROM applications WHERE volunteer_id=?", (session["user_id"],)).fetchone()["n"],
        "completed":    run("SELECT COUNT(*) AS n FROM applications WHERE volunteer_id=? AND status='Completed'", (session["user_id"],)).fetchone()["n"],
        "qualified":    sum(1 for _, m in task_matches if m and m["qualified"]),
    }
    return render_template("volunteer_dashboard.html", task_matches=task_matches, counts=counts, profile=profile)


@app.route("/user/profile", methods=("GET", "POST"))
@require("volunteer")
def profile():
    user = run("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    prof = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (session["user_id"],)).fetchone()
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        if username and username.lower() != (user["username"] or "").lower():
            if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
                flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
                return redirect(url_for("profile"))
            if run("SELECT id FROM users WHERE lower(username)=lower(?) AND id!=?", (username, session["user_id"])).fetchone():
                flash("That username is already taken.", "warning")
                return redirect(url_for("profile"))
        image = save_image(request.files.get("photo"))
        if image is False:
            flash("Profile image must be PNG, JPG, JPEG, GIF, or WEBP.", "warning")
            return redirect(url_for("profile"))
        if image is None:
            image = prof["photo_filename"] if prof else None
        edu   = request.form.get("education_level", "Intermediate (10+2) / High School").strip()
        vals  = (", ".join(request.form.getlist("skills")),
                 ", ".join(request.form.getlist("interests")),
                 ", ".join(request.form.getlist("availability")),
                 request.form["location"], image, edu, session["user_id"])
        if prof:
            run("UPDATE volunteer_profiles SET skills=?,interests=?,availability=?,location=?,photo_filename=?,education_level=? WHERE user_id=?", vals)
        else:
            run("INSERT INTO volunteer_profiles(skills,interests,availability,location,photo_filename,education_level,user_id) VALUES(?,?,?,?,?,?,?)", vals)
        run("UPDATE users SET name=?,username=?,date_of_birth=? WHERE id=?",
            (name or user["name"], username or user["username"], request.form["date_of_birth"], session["user_id"]))
        commit()
        session["user_name"] = name or user["name"]
        refresh_applications(session["user_id"])
        flash("Profile updated and task results refreshed.", "success")
        return redirect(url_for("profile"))
    skills    = run("SELECT name FROM skill_catalog ORDER BY name").fetchall()
    interests = run("SELECT name FROM interest_catalog ORDER BY name").fetchall()
    return render_template("profile.html", profile=prof, user=user, skills=skills, interests=interests,
                           selected_skills=terms(prof["skills"]) if prof else set(),
                           selected_interests=terms(prof["interests"]) if prof else set(),
                           selected_days=terms(prof["availability"]) if prof else set())


@app.route("/profile")
def profile_legacy_redirect():
    return redirect(url_for("profile"))


@app.route("/apply/<int:task_id>", methods=("POST",))
@require("volunteer")
def apply(task_id):
    task = run("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    prof = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (session["user_id"],)).fetchone()
    if not prof:
        flash("Please complete your volunteer profile first.", "warning")
        return redirect(url_for("profile"))
    if run("SELECT id FROM applications WHERE volunteer_id=? AND task_id=?", (session["user_id"], task_id)).fetchone():
        flash("You have already applied for this task.", "warning")
    elif task:
        result = match_details(prof, task)
        if not result["qualified"]:
            flash(f"Application rejected: Jaccard match is {result['score']*100:.2f}%. More than 30% is required.", "danger")
            return redirect(url_for("tasks"))
        run("INSERT INTO applications(volunteer_id,task_id,status,score) VALUES(?,?,?,?)",
            (session["user_id"], task_id, "Pending", result["score"]))
        run("INSERT INTO notifications(user_id,message,link_url) VALUES(?,?,?)",
            (session["user_id"],
             f"Application submitted for '{task['title']}' (Match: {result['score']*100:.2f}%). Status: Pending.",
             url_for("my_applications")))
        if task.get("organization_id"):
            run("INSERT INTO notifications(user_id,message,link_url) VALUES(?,?,?)",
                (task["organization_id"],
                 f"New application from {session.get('user_name','A volunteer')} for '{task['title']}'.",
                 url_for("manage_applications")))
        commit()
        flash("Application submitted! Pending approval by the organization.", "success")
    return redirect(url_for("my_applications"))


@app.route("/user/applications")
@require("volunteer")
def my_applications():
    apps = run(
        "SELECT applications.*, tasks.title, tasks.description AS task_description, tasks.location AS task_location, "
        "tasks.start_date, tasks.end_date, "
        "COALESCE(organization_profiles.organization_name, org_users.name, 'Organization') AS organization_name, "
        "organization_profiles.organization_type, "
        "COALESCE(organization_profiles.contact_email, org_users.email) AS contact_email, "
        "organization_profiles.contact_person, organization_profiles.phone AS contact_phone, "
        "organization_profiles.location AS organization_location, "
        "organization_profiles.logo_filename AS organization_logo "
        "FROM applications JOIN tasks ON tasks.id=applications.task_id "
        "LEFT JOIN users org_users ON org_users.id=tasks.organization_id "
        "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
        "WHERE applications.volunteer_id=? ORDER BY applications.id DESC",
        (session["user_id"],)
    ).fetchall()
    return render_template("my_applications.html", applications=apps)


@app.route("/user/my-applications")
@app.route("/my-applications")
def my_applications_legacy_redirect():
    return redirect(url_for("my_applications"))


# =============================================================================
#  NOTIFICATION ROUTES
# =============================================================================

@app.route("/user/notifications")
@require("volunteer", "organization", "admin")
def notifications():
    notes = run("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
    run("UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0", (session["user_id"],))
    commit()
    return render_template("notifications.html", notifications=notes)


@app.route("/user/notifications/mark-read", methods=("POST",))
def mark_notifications_read():
    if session.get("user_id"):
        run("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
        commit()
        flash("All notifications marked as read.", "success")
    return redirect(url_for("notifications"))


@app.route("/notifications")
def notifications_legacy_redirect():
    return redirect(url_for("notifications"))


@app.route("/user/notification/<int:notification_id>/click")
def click_notification(notification_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    note = run("SELECT * FROM notifications WHERE id=? AND user_id=?",
               (notification_id, session["user_id"])).fetchone()
    if note:
        run("UPDATE notifications SET is_read=1 WHERE id=?", (notification_id,))
        commit()
        if note.get("link_url"):
            return redirect(note["link_url"])
    return redirect(url_for("notifications"))


# =============================================================================
#  CATALOG API  (used by organization task form)
# =============================================================================

@app.route("/catalog/skills", methods=("POST",))
@require("organization", "admin")
def add_catalog_skill():
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name or len(name) > 120:
        return jsonify(success=False, message="Enter a skill name (max 120 characters)."), 400
    run("INSERT INTO skill_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (name,))
    commit()
    return jsonify(success=True, name=name, message=f"'{name}' added to skill list.")


@app.route("/catalog/interests", methods=("POST",))
@require("organization", "admin")
def add_catalog_interest():
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name or len(name) > 120:
        return jsonify(success=False, message="Enter an interest name (max 120 characters)."), 400
    run("INSERT INTO interest_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (name,))
    commit()
    return jsonify(success=True, name=name, message=f"'{name}' added to interest list.")


# =============================================================================
#  ORGANIZATION ROUTES
# =============================================================================

@app.route("/organization/dashboard")
@require("organization")
def organization_dashboard():
    my_tasks = run(
        "SELECT tasks.*, COUNT(applications.id) AS application_count FROM tasks "
        "LEFT JOIN applications ON applications.task_id=tasks.id "
        "WHERE tasks.organization_id=? GROUP BY tasks.id ORDER BY tasks.id DESC",
        (session["user_id"],)
    ).fetchall()
    app_rows = run(
        "SELECT applications.*, users.name AS volunteer_name, users.email AS volunteer_email, "
        "users.date_of_birth, TIMESTAMPDIFF(YEAR, users.date_of_birth, CURDATE()) AS age, "
        "tasks.title AS task_title, tasks.id AS task_id, "
        "volunteer_profiles.skills, volunteer_profiles.interests, volunteer_profiles.availability, "
        "volunteer_profiles.location, volunteer_profiles.photo_filename, volunteer_profiles.education_level "
        "FROM applications JOIN users ON users.id=applications.volunteer_id "
        "JOIN tasks ON tasks.id=applications.task_id "
        "LEFT JOIN volunteer_profiles ON volunteer_profiles.user_id=applications.volunteer_id "
        "WHERE tasks.organization_id=? ORDER BY applications.id DESC",
        (session["user_id"],)
    ).fetchall()
    my_applications = [{"app": row, "reviews": get_volunteer_reviews(row["volunteer_id"])} for row in app_rows]
    other_tasks = run(
        "SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'Other Organization') AS organization_name, "
        "COUNT(applications.id) AS application_count FROM tasks "
        "LEFT JOIN users ON users.id=tasks.organization_id "
        "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
        "LEFT JOIN applications ON applications.task_id=tasks.id "
        "WHERE tasks.organization_id != ? OR tasks.organization_id IS NULL "
        "GROUP BY tasks.id ORDER BY tasks.id DESC",
        (session["user_id"],)
    ).fetchall()
    counts = {"my_tasks": len(my_tasks), "applications": len(my_applications), "other_tasks": len(other_tasks)}
    return render_template("organization_dashboard.html",
                           counts=counts, my_tasks=my_tasks,
                           my_applications=my_applications, other_tasks=other_tasks)


@app.route("/organization")
def organization_legacy_redirect():
    return redirect(url_for("organization_dashboard"))


@app.route("/organization/profile", methods=("GET", "POST"))
@require("organization")
def organization_profile():
    org = run(
        "SELECT users.name, users.username, users.email, organization_profiles.* FROM users "
        "JOIN organization_profiles ON users.id=organization_profiles.user_id WHERE users.id=?",
        (session["user_id"],)
    ).fetchone()
    if request.method == "POST":
        org_name = request.form.get("organization_name", "").strip()
        username = request.form.get("username", "").strip()
        if username and username.lower() != (org["username"] or "").lower():
            if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
                flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
                return redirect(url_for("organization_profile"))
            if run("SELECT id FROM users WHERE lower(username)=lower(?) AND id!=?", (username, session["user_id"])).fetchone():
                flash("That username is already taken.", "warning")
                return redirect(url_for("organization_profile"))
        logo = save_image(request.files.get("logo"))
        if logo is False:
            flash("Use a PNG, JPG, GIF, or WEBP logo.", "danger")
            return redirect(url_for("organization_profile"))
        if logo is None:
            logo = org["logo_filename"] if org else None
        org_type      = request.form.get("organization_type", "Non-Governmental Organization (NGO)").strip()
        contact_email = request.form.get("contact_email", "").strip() or (org["email"] if org else "")
        run("UPDATE users SET name=?, username=? WHERE id=?",
            (org_name, username or (org["username"] if org else ""), session["user_id"]))
        run("UPDATE organization_profiles SET organization_name=?,organization_type=?,contact_person=?,contact_email=?,phone=?,location=?,description=?,logo_filename=? WHERE user_id=?",
            (org_name, org_type, request.form["contact_person"], contact_email,
             request.form["phone"], request.form["location"], request.form["description"], logo, session["user_id"]))
        commit()
        session["user_name"] = org_name
        flash("Organization profile updated.", "success")
        return redirect(url_for("organization_profile"))
    return render_template("organization_profile.html", organization=org)


@app.route("/organization/tasks", methods=("GET", "POST"))
@app.route("/admin/tasks", methods=("GET", "POST"))
@require("organization", "admin")
def manage_tasks():
    if request.method == "POST":
        if session.get("role") == "admin":
            flash("Tasks can only be created by organizations.", "warning")
            return redirect(url_for("manage_tasks"))
        if request.form["end_date"] < request.form["start_date"]:
            flash("End date must be on or after start date.", "danger")
            return redirect(url_for("manage_tasks"))
        skills    = [x.strip() for x in request.form.getlist("required_skills") + [request.form.get("new_skill", "")] if x.strip()]
        interests = [x.strip() for x in request.form.getlist("interests") + [request.form.get("new_interest", "")] if x.strip()]
        for s in skills:
            run("INSERT INTO skill_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (s,))
        for i in interests:
            run("INSERT INTO interest_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (i,))
        image   = save_image(request.files.get("task_image")) or "images/tasks/cleanup.svg"
        min_edu = request.form.get("min_education", "No Formal Education Required").strip()
        run("INSERT INTO tasks(title,description,required_skills,interests,availability,location,image_filename,organization_id,start_date,end_date,min_education) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (request.form["title"], request.form["description"], ", ".join(skills), ", ".join(interests),
             ", ".join(request.form.getlist("availability")), request.form["location"], image,
             session["user_id"] if session.get("role") == "organization" else None,
             request.form["start_date"], request.form["end_date"], min_edu))
        commit()
        flash("Task posted.", "success")
        return redirect(url_for("manage_tasks"))
    if session.get("role") == "admin":
        rows = run("SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'System Admin') AS organization_name "
                   "FROM tasks LEFT JOIN users ON users.id=tasks.organization_id "
                   "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id ORDER BY id DESC").fetchall()
    else:
        rows = run("SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'My Organization') AS organization_name "
                   "FROM tasks LEFT JOIN users ON users.id=tasks.organization_id "
                   "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
                   "WHERE tasks.organization_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
    skills    = run("SELECT name FROM skill_catalog ORDER BY name").fetchall()
    interests = run("SELECT name FROM interest_catalog ORDER BY name").fetchall()
    return render_template("manage_tasks.html", tasks=rows, skills=skills, interests=interests)


@app.route("/organization/task/<int:task_id>/edit", methods=("GET", "POST"))
@app.route("/admin/task/<int:task_id>/edit", methods=("GET", "POST"))
@require("organization", "admin")
def edit_task(task_id):
    task = run("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not owns(task):
        flash("You can only manage your own tasks.", "danger")
        return redirect(url_for("manage_tasks"))
    if request.method == "POST":
        if request.form["end_date"] < request.form["start_date"]:
            flash("End date must be on or after start date.", "danger")
            return redirect(url_for("edit_task", task_id=task_id))
        image = save_image(request.files.get("task_image"))
        if image is False:
            flash("Use a valid image file (PNG, JPG, WEBP).", "danger")
            return redirect(url_for("edit_task", task_id=task_id))
        if image is None:
            image = task["image_filename"]
        min_edu = request.form.get("min_education", "No Formal Education Required").strip()
        run("UPDATE tasks SET title=?,description=?,required_skills=?,interests=?,availability=?,location=?,start_date=?,end_date=?,image_filename=?,min_education=? WHERE id=?",
            (request.form["title"], request.form["description"], request.form["required_skills"],
             request.form["interests"], ", ".join(request.form.getlist("availability")),
             request.form["location"], request.form["start_date"], request.form["end_date"],
             image, min_edu, task_id))
        commit()
        flash("Task updated.", "success")
        return redirect(url_for("manage_tasks"))
    return render_template("edit_task.html", task=task)


@app.route("/organization/task/<int:task_id>/delete", methods=("POST",))
@app.route("/admin/task/<int:task_id>/delete", methods=("POST",))
@require("organization", "admin")
def delete_task(task_id):
    task = run("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if owns(task):
        run("DELETE FROM applications WHERE task_id=?", (task_id,))
        run("DELETE FROM tasks WHERE id=?", (task_id,))
        commit()
        flash("Task deleted.", "info")
    else:
        flash("You can only manage your own tasks.", "danger")
    return redirect(url_for("manage_tasks"))


@app.route("/organization/applications")
@app.route("/admin/applications")
@require("organization", "admin")
def manage_applications():
    base = ("SELECT applications.*, users.name, users.email, users.date_of_birth, "
            "TIMESTAMPDIFF(YEAR, users.date_of_birth, CURDATE()) AS age, "
            "tasks.title, tasks.organization_id, "
            "volunteer_profiles.skills, volunteer_profiles.interests, volunteer_profiles.availability, "
            "volunteer_profiles.location, volunteer_profiles.photo_filename, volunteer_profiles.education_level "
            "FROM applications JOIN users ON users.id=applications.volunteer_id "
            "JOIN tasks ON tasks.id=applications.task_id "
            "LEFT JOIN volunteer_profiles ON volunteer_profiles.user_id=applications.volunteer_id")
    if session.get("role") == "admin":
        apps = run(base + " ORDER BY applications.id DESC").fetchall()
    else:
        apps = run(base + " WHERE tasks.organization_id=? ORDER BY applications.id DESC", (session["user_id"],)).fetchall()
    applications_data = [(row, None, get_volunteer_reviews(row["volunteer_id"])) for row in apps]
    return render_template("manage_applications.html", applications_data=applications_data)


@app.route("/organization/application/<int:application_id>/<decision>", methods=("POST",))
@app.route("/admin/application/<int:application_id>/<decision>", methods=("POST",))
@require("organization", "admin")
def update_application(application_id, decision):
    record = run(
        "SELECT applications.volunteer_id, tasks.title, tasks.organization_id "
        "FROM applications JOIN tasks ON tasks.id=applications.task_id WHERE applications.id=?",
        (application_id,)
    ).fetchone()
    if decision in ("Accepted", "Rejected", "Completed") and owns(record):
        if decision == "Completed":
            run("UPDATE applications SET status=?, review_text=?, rating=? WHERE id=?",
                (decision, request.form.get("review_text", "").strip(),
                 request.form.get("rating", 5, type=int), application_id))
            msg = f"Your work for '{record['title']}' was marked COMPLETED. Thank you!"
        elif decision == "Accepted":
            run("UPDATE applications SET status=? WHERE id=?", (decision, application_id))
            msg = f"Your application for '{record['title']}' was APPROVED."
        else:
            run("UPDATE applications SET status=? WHERE id=?", (decision, application_id))
            msg = f"Your application for '{record['title']}' was REJECTED."
        run("INSERT INTO notifications(user_id,message,link_url) VALUES(?,?,?)",
            (record["volunteer_id"], msg, url_for("my_applications")))
        commit()
        flash(f"Application updated to {decision}.", "success")
    return redirect(request.referrer or url_for("manage_applications"))


# =============================================================================
#  ADMIN ROUTES
# =============================================================================

@app.route("/admin/login", methods=("GET", "POST"))
@app.route("/admin", methods=("GET", "POST"))
def admin_login():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        identifier = request.form["identifier"].strip()
        user = run("SELECT * FROM users WHERE role='admin' AND (lower(email)=lower(?) OR lower(username)=lower(?))",
                   (identifier, identifier)).fetchone()
        if user and check_password_hash(user["password"], request.form["password"]):
            session.clear()
            session["user_id"]   = user["id"]
            session["user_name"] = user["name"]
            session["role"]      = user["role"]
            flash("Administrator login successful.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid administrator credentials.", "danger")
    return render_template("admin_login.html")


@app.route("/admin/dashboard")
@require("admin")
def admin_dashboard():
    counts = {
        "volunteers":    run("SELECT COUNT(*) AS n FROM users WHERE role='volunteer'").fetchone()["n"],
        "organizations": run("SELECT COUNT(*) AS n FROM users WHERE role='organization'").fetchone()["n"],
        "tasks":         run("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"],
        "applications":  run("SELECT COUNT(*) AS n FROM applications").fetchone()["n"],
        "education_types": run("SELECT COUNT(*) AS n FROM education_catalog").fetchone()["n"]
            if run("SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='education_catalog'").fetchone()["n"] > 0 else 0,
    }
    top_tasks = run(
        "SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'System Admin') AS organization_name, "
        "COUNT(applications.id) AS application_count "
        "FROM tasks LEFT JOIN users ON users.id=tasks.organization_id "
        "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
        "LEFT JOIN applications ON applications.task_id=tasks.id "
        "GROUP BY tasks.id ORDER BY tasks.id DESC LIMIT 6"
    ).fetchall()
    recent_notifications = run("SELECT * FROM notifications ORDER BY id DESC LIMIT 5").fetchall()
    return render_template("admin_dashboard.html", counts=counts, top_tasks=top_tasks,
                           recent_notifications=recent_notifications)


@app.route("/admin/catalogs", methods=("GET", "POST"))
@require("admin")
def manage_catalogs():
    if request.method == "POST":
        catalog_type = request.form.get("catalog_type", "").strip()
        name         = request.form.get("name", "").strip()
        if not name or len(name) > 120:
            flash("Enter a name with up to 120 characters.", "warning")
        elif catalog_type == "skill":
            run("INSERT INTO skill_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (name,))
            commit()
            flash(f"Skill '{name}' added.", "success")
        elif catalog_type == "interest":
            run("INSERT INTO interest_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (name,))
            commit()
            flash(f"Interest '{name}' added.", "success")
        else:
            category   = request.form.get("category", "both").strip()
            rank_level = request.form.get("rank_level", 1, type=int)
            if run("SELECT id FROM education_catalog WHERE lower(name)=lower(?)", (name,)).fetchone():
                flash("That education type already exists.", "warning")
            else:
                run("INSERT INTO education_catalog(name, category, rank_level) VALUES(?,?,?)",
                    (name, category, rank_level))
                commit()
                flash(f"Education type '{name}' added.", "success")
        return redirect(url_for("manage_catalogs"))
    skills   = run("SELECT * FROM skill_catalog ORDER BY name ASC").fetchall()
    interests = run("SELECT * FROM interest_catalog ORDER BY name ASC").fetchall()
    edu_list = run("SELECT * FROM education_catalog ORDER BY rank_level ASC, id ASC").fetchall()
    return render_template("manage_catalogs.html", skills=skills, interests=interests, education_list=edu_list)


@app.route("/admin/education", methods=("GET", "POST"))
@require("admin")
def manage_education():
    return manage_catalogs()


@app.route("/admin/education/<int:education_id>/delete", methods=("POST",))
@require("admin")
def delete_education(education_id):
    item = run("SELECT * FROM education_catalog WHERE id=?", (education_id,)).fetchone()
    if item:
        run("DELETE FROM education_catalog WHERE id=?", (education_id,))
        commit()
        flash(f"Education type '{item['name']}' deleted.", "info")
    return redirect(url_for("manage_catalogs"))


@app.route("/admin/catalog/skill/<int:skill_id>/delete", methods=("POST",))
@require("admin")
def delete_catalog_skill(skill_id):
    item = run("SELECT * FROM skill_catalog WHERE id=?", (skill_id,)).fetchone()
    if item:
        run("DELETE FROM skill_catalog WHERE id=?", (skill_id,))
        commit()
        flash(f"Skill '{item['name']}' removed.", "info")
    return redirect(url_for("manage_catalogs"))


@app.route("/admin/catalog/interest/<int:interest_id>/delete", methods=("POST",))
@require("admin")
def delete_catalog_interest(interest_id):
    item = run("SELECT * FROM interest_catalog WHERE id=?", (interest_id,)).fetchone()
    if item:
        run("DELETE FROM interest_catalog WHERE id=?", (interest_id,))
        commit()
        flash(f"Interest '{item['name']}' removed.", "info")
    return redirect(url_for("manage_catalogs"))


@app.route("/admin/profile", methods=("GET", "POST"))
@require("admin")
def admin_profile():
    admin = run("SELECT * FROM users WHERE id=? AND role='admin'", (session["user_id"],)).fetchone()
    if not admin:
        session.clear()
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")
        if not name or not username or not email:
            flash("Name, username, and email are required.", "warning")
        elif not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
        elif run("SELECT id FROM users WHERE lower(username)=lower(?) AND id!=?", (username, admin["id"])).fetchone():
            flash("That username is already taken.", "warning")
        elif run("SELECT id FROM users WHERE lower(email)=lower(?) AND id!=?", (email, admin["id"])).fetchone():
            flash("That email is already registered.", "warning")
        elif password != confirm:
            flash("Passwords do not match.", "warning")
        elif password and len(password) < 6:
            flash("Password must be at least 6 characters.", "warning")
        else:
            photo = save_image(request.files.get("photo"))
            if photo is False:
                flash("Profile image must be PNG, JPG, JPEG, GIF, or WEBP.", "warning")
                return render_template("admin_profile.html", admin=admin)
            if photo is None:
                photo = admin["photo_filename"]
            run("UPDATE users SET name=?,username=?,email=?,photo_filename=? WHERE id=?",
                (name, username, email, photo, admin["id"]))
            if password:
                run("UPDATE users SET password=? WHERE id=?", (generate_password_hash(password), admin["id"]))
            commit()
            session["user_name"] = name
            flash("Admin profile updated.", "success")
            return redirect(url_for("admin_profile"))
    return render_template("admin_profile.html", admin=admin)


@app.route("/admin/volunteers")
@require("admin")
def manage_volunteers():
    rows = run(
        "SELECT users.*, TIMESTAMPDIFF(YEAR, users.date_of_birth, CURDATE()) AS age, "
        "volunteer_profiles.skills, volunteer_profiles.interests, volunteer_profiles.availability, "
        "volunteer_profiles.location, volunteer_profiles.photo_filename AS profile_photo, "
        "volunteer_profiles.education_level, "
        "SUM(CASE WHEN applications.status='Completed' THEN 1 ELSE 0 END) completed_count "
        "FROM users LEFT JOIN volunteer_profiles ON users.id=volunteer_profiles.user_id "
        "LEFT JOIN applications ON users.id=applications.volunteer_id "
        "WHERE users.role='volunteer' GROUP BY users.id"
    ).fetchall()
    return render_template("manage_volunteers.html", volunteers=rows)


@app.route("/admin/volunteer/<int:volunteer_id>", methods=("GET", "POST"))
@require("admin")
def edit_volunteer(volunteer_id):
    volunteer = run(
        "SELECT users.*, volunteer_profiles.skills, volunteer_profiles.interests, "
        "volunteer_profiles.availability, volunteer_profiles.location, "
        "volunteer_profiles.photo_filename AS profile_photo, volunteer_profiles.education_level "
        "FROM users LEFT JOIN volunteer_profiles ON users.id=volunteer_profiles.user_id "
        "WHERE users.id=? AND users.role='volunteer'",
        (volunteer_id,)
    ).fetchone()
    if not volunteer:
        return redirect(url_for("manage_volunteers"))
    if request.method == "POST":
        pwd     = request.form.get("password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()
        if pwd or confirm:
            if pwd != confirm:
                flash("Passwords do not match.", "warning")
                return render_template("edit_volunteer.html", volunteer=volunteer)
            if len(pwd) < 6:
                flash("Password must be at least 6 characters.", "warning")
                return render_template("edit_volunteer.html", volunteer=volunteer)
            run("UPDATE users SET password=? WHERE id=?", (generate_password_hash(pwd), volunteer_id))
        username = request.form.get("username", "").strip()
        if username and not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
            return render_template("edit_volunteer.html", volunteer=volunteer)
        photo = save_image(request.files.get("photo"))
        if photo is False:
            flash("Profile image must be PNG, JPG, JPEG, GIF, or WEBP.", "warning")
            return render_template("edit_volunteer.html", volunteer=volunteer)
        if photo is None:
            photo = volunteer["profile_photo"]
        run("UPDATE users SET name=?,username=?,email=?,date_of_birth=? WHERE id=?",
            (request.form["name"], username or volunteer["username"],
             request.form["email"], request.form.get("date_of_birth"), volunteer_id))
        edu   = request.form.get("education_level", "Intermediate (10+2) / High School").strip()
        vals  = (request.form["skills"], request.form["interests"],
                 ", ".join(request.form.getlist("availability")),
                 request.form["location"], photo, edu, volunteer_id)
        if run("SELECT id FROM volunteer_profiles WHERE user_id=?", (volunteer_id,)).fetchone():
            run("UPDATE volunteer_profiles SET skills=?,interests=?,availability=?,location=?,photo_filename=?,education_level=? WHERE user_id=?", vals)
        else:
            run("INSERT INTO volunteer_profiles(skills,interests,availability,location,photo_filename,education_level,user_id) VALUES(?,?,?,?,?,?,?)", vals)
        commit()
        refresh_applications(volunteer_id)
        flash("Volunteer updated.", "success")
        return redirect(url_for("manage_volunteers"))
    return render_template("edit_volunteer.html", volunteer=volunteer)


@app.route("/admin/volunteer/<int:volunteer_id>/delete", methods=("POST",))
@require("admin")
def delete_volunteer(volunteer_id):
    run("DELETE FROM notifications WHERE user_id=?", (volunteer_id,))
    run("DELETE FROM applications WHERE volunteer_id=?", (volunteer_id,))
    run("DELETE FROM volunteer_profiles WHERE user_id=?", (volunteer_id,))
    run("DELETE FROM users WHERE id=? AND role='volunteer'", (volunteer_id,))
    commit()
    flash("Volunteer deleted.", "info")
    return redirect(url_for("manage_volunteers"))


@app.route("/admin/organizations")
@require("admin")
def manage_organizations():
    rows = run(
        "SELECT users.*, organization_profiles.organization_name, organization_profiles.organization_type, "
        "organization_profiles.logo_filename, organization_profiles.contact_person, "
        "organization_profiles.phone, organization_profiles.location, organization_profiles.description, "
        "COUNT(tasks.id) task_count, GROUP_CONCAT(tasks.title SEPARATOR ' | ') posted_work "
        "FROM users JOIN organization_profiles ON users.id=organization_profiles.user_id "
        "LEFT JOIN tasks ON users.id=tasks.organization_id "
        "WHERE users.role='organization' GROUP BY users.id"
    ).fetchall()
    return render_template("manage_organizations.html", organizations=rows)


@app.route("/admin/organization/<int:organization_id>/works")
@require("admin")
def organization_works(organization_id):
    organization = run(
        "SELECT users.name, organization_profiles.organization_name "
        "FROM users LEFT JOIN organization_profiles ON users.id=organization_profiles.user_id "
        "WHERE users.id=? AND users.role='organization'",
        (organization_id,)
    ).fetchone()
    if not organization:
        return redirect(url_for("manage_organizations"))
    works = run("SELECT * FROM tasks WHERE organization_id=? ORDER BY id DESC", (organization_id,)).fetchall()
    return render_template("organization_works.html", organization=organization, works=works)


@app.route("/admin/organization/<int:organization_id>", methods=("GET", "POST"))
@require("admin")
def edit_organization(organization_id):
    org = run(
        "SELECT users.*, organization_profiles.* FROM users "
        "JOIN organization_profiles ON users.id=organization_profiles.user_id WHERE users.id=?",
        (organization_id,)
    ).fetchone()
    if not org:
        return redirect(url_for("manage_organizations"))
    if request.method == "POST":
        pwd     = request.form.get("password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()
        if pwd or confirm:
            if pwd != confirm:
                flash("Passwords do not match.", "warning")
                return render_template("edit_organization.html", organization=org)
            if len(pwd) < 6:
                flash("Password must be at least 6 characters.", "warning")
                return render_template("edit_organization.html", organization=org)
            run("UPDATE users SET password=? WHERE id=?", (generate_password_hash(pwd), organization_id))
        username = request.form.get("username", "").strip()
        if username and not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
            return render_template("edit_organization.html", organization=org)
        logo = save_image(request.files.get("logo"))
        if logo is False:
            flash("Logo must be PNG, JPG, JPEG, GIF, or WEBP.", "warning")
            return render_template("edit_organization.html", organization=org)
        if logo is None:
            logo = org["logo_filename"] if org else None
        org_type      = request.form.get("organization_type", "Non-Governmental Organization (NGO)").strip()
        contact_email = request.form.get("contact_email", "").strip() or request.form["email"]
        run("UPDATE users SET name=?,username=?,email=? WHERE id=?",
            (request.form["organization_name"], username or org["username"], request.form["email"], organization_id))
        run("UPDATE organization_profiles SET organization_name=?,organization_type=?,contact_person=?,contact_email=?,phone=?,location=?,description=?,logo_filename=? WHERE user_id=?",
            (request.form["organization_name"], org_type, request.form["contact_person"], contact_email,
             request.form["phone"], request.form["location"], request.form["description"], logo, organization_id))
        commit()
        flash("Organization updated.", "success")
        return redirect(url_for("manage_organizations"))
    return render_template("edit_organization.html", organization=org)


# =============================================================================
#  START
# =============================================================================

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True)
