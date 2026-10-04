import os
import re
from functools import wraps
from uuid import uuid4
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
import mysql.connector
from mysql.connector import Error as MySQLError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from services.matching import jaccard_similarity, terms

app = Flask(__name__)
app.secret_key = "change-this-before-deploying"
app.config["MYSQL_USER"] = os.environ.get("MYSQL_USER", "root")
app.config["MYSQL_PASSWORD"] = os.environ.get("MYSQL_PASSWORD", "")
# This project uses one fixed XAMPP MySQL database.
app.config["MYSQL_DATABASE"] = "community_volinturee"
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")


# Database helpers: the rest of the file can use run() for every SQL query.

def connect_mysql(with_database=True):
    db_name = app.config["MYSQL_DATABASE"] if with_database else None
    xampp_socket = "/Applications/XAMPP/xamppfiles/var/mysql/mysql.sock"
    if not os.path.exists(xampp_socket):
        raise MySQLError("XAMPP MySQL is currently turned OFF. Please start MySQL in XAMPP.")

    config = {
        "unix_socket": xampp_socket,
        "user": app.config["MYSQL_USER"],
        "password": app.config["MYSQL_PASSWORD"],
        "connection_timeout": 3,
    }
    if db_name:
        config["database"] = db_name
    return mysql.connector.connect(**config)


def db():
    if "db" not in g:
        g.db = connect_mysql(with_database=True)
    return g.db


def run(query, values=()):
    """Run one MySQL query. Question marks keep SQL easier to read in Python."""
    cursor = db().cursor(dictionary=True, buffered=True)
    cursor.execute(query.replace("?", "%s"), values)
    return cursor


def commit():
    db().commit()


@app.teardown_appcontext
def close_db(error=None):
    connection = g.pop("db", None)
    if connection:
        try:
            connection.close()
        except Exception:
            pass


@app.errorhandler(MySQLError)
def handle_mysql_error(error):
    app.logger.error("MySQL Database Error: %s", error)
    flash("Database is offline. Start MySQL in XAMPP and try again.", "warning")
    return redirect(url_for("home"))


def require(*roles):
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


def save_image(upload):
    """Save an allowed uploaded image and return its path for the database."""
    if not upload or not upload.filename:
        return None
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
        return False
    name = f"{uuid4().hex}_{secure_filename(upload.filename)}"
    upload.save(os.path.join(app.config["UPLOAD_FOLDER"], name))
    return f"uploads/{name}"


# ── Education & Qualification Matching Constants ──

VOLUNTEER_EDUCATION_OPTIONS = [
    "Uneducated / Basic Literacy",
    "SEE / SLC (Secondary School)",
    "Intermediate (10+2) / High School",
    "Bachelor's Running",
    "Bachelor's Degree",
    "Master's Running",
    "Master's Degree",
    "M.Phil / Ph.D.",
]

TASK_MIN_EDUCATION_OPTIONS = [
    "No Formal Education Required",
    "SEE / SLC (Secondary School)",
    "Intermediate (10+2) / High School",
    "Bachelor's Level",
    "Master's Level",
    "Ph.D. / Specialised Degree",
]

EDUCATION_RANK_VOLUNTEER = {
    "Uneducated / Basic Literacy": 1,
    "SEE / SLC (Secondary School)": 2,
    "Intermediate (10+2) / High School": 3,
    "Bachelor's Running": 4,
    "Bachelor's Degree": 5,
    "Master's Running": 6,
    "Master's Degree": 7,
    "M.Phil / Ph.D.": 8,
}

EDUCATION_RANK_TASK = {
    "No Formal Education Required": 1,
    "SEE / SLC (Secondary School)": 2,
    "Intermediate (10+2) / High School": 3,
    "Bachelor's Level": 4,
    "Master's Level": 6,
    "Ph.D. / Specialised Degree": 8,
}


ORGANIZATION_TYPE_OPTIONS = [
    "Non-Governmental Organization (NGO)",
    "Government Organization",
    "International NGO (INGO)",
    "Non-Profit / Charity Foundation",
    "Red Cross / Emergency Relief",
    "Community / Youth Club",
    "Educational Institution / School",
    "Private / Corporate Social Responsibility (CSR)"
]


def get_education_lists():
    try:
        rows = run("SELECT * FROM education_catalog ORDER BY rank_level ASC, id ASC").fetchall()
        if rows:
            v_opts = [r["name"] for r in rows if r.get("category") in ("volunteer", "both")]
            t_opts = [r["name"] for r in rows if r.get("category") in ("task", "both")]
            v_ranks = {r["name"]: r["rank_level"] for r in rows if r.get("category") in ("volunteer", "both")}
            t_ranks = {r["name"]: r["rank_level"] for r in rows if r.get("category") in ("task", "both")}
            return v_opts, t_opts, v_ranks, t_ranks
    except Exception:
        pass
    return (
        VOLUNTEER_EDUCATION_OPTIONS,
        TASK_MIN_EDUCATION_OPTIONS,
        EDUCATION_RANK_VOLUNTEER,
        EDUCATION_RANK_TASK,
    )


def check_education_qualification(vol_edu, task_min_edu):
    if not task_min_edu or task_min_edu == "No Formal Education Required":
        return True
    _, _, v_ranks, t_ranks = get_education_lists()
    vol_rank = v_ranks.get(vol_edu, EDUCATION_RANK_VOLUNTEER.get(vol_edu, 1))
    task_rank = t_ranks.get(task_min_edu, EDUCATION_RANK_TASK.get(task_min_edu, 1))
    return vol_rank >= task_rank


def match_details(profile, task):
    """Use Jaccard similarity, available days, and education to check one task."""
    # Jaccard returns the score and the two normalised skill sets in one step.
    score, volunteer_skills, required_skills, common_skills, _ = jaccard_similarity(
        profile["skills"], task["required_skills"]
    )
    _, _, _, common_days, _ = jaccard_similarity(profile["availability"], task["availability"])
    all_skills_match = bool(required_skills) and required_skills.issubset(volunteer_skills)
    vol_edu = profile.get("education_level") or "Uneducated / Basic Literacy"
    task_min_edu = task.get("min_education") or "No Formal Education Required"
    edu_qualified = check_education_qualification(vol_edu, task_min_edu)

    # A volunteer qualifies with all skills or a 40%+ match, a shared free day,
    # and the required education level.
    is_qualified = (all_skills_match or score >= 0.40) and bool(common_days) and edu_qualified
    return {
        "score": score,
        "common_skills": sorted(common_skills),
        "common_days": sorted(common_days),
        "all_skills_match": all_skills_match,
        "edu_qualified": edu_qualified,
        "qualified": is_qualified,
    }


def refresh_applications(volunteer_id):
    """Recalculate saved applications after a volunteer changes their profile."""
    profile = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (volunteer_id,)).fetchone()
    if not profile:
        return
    records = run(
        "SELECT applications.id AS application_id, applications.status AS application_status, tasks.* FROM applications "
        "JOIN tasks ON tasks.id=applications.task_id WHERE applications.volunteer_id=?",
        (volunteer_id,)
    ).fetchall()
    for record in records:
        result = match_details(profile, record)
        if record["application_status"] not in ("Accepted", "Rejected", "Completed"):
            status = "Pending" if result["qualified"] else "Not qualified"
            run("UPDATE applications SET score=?, status=? WHERE id=?", (result["score"], status, record["application_id"]))
    commit()


def get_volunteer_reviews(volunteer_id):
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
            (volunteer_id,)
        ).fetchall()
    except MySQLError:
        return []


def tasks_with_matches(rows):
    profile = None
    if session.get("role") == "volunteer":
        profile = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (session["user_id"],)).fetchone()
    return [(task, match_details(profile, task) if profile else None) for task in rows]


def owns(task):
    return session.get("role") == "admin" or (task and task["organization_id"] == session.get("user_id"))


@app.context_processor
def nav():
    photo = None
    unread_count = 0
    if session.get("user_id"):
        try:
            row = run("SELECT COUNT(*) AS unread FROM notifications WHERE user_id=? AND is_read=0", (session["user_id"],)).fetchone()
            if row:
                unread_count = row["unread"]
        except MySQLError:
            pass

    if session.get("role") == "volunteer":
        try:
            row = run("SELECT photo_filename FROM volunteer_profiles WHERE user_id=?", (session["user_id"],)).fetchone()
            if row and row["photo_filename"]:
                photo = row["photo_filename"]
        except MySQLError:
            pass
    elif session.get("role") == "admin":
        try:
            row = run("SELECT photo_filename FROM users WHERE id=?", (session["user_id"],)).fetchone()
            if row and row["photo_filename"]:
                photo = row["photo_filename"]
        except MySQLError:
            pass
    elif session.get("role") == "organization":
        try:
            row = run("SELECT logo_filename FROM organization_profiles WHERE user_id=?", (session["user_id"],)).fetchone()
            if row and row["logo_filename"]:
                photo = row["logo_filename"]
        except MySQLError:
            pass
    v_opts, t_opts, _, _ = get_education_lists()
    return {
        "nav_photo": photo,
        "unread_notifications": unread_count,
        "VOLUNTEER_EDUCATION_OPTIONS": v_opts,
        "TASK_MIN_EDUCATION_OPTIONS": t_opts,
        "ORGANIZATION_TYPE_OPTIONS": ORGANIZATION_TYPE_OPTIONS,
    }


def add_column_if_missing(table, column, definition):
    """Keep older project databases compatible with the current schema."""
    found = run(
        "SELECT COUNT(*) AS total FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=? AND column_name=?",
        (table, column),
    ).fetchone()
    if found["total"] == 0:
        # Table, column, and definition below are fixed project values, not user input.
        run(f"ALTER TABLE `{table}` ADD `{column}` {definition}")


# Create the database/tables once, then add the small amount of sample data.

def init_db():
    try:
        db_name = app.config["MYSQL_DATABASE"]
        if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
            raise ValueError("MYSQL_DATABASE can only contain letters, numbers, and underscores.")

        conn = connect_mysql(with_database=False)
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4")
        conn.commit()
        cursor.close()
        conn.close()
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

        with app.open_resource("schema.sql") as f:
            for statement in f.read().decode().split(";"):
                if statement.strip():
                    run(statement)

        # These migrations only run when someone uses an older version of the database.
        missing_columns = [
            ("users", "username", "VARCHAR(60) NULL UNIQUE AFTER name"),
            ("users", "photo_filename", "VARCHAR(255) NULL"),
            ("applications", "review_text", "TEXT NULL"),
            ("applications", "rating", "INT NULL DEFAULT 5"),
            ("applications", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            ("volunteer_profiles", "education_level", "VARCHAR(100) NULL DEFAULT 'Intermediate (10+2) / High School'"),
            ("tasks", "min_education", "VARCHAR(100) NULL DEFAULT 'No Formal Education Required'"),
            ("notifications", "link_url", "VARCHAR(255) NULL"),
            ("organization_profiles", "organization_type", "VARCHAR(100) NULL DEFAULT 'Non-Governmental Organization (NGO)'"),
            ("organization_profiles", "contact_email", "VARCHAR(190) NULL"),
        ]
        for table, column, definition in missing_columns:
            add_column_if_missing(table, column, definition)

        for skill in "Communication,Teaching,First Aid,Computer,Programming,Graphic Design,Photography,Cooking,Driving,Organizing,Teamwork,Gardening,Fundraising,Social Media,Translation,Accounting,Counselling,Childcare,Elder Care,Event Planning,Cleaning,Research".split(","):
            run("INSERT INTO skill_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (skill,))

        for interest in "Education,Technology,Environment,Community,Food Support,Health,Sports,Animals,Arts,Music,Reading,Youth,Women Empowerment,Disaster Relief,Culture,Outdoors".split(","):
            run("INSERT INTO interest_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (interest,))

        default_edu_types = [
            ("Uneducated / Basic Literacy", "volunteer", 1),
            ("SEE / SLC (Secondary School)", "both", 2),
            ("Intermediate (10+2) / High School", "both", 3),
            ("Bachelor's Running", "volunteer", 4),
            ("Bachelor's Level", "task", 4),
            ("Bachelor's Degree", "volunteer", 5),
            ("Master's Running", "volunteer", 6),
            ("Master's Level", "task", 6),
            ("Master's Degree", "volunteer", 7),
            ("M.Phil / Ph.D.", "volunteer", 8),
            ("Ph.D. / Specialised Degree", "task", 8),
            ("No Formal Education Required", "task", 1),
        ]
        for name, cat, rk in default_edu_types:
            run("INSERT INTO education_catalog(name, category, rank_level) VALUES(?,?,?) ON DUPLICATE KEY UPDATE category=category", (name, cat, rk))

        if not run("SELECT id FROM users WHERE email=?", ("admin@gmail.com",)).fetchone():
            run("INSERT INTO users(name,username,email,password,role) VALUES(?,?,?,?,?)",
                ("System Administrator", "admin", "admin@gmail.com", generate_password_hash("admin123"), "admin"))

        demo_volunteers = [
            ("Bashanta Pokharel", "bashanta27", "bashanta@gmail.com", "Communication, Teamwork, Programming, Teaching, First Aid, Computer, Graphic Design, Photography, Event Planning", "Technology, Community", "Monday, Wednesday, Saturday", "Kathmandu"),
            ("Sweekriti Karki", "sweekriti42", "sweekriti@gmail.com", "Teaching, First Aid, Event Planning, Communication, Teamwork, Childcare, Counselling, Research, Translation", "Education, Youth", "Tuesday, Thursday, Sunday", "Lalitpur"),
            ("Kusum Dahal", "kusum65", "kusum@gmail.com", "Cooking, Organizing, Fundraising, Communication, Teamwork, Driving, Accounting, Event Planning, Cleaning", "Food Support, Community", "Monday, Friday, Saturday", "Bhaktapur"),
            ("Aagaman Adhakari", "aagaman18", "aagaman@gmail.com", "Graphic Design, Social Media, Photography, Programming, Communication, Teamwork, Research, Event Planning, Translation", "Arts, Technology", "Tuesday, Thursday, Sunday", "Kathmandu"),
            ("Bhuban Subedi", "bhuban83", "bhuban@gmail.com", "Gardening, Cleaning, Teamwork, Communication, Organizing, First Aid, Driving, Research, Event Planning", "Environment, Outdoors", "Wednesday, Friday, Saturday", "Lalitpur"),
        ]
        old_demo_skills = {
            "bashanta@gmail.com": "Communication, Teamwork, Programming",
            "sweekriti@gmail.com": "Teaching, First Aid, Event Planning",
            "kusum@gmail.com": "Cooking, Organizing, Fundraising",
            "aagaman@gmail.com": "Graphic Design, Social Media, Photography",
            "bhuban@gmail.com": "Gardening, Cleaning, Teamwork",
        }
        for name, username, email, skills, interests, days, location in demo_volunteers:
            existing_user = run("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not existing_user:
                vid = run("INSERT INTO users(name,username,email,password,role,date_of_birth) VALUES(?,?,?,?,'volunteer',?)",
                          (name, username, email, generate_password_hash("Bashanta123"), "2000-01-01")).lastrowid
                run("INSERT INTO volunteer_profiles(user_id,skills,interests,availability,location) VALUES(?,?,?,?,?)",
                    (vid, skills, interests, days, location))
            else:
                profile = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (existing_user["id"],)).fetchone()
                if not profile:
                    run("INSERT INTO volunteer_profiles(user_id,skills,interests,availability,location) VALUES(?,?,?,?,?)",
                        (existing_user["id"], skills, interests, days, location))
                elif profile["skills"] == old_demo_skills[email]:
                    run("UPDATE volunteer_profiles SET skills=? WHERE user_id=?", (skills, existing_user["id"]))

        demo_orgs = [
            ("Community Action Nepal", "communityaction57", "communityaction@gmail.com", "Community Coordinator", "9800000000", "Kathmandu", "Community support and local volunteering.", "Community / Youth Club", "uploads/community_action_logo.svg"),
            ("Green Nepal Alliance", "greennepal64", "greennepal@gmail.com", "Environment Coordinator", "9800000001", "Kathmandu", "Environmental clean-up and tree planting initiative.", "Non-Profit / Charity Foundation", "uploads/green_nepal_logo.svg"),
            ("Kathmandu Food Relief", "foodrelief39", "foodrelief@gmail.com", "Food Bank Coordinator", "9800000002", "Lalitpur", "Food collection and family nutrition support.", "Non-Profit / Charity Foundation", "uploads/food_relief_logo.svg"),
            ("Bright Futures Youth Foundation", "brightfutures21", "brightfutures@gmail.com", "Education Coordinator", "9800000003", "Bhaktapur", "Youth development and child education support.", "Educational Institution / School", "uploads/bright_futures_logo.svg"),
            ("Digital Skills Nepal", "digitalskills76", "digitalskills@gmail.com", "Digital Coordinator", "9800000004", "Kathmandu", "Digital literacy and technology training.", "Non-Governmental Organization (NGO)", "uploads/digital_skills_logo.svg"),
            ("Care & Compassion Nepal", "caretogether48", "caretogether@gmail.com", "Care Coordinator", "9800000005", "Lalitpur", "Care, wellness, and elderly support activities.", "Non-Profit / Charity Foundation", "uploads/care_compassion_logo.svg"),
            ("Himalayan Animal Rescue", "animalrescue99", "animalrescue@gmail.com", "Animal Shelter Manager", "9800000006", "Kathmandu", "Rescuing and caring for community animals.", "Non-Profit / Charity Foundation", "uploads/animal_rescue_logo.svg"),
            ("Nepal Eco & Heritage Initiative", "ecoheritage15", "ecoheritage@gmail.com", "Heritage Officer", "9800000007", "Bhaktapur", "Preserving local eco-parks and heritage trails.", "Non-Governmental Organization (NGO)", "uploads/eco_heritage_logo.svg"),
            ("Red Cross Community Relief (Demo)", "redcrossrelief", "redcrossrelief@gmail.com", "Relief Coordinator", "9800000008", "Kathmandu", "A classroom demonstration organization for first aid, emergency preparedness, and community relief work.", "Red Cross / Emergency Relief", "uploads/red_cross_relief_logo.svg"),
        ]

        org_ids = []
        for name, username, email, contact, phone, location, desc, org_type, logo in demo_orgs:
            user = run("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not user:
                oid = run("INSERT INTO users(name,username,email,password,role) VALUES(?,?,?,?,?)",
                          (name, username, email, generate_password_hash("Organization123"), "organization")).lastrowid
                run("INSERT INTO organization_profiles(user_id,organization_name,organization_type,contact_person,contact_email,phone,location,description,logo_filename) VALUES(?,?,?,?,?,?,?,?,?)",
                    (oid, name, org_type, contact, email, phone, location, desc, logo))
                org_ids.append(oid)
            else:
                org_ids.append(user["id"])
                run("UPDATE organization_profiles SET logo_filename=? WHERE user_id=? AND (logo_filename IS NULL OR logo_filename='')",
                    (logo, user["id"]))

        demo_tasks = [
            ("Community Clean-up Drive", "Help clean and improve a public community space in Kathmandu.", "Cleaning, Teamwork", "Community, Environment", "Wednesday, Saturday", "Kathmandu", "images/tasks/cleanup.svg", org_ids[0], "2026-10-10", "2026-10-31"),
            ("Neighbourhood Garden Day", "Plant flowers and care for a shared community garden.", "Gardening, Teamwork", "Environment, Community", "Monday, Saturday", "Kathmandu", "images/tasks/garden.svg", org_ids[0], "2026-10-12", "2026-11-12"),

            ("City Park Tree Planting", "Plant young trees and install protective guards in public parks.", "Gardening, Teamwork", "Environment, Outdoors", "Friday, Saturday", "Kathmandu", "images/tasks/garden.svg", org_ids[1], "2026-10-14", "2026-11-14"),
            ("Bagmati Riverbank Cleanup", "Collect waste and sort recyclables along the riverbank.", "Cleaning, Organizing", "Environment, Community", "Sunday", "Kathmandu", "images/tasks/cleanup.svg", org_ids[1], "2026-10-18", "2026-11-18"),

            ("Food Package Assembly & Serving", "Help sort donated food items and serve warm meals to community members.", "Cooking, Teamwork, Organizing", "Food Support, Community", "Monday, Friday", "Lalitpur", "images/tasks/food_real.jpg", org_ids[2], "2026-10-11", "2026-11-11"),
            ("Fresh Food Kitchen Assistant", "Prepare and package nutritious meals for family distribution.", "Cooking, Communication", "Food Support, Community", "Saturday", "Lalitpur", "images/tasks/food_real.jpg", org_ids[2], "2026-10-16", "2026-11-16"),

            ("Children's Reading Buddy Program", "Read storybooks and mentor young learners in Bhaktapur.", "Teaching, Communication", "Education, Reading", "Tuesday, Thursday", "Bhaktapur", "images/tasks/reading_real.jpg", org_ids[3], "2026-10-13", "2026-11-13"),
            ("Youth Creative Learning Workshop", "Support children during a weekend art, games, and learning workshop.", "Teaching, Event Planning", "Education, Youth", "Sunday", "Bhaktapur", "images/tasks/reading_real.jpg", org_ids[3], "2026-10-20", "2026-11-20"),

            ("Senior Citizens Tech Literacy Class", "Guide beginners step-by-step to use laptops, internet, and phones.", "Computer, Teaching", "Technology, Education", "Wednesday, Saturday", "Kathmandu", "images/tasks/digital.svg", org_ids[4], "2026-10-15", "2026-11-15"),
            ("Community Digital Media Support", "Help create simple flyers and update community web pages.", "Programming, Graphic Design", "Technology, Community", "Thursday, Saturday", "Kathmandu", "images/tasks/digital.svg", org_ids[4], "2026-10-22", "2026-11-22"),

            ("Elder Care Center Companion Visit", "Spend meaningful time, assist, and chat warmly with senior citizens.", "Elder Care, Communication", "Health, Community", "Tuesday, Friday", "Lalitpur", "images/tasks/care_real.jpg", org_ids[5], "2026-10-17", "2026-11-17"),
            ("Community Health & First Aid Workshop", "Help organize a community health and wellness awareness camp.", "First Aid, Event Planning", "Health, Community", "Sunday", "Lalitpur", "images/tasks/care_real.jpg", org_ids[5], "2026-10-24", "2026-11-24"),

            ("Shelter Animal Companion & Feeding", "Assist in feeding, walking, and caring for rescue animals.", "Teamwork, Communication", "Animals, Outdoors", "Saturday, Sunday", "Kathmandu", "images/tasks/cleanup.svg", org_ids[6], "2026-10-19", "2026-11-19"),
            ("Pet Adoption Drive Coordinator", "Help organize an outdoor adoption awareness event for rescued pets.", "Event Planning, Social Media", "Animals, Community", "Saturday", "Kathmandu", "images/tasks/cleanup.svg", org_ids[6], "2026-10-25", "2026-11-25"),

            ("Heritage Site Walkway Cleaning", "Help clear trash and maintain public walkways around heritage sites.", "Cleaning, Gardening", "Culture, Outdoors", "Sunday", "Bhaktapur", "images/tasks/garden.svg", org_ids[7], "2026-10-21", "2026-11-21"),
            ("Eco Survey & Tree Labeling", "Catalog local tree species and assist with environmental data.", "Research, Communication", "Environment, Outdoors", "Friday, Saturday", "Bhaktapur", "images/tasks/garden.svg", org_ids[7], "2026-10-26", "2026-11-26"),

            # Bashanta has 9 saved skills. These four tasks use 5, 6, 7, and 8
            # of them, so Jaccard gives 55.56%, 66.67%, 77.78%, and 88.89%.
            ("Community Mentor Support", "Support a community mentoring session with communication and training activities.", "Communication, Teamwork, Programming, Teaching, First Aid", "Community, Education", "Saturday", "Kathmandu", "images/tasks/reading_real.jpg", org_ids[0], "2026-10-28", "2026-11-28"),
            ("Digital Workshop Assistant", "Help visitors during a practical digital learning workshop.", "Communication, Teamwork, Programming, Teaching, First Aid, Computer", "Technology, Education", "Saturday", "Kathmandu", "images/tasks/digital.svg", org_ids[1], "2026-10-29", "2026-11-29"),
            ("Volunteer Leadership Day", "Assist an experienced volunteer team during a leadership and skills day.", "Communication, Teamwork, Programming, Teaching, First Aid, Computer, Graphic Design, Photography", "Community, Technology", "Saturday", "Lalitpur", "images/tasks/food_real.jpg", org_ids[2], "2026-10-30", "2026-11-30"),
            ("Student Event Team", "Help coordinate learning activities and document a student event.", "Communication, Teamwork, Programming, Teaching, First Aid, Computer, Graphic Design", "Education, Youth", "Saturday", "Bhaktapur", "images/tasks/reading_real.jpg", org_ids[3], "2026-11-01", "2026-12-01"),
            ("Community Research Support", "Support a small community research and information activity.", "Communication, Teamwork, Programming, Teaching, First Aid, Gardening, Cooking, Driving, Research", "Community, Environment", "Saturday", "Kathmandu", "images/tasks/garden.svg", org_ids[4], "2026-11-02", "2026-12-02"),
            ("Senior Centre Welcome Team", "Welcome visitors and help the senior centre activity team.", "Communication, Teamwork, Elder Care", "Health, Community", "Saturday", "Lalitpur", "images/tasks/care_real.jpg", org_ids[5], "2026-11-03", "2026-12-03"),
            ("Animal Adoption Festival Support", "Help prepare a community animal adoption festival.", "Communication, Teamwork, Programming, Gardening, Cooking, Driving", "Animals, Community", "Saturday", "Kathmandu", "images/tasks/cleanup.svg", org_ids[6], "2026-11-04", "2026-12-04"),

            # Every demo volunteer has 9 skills. Each group below uses 5, 6, 7,
            # and 8 of that volunteer's skills for 55.56%, 66.67%, 77.78%, and 88.89%.
            ("Youth Learning Support Team", "Support a youth learning activity with children and volunteer mentors.", "Teaching, First Aid, Event Planning, Communication, Teamwork", "Education, Youth", "Tuesday", "Kathmandu", "images/tasks/reading_real.jpg", org_ids[0], "2026-11-05", "2026-12-05"),
            ("Childcare Workshop Support", "Help children and facilitators during a practical learning workshop.", "Teaching, First Aid, Event Planning, Communication, Teamwork, Childcare", "Education, Youth", "Thursday", "Kathmandu", "images/tasks/reading_real.jpg", org_ids[0], "2026-11-06", "2026-12-06"),
            ("Community Learning Research Team", "Help collect feedback and support a community learning research session.", "Teaching, First Aid, Event Planning, Communication, Teamwork, Childcare, Counselling", "Education, Community", "Sunday", "Kathmandu", "images/tasks/reading_real.jpg", org_ids[1], "2026-11-07", "2026-12-07"),
            ("Multilingual Youth Mentorship", "Support youth mentors with learning, translation, and research activities.", "Teaching, First Aid, Event Planning, Communication, Teamwork, Childcare, Counselling, Research", "Education, Youth", "Tuesday", "Kathmandu", "images/tasks/reading_real.jpg", org_ids[1], "2026-11-08", "2026-12-08"),

            ("Food Drive Support Crew", "Sort food supplies and support a community food distribution team.", "Cooking, Organizing, Fundraising, Communication, Teamwork", "Food Support, Community", "Friday", "Lalitpur", "images/tasks/food_real.jpg", org_ids[2], "2026-11-09", "2026-12-09"),
            ("Community Meal Delivery", "Prepare food packages and support delivery coordination.", "Cooking, Organizing, Fundraising, Communication, Teamwork, Driving", "Food Support, Community", "Saturday", "Lalitpur", "images/tasks/food_real.jpg", org_ids[2], "2026-11-10", "2026-12-10"),
            ("Donation Event Operations", "Help manage food donations, records, and volunteer operations.", "Cooking, Organizing, Fundraising, Communication, Teamwork, Driving, Accounting", "Food Support, Community", "Monday", "Bhaktapur", "images/tasks/food_real.jpg", org_ids[3], "2026-11-11", "2026-12-11"),
            ("Festival Food Coordination", "Coordinate the food team and community festival service points.", "Cooking, Organizing, Fundraising, Communication, Teamwork, Driving, Accounting, Event Planning", "Food Support, Community", "Friday", "Bhaktapur", "images/tasks/food_real.jpg", org_ids[3], "2026-11-12", "2026-12-12"),

            ("Creative Media Support Team", "Create visual content and help share a community campaign.", "Graphic Design, Social Media, Photography, Programming, Communication", "Arts, Technology", "Tuesday", "Kathmandu", "images/tasks/digital.svg", org_ids[4], "2026-11-13", "2026-12-13"),
            ("Design and Technology Workshop", "Support a practical community design and technology workshop.", "Graphic Design, Social Media, Photography, Programming, Communication, Teamwork", "Technology, Community", "Thursday", "Kathmandu", "images/tasks/digital.svg", org_ids[4], "2026-11-14", "2026-12-14"),
            ("Community Campaign Research", "Prepare media content and research feedback for a community campaign.", "Graphic Design, Social Media, Photography, Programming, Communication, Teamwork, Research", "Arts, Community", "Sunday", "Lalitpur", "images/tasks/care_real.jpg", org_ids[5], "2026-11-15", "2026-12-15"),
            ("Digital Storytelling Event", "Help run a digital storytelling and community media event.", "Graphic Design, Social Media, Photography, Programming, Communication, Teamwork, Research, Event Planning", "Arts, Technology", "Tuesday", "Lalitpur", "images/tasks/care_real.jpg", org_ids[5], "2026-11-16", "2026-12-16"),

            ("Green Community Action Team", "Help maintain a shared green space with the community team.", "Gardening, Cleaning, Teamwork, Communication, Organizing", "Environment, Community", "Wednesday", "Kathmandu", "images/tasks/garden.svg", org_ids[6], "2026-11-17", "2026-12-17"),
            ("Park Safety Support", "Assist the park team with cleaning, first-aid readiness, and visitor support.", "Gardening, Cleaning, Teamwork, Communication, Organizing, First Aid", "Environment, Community", "Friday", "Kathmandu", "images/tasks/garden.svg", org_ids[6], "2026-11-18", "2026-12-18"),
            ("Eco Survey and Maintenance", "Support garden maintenance and collect simple environmental observations.", "Gardening, Cleaning, Teamwork, Communication, Organizing, First Aid, Driving", "Environment, Outdoors", "Saturday", "Bhaktapur", "images/tasks/garden.svg", org_ids[7], "2026-11-19", "2026-12-19"),
            ("Environment Event Leadership", "Coordinate a community environment event and research activity.", "Gardening, Cleaning, Teamwork, Communication, Organizing, First Aid, Driving, Research", "Environment, Community", "Wednesday", "Bhaktapur", "images/tasks/garden.svg", org_ids[7], "2026-11-20", "2026-12-20"),

            ("Emergency Relief Kit Packing", "Sort, pack, and label essential household relief kits for community response.", "First Aid, Organizing, Teamwork, Communication", "Disaster Relief, Community", "Saturday", "Kathmandu", "images/tasks/relief_kit_real.jpg", org_ids[8], "2026-11-21", "2026-12-21"),
            ("Community First Aid Awareness", "Support a practical first-aid awareness session for families and youth.", "First Aid, Teaching, Communication, Teamwork", "Health, Community", "Saturday", "Kathmandu", "images/tasks/first_aid_real.jpg", org_ids[8], "2026-11-22", "2026-12-22"),
        ]

        for title, desc, req_skills, interests, avail, loc, img, org_id, start_d, end_d in demo_tasks:
            if not run("SELECT id FROM tasks WHERE title=? AND organization_id=?", (title, org_id)).fetchone():
                run("INSERT INTO tasks(title,description,required_skills,interests,availability,location,image_filename,organization_id,start_date,end_date) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (title, desc, req_skills, interests, avail, loc, img, org_id, start_d, end_d))

        # Every demo work gets its own local photo. Uploaded organization images are not changed.
        demo_task_images = {
            "Community Clean-up Drive": "images/tasks/cleanup_real.jpg",
            "Neighbourhood Garden Day": "images/tasks/planting_real.jpg",
            "City Park Tree Planting": "images/tasks/city_planting_real.jpg",
            "Bagmati Riverbank Cleanup": "images/tasks/river_cleanup_real.jpg",
            "Food Package Assembly & Serving": "images/tasks/food_real.jpg",
            "Fresh Food Kitchen Assistant": "images/tasks/kitchen_support_real.jpg",
            "Children's Reading Buddy Program": "images/tasks/reading_real.jpg",
            "Youth Creative Learning Workshop": "images/tasks/youth_workshop_real.jpg",
            "Senior Citizens Tech Literacy Class": "images/tasks/senior_digital_real.jpg",
            "Community Digital Media Support": "images/tasks/digital_media_real.jpg",
            "Elder Care Center Companion Visit": "images/tasks/care_real.jpg",
            "Community Health & First Aid Workshop": "images/tasks/health_workshop_real.jpg",
            "Shelter Animal Companion & Feeding": "images/tasks/animal_care_real.jpg",
            "Pet Adoption Drive Coordinator": "images/tasks/animal_adoption_real.jpg",
            "Heritage Site Walkway Cleaning": "images/tasks/heritage_cleaning_real.jpg",
            "Eco Survey & Tree Labeling": "images/tasks/eco_research_real.jpg",
            "Community Mentor Support": "images/tasks/mentor_support_real.jpg",
            "Digital Workshop Assistant": "images/tasks/digital_workshop_real.jpg",
            "Volunteer Leadership Day": "images/tasks/leadership_real.jpg",
            "Student Event Team": "images/tasks/student_event_real.jpg",
            "Community Research Support": "images/tasks/community_research_real.jpg",
            "Senior Centre Welcome Team": "images/tasks/senior_welcome_real.jpg",
            "Animal Adoption Festival Support": "images/tasks/animal_event_real.jpg",
            "Youth Learning Support Team": "images/tasks/youth_learning_real.jpg",
            "Childcare Workshop Support": "images/tasks/childcare_real.jpg",
            "Community Learning Research Team": "images/tasks/learning_research_real.jpg",
            "Multilingual Youth Mentorship": "images/tasks/multilingual_real.jpg",
            "Food Drive Support Crew": "images/tasks/food_drive_real.jpg",
            "Community Meal Delivery": "images/tasks/meal_delivery_real.jpg",
            "Donation Event Operations": "images/tasks/donation_operations_real.jpg",
            "Festival Food Coordination": "images/tasks/festival_food_real.jpg",
            "Creative Media Support Team": "images/tasks/creative_media_real.jpg",
            "Design and Technology Workshop": "images/tasks/design_workshop_real.jpg",
            "Community Campaign Research": "images/tasks/campaign_research_real.jpg",
            "Digital Storytelling Event": "images/tasks/digital_storytelling_real.jpg",
            "Green Community Action Team": "images/tasks/green_action_real.jpg",
            "Park Safety Support": "images/tasks/park_safety_real.jpg",
            "Eco Survey and Maintenance": "images/tasks/eco_maintenance_real.jpg",
            "Environment Event Leadership": "images/tasks/environment_event_real.jpg",
            "Emergency Relief Kit Packing": "images/tasks/relief_kit_real.jpg",
            "Community First Aid Awareness": "images/tasks/first_aid_real.jpg",
        }
        for title, image in demo_task_images.items():
            run("UPDATE tasks SET image_filename=? WHERE title=? AND image_filename NOT LIKE 'uploads/%'", (image, title))

        # Upgrade the four previously-created demonstration tasks one time.
        # The old skill text is checked so tasks edited by an organization are not overwritten.
        demo_task_skill_updates = [
            ("Communication, Teamwork, Programming, Teaching, First Aid", "Community Mentor Support", "Communication, Teamwork, Programming, Teaching, First Aid, Gardening, Cooking"),
            ("Communication, Teamwork, Programming, Teaching, First Aid, Computer, Graphic Design", "Student Event Team", "Communication, Teamwork, Programming, Teaching, First Aid, Computer, Graphic Design"),
        ]
        for new_skills, title, old_skills in demo_task_skill_updates:
            run("UPDATE tasks SET required_skills=? WHERE title=? AND required_skills=?", (new_skills, title, old_skills))

        if run("SELECT COUNT(*) AS total FROM applications WHERE status='Completed'").fetchone()["total"] == 0:
            vol_sweekriti = run("SELECT id FROM users WHERE email='sweekriti@gmail.com'").fetchone()
            vol_kusum = run("SELECT id FROM users WHERE email='kusum@gmail.com'").fetchone()
            task_reading = run("SELECT id FROM tasks WHERE title LIKE '%Reading Buddy%'").fetchone()
            task_cleanup = run("SELECT id FROM tasks WHERE title LIKE '%Clean-up Drive%'").fetchone()

            if vol_sweekriti and task_reading:
                run("INSERT INTO applications(volunteer_id, task_id, status, score, rating, review_text) VALUES(?,?,?,?,?,?)",
                    (vol_sweekriti["id"], task_reading["id"], "Completed", 0.85, 5, "Outstanding volunteer! Sweekriti was very punctual, mentored the youth patiently, and demonstrated exceptional leadership."))
            if vol_kusum and task_cleanup:
                run("INSERT INTO applications(volunteer_id, task_id, status, score, rating, review_text) VALUES(?,?,?,?,?,?)",
                    (vol_kusum["id"], task_cleanup["id"], "Completed", 0.78, 5, "Highly dedicated and energetic worker! Kusum coordinated team activities and completed all tasks efficiently."))

        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        commit()
    except (MySQLError, ValueError) as error:
        app.logger.warning("XAMPP MySQL connection notice during startup: %s", error)


# ═══════════════════════════════════════════
#                  ROUTES
# ═══════════════════════════════════════════

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
        run("SELECT 1 AS connected").fetchone()
        return jsonify(status="online", database="MySQL connected")
    except Exception as e:
        app.logger.warning("Health check MySQL connection error: %s", e)
        return jsonify(status="offline", database="MySQL unavailable", error=str(e)), 503



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


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        email = request.form["email"].lower()
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
                (request.form["name"], username, email, generate_password_hash(request.form["password"]), request.form["date_of_birth"]))
            commit()
            flash("Volunteer account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/register-organization", methods=("GET", "POST"))
def register_organization():
    if request.method == "POST":
        email = request.form["email"].lower()
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
            name = request.form["organization_name"]
            org_type = request.form.get("organization_type", "Non-Governmental Organization (NGO)").strip()
            logo = save_image(request.files.get("logo"))
            if logo is False:
                flash("Logo image must be a PNG, JPG, GIF, or WEBP file.", "danger")
                return render_template("register_organization.html")
            user_id = run("INSERT INTO users(name,username,email,password,role) VALUES(?,?,?,?,'organization')",
                         (name, username, email, generate_password_hash(request.form["password"]))).lastrowid
            run("INSERT INTO organization_profiles(user_id,organization_name,organization_type,contact_person,contact_email,phone,location,description,logo_filename) VALUES(?,?,?,?,?,?,?,?,?)",
                (user_id, name, org_type, request.form["contact_person"], email, request.form["phone"], request.form["location"], request.form["description"], logo))
            commit()
            flash("Organization account created successfully. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register_organization.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        identifier = request.form["identifier"].strip()
        user = run("SELECT * FROM users WHERE lower(email)=lower(?) OR lower(username)=lower(?)", (identifier, identifier)).fetchone()
        if user and check_password_hash(user["password"], request.form["password"]):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["role"] = user["role"]
            flash("Login successful. Welcome back!", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            elif user["role"] == "organization":
                return redirect(url_for("organization_dashboard"))
            else:
                # Volunteers see their newest opportunities first after login.
                return redirect(url_for("volunteer_dashboard"))
        flash("Incorrect email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/user/dashboard")
@require("volunteer")
def volunteer_dashboard():
    """Show a volunteer's six newest opportunities after login."""
    profile = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (session["user_id"],)).fetchone()
    recent_tasks = run(
        "SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'Organization') AS organization_name "
        "FROM tasks "
        "LEFT JOIN users ON users.id=tasks.organization_id "
        "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
        "ORDER BY tasks.id DESC LIMIT 6"
    ).fetchall()
    task_matches = [(task, match_details(profile, task) if profile else None) for task in recent_tasks]
    counts = {
        "applications": run("SELECT COUNT(*) AS total FROM applications WHERE volunteer_id=?", (session["user_id"],)).fetchone()["total"],
        "completed": run("SELECT COUNT(*) AS total FROM applications WHERE volunteer_id=? AND status='Completed'", (session["user_id"],)).fetchone()["total"],
        "qualified": sum(1 for _, match in task_matches if match and match["qualified"]),
    }
    return render_template("volunteer_dashboard.html", task_matches=task_matches, counts=counts, profile=profile)


@app.route("/user/profile", methods=("GET", "POST"))
@require("volunteer")
def profile():
    user = run("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    prof = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (session["user_id"],)).fetchone()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()

        if username and user and username.lower() != (user["username"] or "").lower():
            if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
                flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
                return redirect(url_for("profile"))
            taken = run("SELECT id FROM users WHERE lower(username)=lower(?) AND id!=?", (username, session["user_id"])).fetchone()
            if taken:
                flash("That username is already taken by another account.", "warning")
                return redirect(url_for("profile"))

        image = save_image(request.files.get("photo"))
        if image is False:
            flash("Profile image must be PNG, JPG, JPEG, GIF, or WEBP.", "warning")
            return redirect(url_for("profile"))
        if image is None:
            image = prof["photo_filename"] if prof else None
        edu_level = request.form.get("education_level", "Intermediate (10+2) / High School").strip()
        vals = (
            ", ".join(request.form.getlist("skills")),
            ", ".join(request.form.getlist("interests")),
            ", ".join(request.form.getlist("availability")),
            request.form["location"],
            image,
            edu_level,
            session["user_id"],
        )
        if prof:
            run("UPDATE volunteer_profiles SET skills=?,interests=?,availability=?,location=?,photo_filename=?,education_level=? WHERE user_id=?", vals)
        else:
            run("INSERT INTO volunteer_profiles(skills,interests,availability,location,photo_filename,education_level,user_id) VALUES(?,?,?,?,?,?,?)", vals)
        run("UPDATE users SET name=?,username=?,date_of_birth=? WHERE id=?", (name or user["name"], username or user["username"], request.form["date_of_birth"], session["user_id"]))
        commit()
        session["user_name"] = name or user["name"]
        refresh_applications(session["user_id"])
        flash("Profile updated and previous task results refreshed.", "success")
        return redirect(url_for("profile"))
    skills = run("SELECT name FROM skill_catalog ORDER BY name").fetchall()
    interests = run("SELECT name FROM interest_catalog ORDER BY name").fetchall()
    return render_template("profile.html",
        profile=prof, user=user, skills=skills, interests=interests,
        selected_skills=terms(prof["skills"]) if prof else set(),
        selected_interests=terms(prof["interests"]) if prof else set(),
        selected_days=terms(prof["availability"]) if prof else set())


@app.route("/profile", methods=("GET", "POST"))
def profile_legacy_redirect():
    return redirect(url_for("profile"))


# ── Application Route with 40% Threshold Check ──

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
        # Threshold enforcement: Must have >= 40% Jaccard Similarity match
        if not result["qualified"]:
            flash(f"Application rejected: Your Jaccard similarity match is {result['score'] * 100:.2f}%. Minimum 40% match is required to apply.", "danger")
            return redirect(url_for("tasks"))

        status = "Pending"  # Pending approval by the organization
        run("INSERT INTO applications(volunteer_id,task_id,status,score) VALUES(?,?,?,?)",
            (session["user_id"], task_id, status, result["score"]))

        # 1. Notification for Volunteer
        vol_msg = f"Application submitted for '{task['title']}' (Jaccard Match: {result['score'] * 100:.2f}%). Status: Pending Approval by organization."
        run("INSERT INTO notifications(user_id, message, link_url) VALUES(?,?,?)",
            (session["user_id"], vol_msg, url_for("my_applications")))

        # 2. Notification for Organization owning the task
        if task.get("organization_id"):
            vol_name = session.get("user_name", "A volunteer")
            org_msg = f"New volunteer application received from {vol_name} for work task '{task['title']}'."
            run("INSERT INTO notifications(user_id, message, link_url) VALUES(?,?,?)",
                (task["organization_id"], org_msg, url_for("manage_applications")))

        commit()
        flash("Application submitted successfully! It is now pending approval by the organization.", "success")
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
        "organization_profiles.contact_person, "
        "organization_profiles.phone AS contact_phone, "
        "organization_profiles.location AS organization_location, "
        "organization_profiles.logo_filename AS organization_logo "
        "FROM applications "
        "JOIN tasks ON tasks.id=applications.task_id "
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


@app.route("/catalog/skills", methods=("POST",))
@require("organization", "admin")
def add_catalog_skill():
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name or len(name) > 120:
        return jsonify(success=False, message="Enter a skill name with up to 120 characters."), 400
    run("INSERT INTO skill_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (name,))
    commit()
    return jsonify(success=True, name=name, message=f"{name} is available in the skill list.")


@app.route("/catalog/interests", methods=("POST",))
@require("organization", "admin")
def add_catalog_interest():
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name or len(name) > 120:
        return jsonify(success=False, message="Enter an interest name with up to 120 characters."), 400
    run("INSERT INTO interest_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (name,))
    commit()
    return jsonify(success=True, name=name, message=f"{name} is available in the interest list.")


@app.route("/organization/dashboard")
@require("organization")
def organization_dashboard():
    # 1. My Organization's Posted Tasks + application count
    my_tasks = run(
        "SELECT tasks.*, COUNT(applications.id) AS application_count FROM tasks "
        "LEFT JOIN applications ON applications.task_id=tasks.id "
        "WHERE tasks.organization_id=? GROUP BY tasks.id ORDER BY tasks.id DESC",
        (session["user_id"],)
    ).fetchall()

    # 2. Applied volunteers for my organization's tasks
    my_applications_rows = run(
        "SELECT applications.*, users.name AS volunteer_name, users.email AS volunteer_email, users.date_of_birth, "
        "TIMESTAMPDIFF(YEAR, users.date_of_birth, CURDATE()) AS age, "
        "tasks.title AS task_title, tasks.id AS task_id, "
        "volunteer_profiles.skills, volunteer_profiles.interests, volunteer_profiles.availability, "
        "volunteer_profiles.location, volunteer_profiles.photo_filename, volunteer_profiles.education_level "
        "FROM applications JOIN users ON users.id=applications.volunteer_id "
        "JOIN tasks ON tasks.id=applications.task_id "
        "LEFT JOIN volunteer_profiles ON volunteer_profiles.user_id=applications.volunteer_id "
        "WHERE tasks.organization_id=? ORDER BY applications.id DESC",
        (session["user_id"],)
    ).fetchall()

    my_applications = []
    for app_row in my_applications_rows:
        reviews = get_volunteer_reviews(app_row["volunteer_id"])
        my_applications.append({
            "app": app_row,
            "reviews": reviews
        })

    # 3. Other Organizations' Tasks (Separate Panel)
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

    counts = {
        "my_tasks": len(my_tasks),
        "applications": len(my_applications),
        "other_tasks": len(other_tasks)
    }

    return render_template(
        "organization_dashboard.html",
        counts=counts,
        my_tasks=my_tasks,
        my_applications=my_applications,
        other_tasks=other_tasks
    )


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

        if username and org and username.lower() != (org["username"] or "").lower():
            if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
                flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
                return redirect(url_for("organization_profile"))
            taken = run("SELECT id FROM users WHERE lower(username)=lower(?) AND id!=?", (username, session["user_id"])).fetchone()
            if taken:
                flash("That username is already taken by another account.", "warning")
                return redirect(url_for("organization_profile"))

        logo = save_image(request.files.get("logo"))
        if logo is None:
            logo = org["logo_filename"] if org else None
        if logo is False:
            flash("Use a PNG, JPG, GIF, or WEBP logo.", "danger")
            return redirect(url_for("organization_profile"))

        org_type = request.form.get("organization_type", "Non-Governmental Organization (NGO)").strip()
        contact_email = request.form.get("contact_email", "").strip() or (org["email"] if org else "")
        run("UPDATE users SET name=?, username=? WHERE id=?", (org_name, username or (org["username"] if org else ""), session["user_id"]))
        run("UPDATE organization_profiles SET organization_name=?,organization_type=?,contact_person=?,contact_email=?,phone=?,location=?,description=?,logo_filename=? WHERE user_id=?",
            (org_name, org_type, request.form["contact_person"], contact_email, request.form["phone"],
             request.form["location"], request.form["description"], logo, session["user_id"]))
        commit()
        session["user_name"] = org_name
        flash("Organization profile updated successfully.", "success")
        return redirect(url_for("organization_profile"))
    return render_template("organization_profile.html", organization=org)


@app.route("/organization/tasks", methods=("GET", "POST"))
@app.route("/admin/tasks", methods=("GET", "POST"))
@require("organization", "admin")
def manage_tasks():
    if request.method == "POST":
        if session.get("role") == "admin":
            flash("Tasks can only be created by registered organizations. Administrators can view, edit, and delete existing tasks.", "warning")
            return redirect(url_for("manage_tasks"))

        if request.form["end_date"] < request.form["start_date"]:
            flash("The work end date must be on or after the start date.", "danger")
            return redirect(url_for("manage_tasks"))
        skills = [x.strip() for x in request.form.getlist("required_skills") + [request.form.get("new_skill", "")] if x.strip()]
        interests = [x.strip() for x in request.form.getlist("interests") + [request.form.get("new_interest", "")] if x.strip()]
        for item in skills:
            run("INSERT INTO skill_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (item,))
        for item in interests:
            run("INSERT INTO interest_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (item,))
        image = save_image(request.files.get("task_image"))
        if image is None:
            image = "images/tasks/cleanup.svg"
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
        query = ("SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'System Admin') AS organization_name "
                 "FROM tasks LEFT JOIN users ON users.id=tasks.organization_id "
                 "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id ORDER BY id DESC")
        rows = run(query).fetchall()
    else:
        query = ("SELECT tasks.*, COALESCE(organization_profiles.organization_name, users.name, 'My Organization') AS organization_name "
                 "FROM tasks LEFT JOIN users ON users.id=tasks.organization_id "
                 "LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id "
                 "WHERE tasks.organization_id=? ORDER BY id DESC")
        rows = run(query, (session["user_id"],)).fetchall()
    skills = run("SELECT name FROM skill_catalog ORDER BY name").fetchall()
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
            flash("The work end date must be on or after the start date.", "danger")
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
             request.form["location"], request.form["start_date"], request.form["end_date"], image, min_edu, task_id))
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

    applications_data = []
    for app_row in apps:
        reviews = get_volunteer_reviews(app_row["volunteer_id"])
        applications_data.append((app_row, None, reviews))

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
            review_text = request.form.get("review_text", "").strip()
            rating_val = request.form.get("rating", 5, type=int)
            run("UPDATE applications SET status=?, review_text=?, rating=? WHERE id=?", (decision, review_text, rating_val, application_id))
            vol_msg = f"Your volunteer work for '{record['title']}' was marked COMPLETED by the organization. Thank you for your service!"
        elif decision == "Accepted":
            run("UPDATE applications SET status=? WHERE id=?", (decision, application_id))
            vol_msg = f"Congratulations! Your application for '{record['title']}' was APPROVED by the organization."
        elif decision == "Rejected":
            run("UPDATE applications SET status=? WHERE id=?", (decision, application_id))
            vol_msg = f"Your application for '{record['title']}' was REJECTED by the organization."
        else:
            vol_msg = f"Your application for '{record['title']}' status was updated to {decision.lower()}."

        run("INSERT INTO notifications(user_id, message, link_url) VALUES(?,?,?)",
            (record["volunteer_id"], vol_msg, url_for("my_applications")))
        commit()
        flash(f"Application status updated to {decision}.", "success")
    return redirect(request.referrer or url_for("manage_applications"))


@app.route("/user/notification/<int:notification_id>/click")
def click_notification(notification_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    note = run("SELECT * FROM notifications WHERE id=? AND user_id=?", (notification_id, session["user_id"])).fetchone()
    if note:
        run("UPDATE notifications SET is_read=1 WHERE id=?", (notification_id,))
        commit()
        if note.get("link_url"):
            return redirect(note["link_url"])
    return redirect(url_for("notifications"))


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
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["role"] = user["role"]
            flash("Administrator login successful.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Use a valid administrator username/email and password.", "danger")
    return render_template("admin_login.html")


@app.route("/admin/dashboard")
@require("admin")
def admin_dashboard():
    counts = {
        "volunteers": run("SELECT COUNT(*) AS total FROM users WHERE role='volunteer'").fetchone()["total"],
        "organizations": run("SELECT COUNT(*) AS total FROM users WHERE role='organization'").fetchone()["total"],
        "tasks": run("SELECT COUNT(*) AS total FROM tasks").fetchone()["total"],
        "applications": run("SELECT COUNT(*) AS total FROM applications").fetchone()["total"],
        "education_types": run("SELECT COUNT(*) AS total FROM education_catalog").fetchone()["total"] if run("SELECT COUNT(*) AS total FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='education_catalog'").fetchone()["total"] > 0 else 0,
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
    return render_template("admin_dashboard.html", counts=counts, top_tasks=top_tasks, recent_notifications=recent_notifications)


@app.route("/admin/catalogs", methods=("GET", "POST"))
@require("admin")
def manage_catalogs():
    if request.method == "POST":
        catalog_type = request.form.get("catalog_type", "").strip()
        if catalog_type == "skill":
            name = request.form.get("name", "").strip()
            if not name or len(name) > 120:
                flash("Enter a skill name with up to 120 characters.", "warning")
            else:
                run("INSERT INTO skill_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (name,))
                commit()
                flash(f"New skill '{name}' added to database catalog.", "success")
        elif catalog_type == "interest":
            name = request.form.get("name", "").strip()
            if not name or len(name) > 120:
                flash("Enter a hobby / interest name with up to 120 characters.", "warning")
            else:
                run("INSERT INTO interest_catalog(name) VALUES(?) ON DUPLICATE KEY UPDATE name=name", (name,))
                commit()
                flash(f"New hobby / interest '{name}' added to database catalog.", "success")
        else:
            name = request.form.get("name", "").strip()
            category = request.form.get("category", "both").strip()
            rank_level = request.form.get("rank_level", 1, type=int)
            if not name or len(name) > 120:
                flash("Enter an education type name with up to 120 characters.", "warning")
            elif run("SELECT id FROM education_catalog WHERE lower(name)=lower(?)", (name,)).fetchone():
                flash("That education type already exists in the catalog.", "warning")
            else:
                run("INSERT INTO education_catalog(name, category, rank_level) VALUES(?,?,?)", (name, category, rank_level))
                commit()
                flash(f"New education type '{name}' added to catalog.", "success")
        return redirect(url_for("manage_catalogs"))

    skills = run("SELECT * FROM skill_catalog ORDER BY name ASC").fetchall()
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
        flash(f"Skill '{item['name']}' removed from catalog.", "info")
    return redirect(url_for("manage_catalogs"))


@app.route("/admin/catalog/interest/<int:interest_id>/delete", methods=("POST",))
@require("admin")
def delete_catalog_interest(interest_id):
    item = run("SELECT * FROM interest_catalog WHERE id=?", (interest_id,)).fetchone()
    if item:
        run("DELETE FROM interest_catalog WHERE id=?", (interest_id,))
        commit()
        flash(f"Hobby / Interest '{item['name']}' removed from catalog.", "info")
    return redirect(url_for("manage_catalogs"))


@app.route("/admin/profile", methods=("GET", "POST"))
@require("admin")
def admin_profile():
    admin = run("SELECT * FROM users WHERE id=? AND role='admin'", (session["user_id"],)).fetchone()
    if not admin:
        session.clear()
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not username or not email:
            flash("Name, username, and email are required.", "warning")
        elif not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
        elif run("SELECT id FROM users WHERE lower(username)=lower(?) AND id!=?", (username, admin["id"])).fetchone():
            flash("That username is already taken.", "warning")
        elif run("SELECT id FROM users WHERE lower(email)=lower(?) AND id!=?", (email, admin["id"])).fetchone():
            flash("That email is already registered.", "warning")
        elif password != confirm_password:
            flash("Passwords do not match.", "warning")
        elif password and len(password) < 6:
            flash("Password must be at least 6 characters long.", "warning")
        else:
            photo = save_image(request.files.get("photo"))
            if photo is False:
                flash("Profile image must be PNG, JPG, JPEG, GIF, or WEBP.", "warning")
                return render_template("admin_profile.html", admin=admin)
            if photo is None:
                photo = admin["photo_filename"]

            run("UPDATE users SET name=?, username=?, email=?, photo_filename=? WHERE id=?",
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
        "volunteer_profiles.skills, volunteer_profiles.interests, "
        "volunteer_profiles.availability, volunteer_profiles.location, volunteer_profiles.photo_filename AS profile_photo, "
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
        "volunteer_profiles.availability, volunteer_profiles.location, volunteer_profiles.photo_filename AS profile_photo, "
        "volunteer_profiles.education_level "
        "FROM users LEFT JOIN volunteer_profiles ON users.id=volunteer_profiles.user_id "
        "WHERE users.id=? AND users.role='volunteer'",
        (volunteer_id,)
    ).fetchone()
    if not volunteer:
        return redirect(url_for("manage_volunteers"))
    if request.method == "POST":
        pwd = request.form.get("password", "").strip()
        confirm_pwd = request.form.get("confirm_password", "").strip()

        if pwd or confirm_pwd:
            if pwd != confirm_pwd:
                flash("Passwords do not match.", "warning")
                return render_template("edit_volunteer.html", volunteer=volunteer)
            elif len(pwd) < 6:
                flash("Password must be at least 6 characters long.", "warning")
                return render_template("edit_volunteer.html", volunteer=volunteer)
            else:
                run("UPDATE users SET password=? WHERE id=?", (generate_password_hash(pwd), volunteer_id))

        username = request.form.get("username", "").strip()
        if username and not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
            return render_template("edit_volunteer.html", volunteer=volunteer)

        # Admin may replace the volunteer image, or keep the saved image unchanged.
        photo = save_image(request.files.get("photo"))
        if photo is False:
            flash("Profile image must be PNG, JPG, JPEG, GIF, or WEBP.", "warning")
            return render_template("edit_volunteer.html", volunteer=volunteer)
        if photo is None:
            photo = volunteer["profile_photo"]

        run("UPDATE users SET name=?, username=?, email=?, date_of_birth=? WHERE id=?",
            (request.form["name"], username or volunteer["username"], request.form["email"], request.form.get("date_of_birth"), volunteer_id))

        edu_level = request.form.get("education_level", "Intermediate (10+2) / High School").strip()
        existing = run("SELECT id FROM volunteer_profiles WHERE user_id=?", (volunteer_id,)).fetchone()
        vals = (request.form["skills"], request.form["interests"],
                ", ".join(request.form.getlist("availability")), request.form["location"], photo, edu_level, volunteer_id)
        if existing:
            run("UPDATE volunteer_profiles SET skills=?,interests=?,availability=?,location=?,photo_filename=?,education_level=? WHERE user_id=?", vals)
        else:
            run("INSERT INTO volunteer_profiles(skills,interests,availability,location,photo_filename,education_level,user_id) VALUES(?,?,?,?,?,?,?)", vals)
        commit()
        refresh_applications(volunteer_id)
        flash("Volunteer updated successfully.", "success")
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
        pwd = request.form.get("password", "").strip()
        confirm_pwd = request.form.get("confirm_password", "").strip()

        if pwd or confirm_pwd:
            if pwd != confirm_pwd:
                flash("Passwords do not match.", "warning")
                return render_template("edit_organization.html", organization=org)
            elif len(pwd) < 6:
                flash("Password must be at least 6 characters long.", "warning")
                return render_template("edit_organization.html", organization=org)
            else:
                run("UPDATE users SET password=? WHERE id=?", (generate_password_hash(pwd), organization_id))

        username = request.form.get("username", "").strip()
        if username and not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("Username must use 3–30 letters, numbers, or underscores.", "warning")
            return render_template("edit_organization.html", organization=org)

        logo = save_image(request.files.get("logo"))
        if logo is False:
            flash("Organization logo must be PNG, JPG, JPEG, GIF, or WEBP.", "warning")
            return render_template("edit_organization.html", organization=org)
        if logo is None:
            logo = org["logo_filename"] if org else None

        org_type = request.form.get("organization_type", "Non-Governmental Organization (NGO)").strip()
        contact_email = request.form.get("contact_email", "").strip() or request.form["email"]
        run("UPDATE users SET name=?, username=?, email=? WHERE id=?",
            (request.form["organization_name"], username or org["username"], request.form["email"], organization_id))
        run("UPDATE organization_profiles SET organization_name=?,organization_type=?,contact_person=?,contact_email=?,phone=?,location=?,description=?,logo_filename=? WHERE user_id=?",
            (request.form["organization_name"], org_type, request.form["contact_person"], contact_email, request.form["phone"],
             request.form["location"], request.form["description"], logo, organization_id))
        commit()
        flash("Organization updated successfully.", "success")
        return redirect(url_for("manage_organizations"))
    return render_template("edit_organization.html", organization=org)


# ── Initialization and App Start ──

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True)
