import os, sqlite3
from functools import wraps
from uuid import uuid4
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from services.matching import jaccard_similarity, terms

app = Flask(__name__)
app.config.update(SECRET_KEY="change-this-before-deploying", DATABASE=os.path.join(app.root_path,"community_volunteer.db"), UPLOAD_FOLDER=os.path.join(app.root_path,"static","uploads"))

def db():
    if "db" not in g:
        g.db=sqlite3.connect(app.config["DATABASE"]); g.db.row_factory=sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(error=None):
    if g.get("db"): g.db.close()
def match_details(profile, task):
    """Compare task-relevant volunteer skills so extra unrelated skills do not reduce the result."""
    volunteer_skills, required_skills = terms(profile["skills"]), terms(task["required_skills"])
    relevant_volunteer_skills = volunteer_skills & required_skills
    score, _, _, common_skills, _ = jaccard_similarity(", ".join(relevant_volunteer_skills), task["required_skills"])
    _, _, _, common_days, _ = jaccard_similarity(profile["availability"], task["availability"])
    all_skills_match = bool(required_skills) and required_skills.issubset(volunteer_skills)
    return {"score":score,"common_skills":sorted(common_skills),"common_days":sorted(common_days),"all_skills_match":all_skills_match,"qualified":all_skills_match and bool(common_days)}
def refresh_applications(volunteer_id):
    con=db(); profile=con.execute("SELECT * FROM volunteer_profiles WHERE user_id=?",(volunteer_id,)).fetchone()
    if not profile:return
    records=con.execute("SELECT applications.id AS application_id,tasks.* FROM applications JOIN tasks ON tasks.id=applications.task_id WHERE applications.volunteer_id=?",(volunteer_id,)).fetchall()
    for record in records:
        result=match_details(profile,record)
        if con.execute("SELECT status FROM applications WHERE id=?",(record["application_id"],)).fetchone()["status"] not in ("Accepted","Rejected","Completed"):
            con.execute("UPDATE applications SET score=?,status=? WHERE id=?",(result["score"],"Qualified" if result["qualified"] else "Not qualified",record["application_id"]))
    con.commit()
def require(*roles):
    def deco(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            if "user_id" not in session: return redirect(url_for("login"))
            if roles and session.get("role") not in roles: flash("You do not have permission for this page.","danger"); return redirect(url_for("home"))
            return view(*args,**kwargs)
        return wrapped
    return deco
def save_image(upload):
    if not upload or not upload.filename: return None
    ext=upload.filename.rsplit(".",1)[-1].lower() if "." in upload.filename else ""
    if ext not in {"png","jpg","jpeg","gif","webp"}: return False
    name=f"{uuid4().hex}_{secure_filename(upload.filename)}"; upload.save(os.path.join(app.config["UPLOAD_FOLDER"],name)); return f"uploads/{name}"
def init_db():
    con=db()
    with app.open_resource("schema.sql") as f: con.executescript(f.read().decode())
    con.execute("CREATE TABLE IF NOT EXISTS organization_profiles (id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE,organization_name TEXT,contact_person TEXT,phone TEXT,location TEXT,description TEXT,logo_filename TEXT)")
    for table,col,typ in [("users","date_of_birth","TEXT"),("volunteer_profiles","photo_filename","TEXT"),("tasks","image_filename","TEXT"),("tasks","organization_id","INTEGER"),("tasks","start_date","TEXT"),("tasks","end_date","TEXT"),("organization_profiles","logo_filename","TEXT")]:
        if col not in {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}: con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    con.executescript("CREATE TABLE IF NOT EXISTS organization_profiles (id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE,organization_name TEXT,contact_person TEXT,phone TEXT,location TEXT,description TEXT,logo_filename TEXT); CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY,user_id INTEGER,message TEXT,is_read INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS skill_catalog (id INTEGER PRIMARY KEY,name TEXT UNIQUE); CREATE TABLE IF NOT EXISTS interest_catalog (id INTEGER PRIMARY KEY,name TEXT UNIQUE);")
    for x in "Communication,Teaching,First Aid,Computer,Programming,Graphic Design,Photography,Cooking,Driving,Organizing,Teamwork,Gardening,Fundraising,Social Media,Translation,Accounting,Counselling,Childcare,Elder Care,Event Planning,Cleaning,Research".split(","): con.execute("INSERT OR IGNORE INTO skill_catalog(name) VALUES(?)",(x,))
    for x in "Education,Technology,Environment,Community,Food Support,Health,Sports,Animals,Arts,Music,Reading,Youth,Women Empowerment,Disaster Relief,Culture,Outdoors".split(","): con.execute("INSERT OR IGNORE INTO interest_catalog(name) VALUES(?)",(x,))
    # Convert older sample labels into the same individual-day format used by the checkboxes.
    con.execute("UPDATE tasks SET availability='Saturday, Sunday' WHERE lower(availability)='weekends'")
    con.execute("UPDATE tasks SET availability='Saturday' WHERE lower(availability)='saturday morning'")
    con.execute("UPDATE tasks SET availability='Monday, Tuesday, Wednesday, Thursday, Friday' WHERE lower(availability)='weekday afternoon'")
    con.execute("UPDATE tasks SET start_date='2026-10-10', end_date='2026-10-31' WHERE start_date IS NULL OR end_date IS NULL")
    # These demonstration passwords are stored with generate_password_hash, never as plain text.
    if not con.execute("SELECT id FROM users WHERE email=?",("bashanta@gmail.com",)).fetchone():
        con.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",("Bashanta","bashanta@gmail.com",generate_password_hash("Bashanta123@"),"admin"))
    if not con.execute("SELECT id FROM users WHERE email=?",("organization@volunteerhub.local",)).fetchone():
        organization_id=con.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",("VolunteerHub Organization","organization@volunteerhub.local",generate_password_hash("Organization123@"),"organization")).lastrowid
        con.execute("INSERT INTO organization_profiles(user_id,organization_name,contact_person,phone,location,description) VALUES(?,?,?,?,?,?)",(organization_id,"VolunteerHub Organization","Organization Manager","9800000000","Kathmandu","Demo organization account for posting work."))
    os.makedirs(app.config["UPLOAD_FOLDER"],exist_ok=True); con.commit()
@app.context_processor
def nav():
    photo=None
    if session.get("role")=="volunteer":
        row=db().execute("SELECT photo_filename FROM volunteer_profiles WHERE user_id=?",(session["user_id"],)).fetchone(); photo=row["photo_filename"].replace("uploads/","") if row and row["photo_filename"] else None
    return {"nav_photo":photo,"unread_notifications":0}

def tasks_with_matches(rows):
    profile=None
    if session.get("role")=="volunteer": profile=db().execute("SELECT * FROM volunteer_profiles WHERE user_id=?",(session["user_id"],)).fetchone()
    return [(task,match_details(profile,task) if profile else None) for task in rows]
@app.route("/")
def home(): return render_template("index.html",tasks=db().execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 10").fetchall())
@app.route("/health")
def health(): return jsonify(status="online")
@app.route("/register",methods=("GET","POST"))
def register():
    if request.method=="POST":
        con=db(); email=request.form["email"].lower()
        if con.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone(): flash("That email is already registered.","warning")
        else: con.execute("INSERT INTO users(name,email,password,role,date_of_birth) VALUES(?,?,?,'volunteer',?)",(request.form["name"],email,generate_password_hash(request.form["password"]),request.form["date_of_birth"])); con.commit(); flash("Volunteer account created. Please log in.","success"); return redirect(url_for("login"))
    return render_template("register.html")
@app.route("/register-organization",methods=("GET","POST"))
def register_organization():
    if request.method=="POST":
        con=db(); email=request.form["email"].lower()
        if con.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone(): flash("That email is already registered.","warning")
        else:
            name=request.form["organization_name"]; user_id=con.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,'organization')",(name,email,generate_password_hash(request.form["password"]))).lastrowid
            con.execute("INSERT INTO organization_profiles(user_id,organization_name,contact_person,phone,location,description) VALUES(?,?,?,?,?,?)",(user_id,name,request.form["contact_person"],request.form["phone"],request.form["location"],request.form["description"])); con.commit(); flash("Organization account created. Please log in.","success"); return redirect(url_for("login"))
    return render_template("register_organization.html")
@app.route("/login",methods=("GET","POST"))
def login():
    if request.method=="POST":
        identifier=request.form["identifier"].strip()
        user=db().execute("SELECT * FROM users WHERE lower(email)=lower(?) OR lower(name)=lower(?)",(identifier,identifier)).fetchone()
        if user and check_password_hash(user["password"],request.form["password"]):
            session.clear(); session.update(user_id=user["id"],user_name=user["name"],role=user["role"]); flash("Login successful. Welcome back!","success"); return redirect(url_for("admin_dashboard" if user["role"]=="admin" else "organization_dashboard" if user["role"]=="organization" else "profile"))
        flash("Incorrect email or password.","danger")
    return render_template("login.html")
@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("home"))
@app.route("/profile",methods=("GET","POST"))
@require("volunteer")
def profile():
    con=db(); user=con.execute("SELECT * FROM users WHERE id=?",(session["user_id"],)).fetchone(); prof=con.execute("SELECT * FROM volunteer_profiles WHERE user_id=?",(session["user_id"],)).fetchone()
    if request.method=="POST":
        image=save_image(request.files.get("photo")); image=(prof["photo_filename"] if prof else None) if image is None else image
        vals=(", ".join(request.form.getlist("skills")),", ".join(request.form.getlist("interests")),", ".join(request.form.getlist("availability")),request.form["location"],image,session["user_id"])
        if prof: con.execute("UPDATE volunteer_profiles SET skills=?,interests=?,availability=?,location=?,photo_filename=? WHERE user_id=?",vals)
        else: con.execute("INSERT INTO volunteer_profiles(skills,interests,availability,location,photo_filename,user_id) VALUES(?,?,?,?,?,?)",vals)
        con.execute("UPDATE users SET name=?,date_of_birth=? WHERE id=?",(request.form["name"],request.form["date_of_birth"],session["user_id"])); con.commit(); refresh_applications(session["user_id"]); flash("Profile updated and previous task results refreshed.","success"); return redirect(url_for("profile"))
    return render_template("profile.html",profile=prof,user=user,skills=con.execute("SELECT name FROM skill_catalog ORDER BY name").fetchall(),interests=con.execute("SELECT name FROM interest_catalog ORDER BY name").fetchall(),selected_skills=terms(prof["skills"]) if prof else set(),selected_interests=terms(prof["interests"]) if prof else set(),selected_days=terms(prof["availability"]) if prof else set())
@app.route("/tasks")
def tasks(): return render_template("tasks.html",task_matches=tasks_with_matches(db().execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()))
@app.route("/apply/<int:task_id>",methods=("POST",))
@require("volunteer")
def apply(task_id):
    con=db(); task=con.execute("SELECT * FROM tasks WHERE id=?",(task_id,)).fetchone(); prof=con.execute("SELECT * FROM volunteer_profiles WHERE user_id=?",(session["user_id"],)).fetchone()
    if not prof: return redirect(url_for("profile"))
    if con.execute("SELECT id FROM applications WHERE volunteer_id=? AND task_id=?",(session["user_id"],task_id)).fetchone(): flash("You already applied for this task.","warning")
    elif task:
        result=match_details(prof,task); status="Qualified" if result["qualified"] else "Not qualified"
        con.execute("INSERT INTO applications(volunteer_id,task_id,status,score) VALUES(?,?,?,?)",(session["user_id"],task_id,status,result["score"])); con.execute("INSERT INTO notifications(user_id,message) VALUES(?,?)",(session["user_id"],f"You are {status.lower()} for '{task['title']}'. Matched skills: {', '.join(result['common_skills']) or 'none'}; matching days: {', '.join(result['common_days']) or 'none'}.")); con.commit()
    return redirect(url_for("my_applications"))
@app.route("/my-applications")
@require("volunteer")
def my_applications(): return render_template("my_applications.html",applications=db().execute("SELECT applications.*,tasks.title FROM applications JOIN tasks ON tasks.id=applications.task_id WHERE volunteer_id=?",(session["user_id"],)).fetchall())
@app.route("/notifications")
@require("volunteer")
def notifications(): return render_template("notifications.html",notifications=db().execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC",(session["user_id"],)).fetchall())
@app.route("/compare",methods=("GET","POST"))
def compare():
    result=None
    if request.method=="POST":
        s,a,b,c,u=jaccard_similarity(request.form["volunteer_terms"],request.form["task_terms"]); result={"score":s,"volunteer":sorted(a),"task":sorted(b),"common":sorted(c),"all":sorted(u)}
    return render_template("compare.html",result=result)

@app.route("/organization")
@require("organization")
def organization_dashboard():
    con=db(); counts={"tasks":con.execute("SELECT COUNT(*) FROM tasks WHERE organization_id=?",(session["user_id"],)).fetchone()[0],"applications":con.execute("SELECT COUNT(*) FROM applications JOIN tasks ON tasks.id=applications.task_id WHERE tasks.organization_id=?",(session["user_id"],)).fetchone()[0]}
    return render_template("organization_dashboard.html",counts=counts)
@app.route("/organization/profile",methods=("GET","POST"))
@require("organization")
def organization_profile():
    con=db(); org=con.execute("SELECT * FROM organization_profiles WHERE user_id=?",(session["user_id"],)).fetchone()
    if request.method=="POST":
        logo=save_image(request.files.get("logo")); logo=org["logo_filename"] if logo is None else logo
        if logo is False: flash("Use a PNG, JPG, GIF, or WEBP logo.","danger"); return redirect(url_for("organization_profile"))
        con.execute("UPDATE users SET name=? WHERE id=?",(request.form["organization_name"],session["user_id"])); con.execute("UPDATE organization_profiles SET organization_name=?,contact_person=?,phone=?,location=?,description=?,logo_filename=? WHERE user_id=?",(request.form["organization_name"],request.form["contact_person"],request.form["phone"],request.form["location"],request.form["description"],logo,session["user_id"])); con.commit(); flash("Organization profile updated.","success"); return redirect(url_for("organization_profile"))
    return render_template("organization_profile.html",organization=org)
def owns(task): return session.get("role")=="admin" or (task and task["organization_id"]==session.get("user_id"))
@app.route("/organization/tasks",methods=("GET","POST"))
@app.route("/admin/tasks",methods=("GET","POST"))
@require("organization","admin")
def manage_tasks():
    con=db()
    if request.method=="POST":
        if request.form["end_date"] < request.form["start_date"]:
            flash("The work end date must be on or after the start date.","danger"); return redirect(url_for("manage_tasks"))
        skills=[x.strip() for x in request.form.getlist("required_skills")+[request.form.get("new_skill","")] if x.strip()]; interests=[x.strip() for x in request.form.getlist("interests")+[request.form.get("new_interest","")] if x.strip()]
        for item in skills: con.execute("INSERT OR IGNORE INTO skill_catalog(name) VALUES(?)",(item,))
        for item in interests: con.execute("INSERT OR IGNORE INTO interest_catalog(name) VALUES(?)",(item,))
        image=save_image(request.files.get("task_image")); image="images/tasks/cleanup.svg" if image is None else image
        if image is False: flash("Use a PNG, JPG, GIF, or WEBP image.","danger"); return redirect(url_for("manage_tasks"))
        con.execute("INSERT INTO tasks(title,description,required_skills,interests,availability,location,image_filename,organization_id,start_date,end_date) VALUES(?,?,?,?,?,?,?,?,?,?)",(request.form["title"],request.form["description"],", ".join(skills),", ".join(interests),", ".join(request.form.getlist("availability")),request.form["location"],image,session["user_id"] if session.get("role")=="organization" else None,request.form["start_date"],request.form["end_date"])); con.commit(); flash("Task posted.","success"); return redirect(url_for("manage_tasks"))
    query="SELECT tasks.*,COALESCE(organization_profiles.organization_name,users.name,'System Admin') AS organization_name FROM tasks LEFT JOIN users ON users.id=tasks.organization_id LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id" if session.get("role")=="admin" else "SELECT tasks.*,COALESCE(organization_profiles.organization_name,users.name,'My Organization') AS organization_name FROM tasks LEFT JOIN users ON users.id=tasks.organization_id LEFT JOIN organization_profiles ON organization_profiles.user_id=tasks.organization_id WHERE tasks.organization_id=?"
    rows=con.execute(query+" ORDER BY id DESC",() if session.get("role")=="admin" else (session["user_id"],)).fetchall()
    return render_template("manage_tasks.html",tasks=rows,skills=con.execute("SELECT name FROM skill_catalog ORDER BY name").fetchall(),interests=con.execute("SELECT name FROM interest_catalog ORDER BY name").fetchall())
@app.route("/organization/task/<int:task_id>/edit",methods=("GET","POST"))
@app.route("/admin/task/<int:task_id>/edit",methods=("GET","POST"))
@require("organization","admin")
def edit_task(task_id):
    con=db(); task=con.execute("SELECT * FROM tasks WHERE id=?",(task_id,)).fetchone()
    if not owns(task): flash("You can only manage your own tasks.","danger"); return redirect(url_for("manage_tasks"))
    if request.method=="POST":
        if request.form["end_date"] < request.form["start_date"]:
            flash("The work end date must be on or after the start date.","danger"); return redirect(url_for("edit_task",task_id=task_id))
        con.execute("UPDATE tasks SET title=?,description=?,required_skills=?,interests=?,availability=?,location=?,start_date=?,end_date=? WHERE id=?",(request.form["title"],request.form["description"],request.form["required_skills"],request.form["interests"],", ".join(request.form.getlist("availability")),request.form["location"],request.form["start_date"],request.form["end_date"],task_id)); con.commit(); flash("Task updated.","success"); return redirect(url_for("manage_tasks"))
    return render_template("edit_task.html",task=task)
@app.route("/organization/task/<int:task_id>/delete",methods=("POST",))
@app.route("/admin/task/<int:task_id>/delete",methods=("POST",))
@require("organization","admin")
def delete_task(task_id):
    con=db(); task=con.execute("SELECT * FROM tasks WHERE id=?",(task_id,)).fetchone()
    if owns(task): con.execute("DELETE FROM applications WHERE task_id=?",(task_id,)); con.execute("DELETE FROM tasks WHERE id=?",(task_id,)); con.commit(); flash("Task deleted.","info")
    else: flash("You can only manage your own tasks.","danger")
    return redirect(url_for("manage_tasks"))
@app.route("/organization/applications")
@app.route("/admin/applications")
@require("organization","admin")
def manage_applications():
    con=db(); base="SELECT applications.*,users.name,users.email,tasks.title,tasks.organization_id FROM applications JOIN users ON users.id=applications.volunteer_id JOIN tasks ON tasks.id=applications.task_id"; query=base+(" ORDER BY applications.id DESC" if session.get("role")=="admin" else " WHERE tasks.organization_id=? ORDER BY applications.id DESC")
    return render_template("manage_applications.html",applications=con.execute(query,() if session.get("role")=="admin" else (session["user_id"],)).fetchall())
@app.route("/organization/application/<int:application_id>/<decision>",methods=("POST",))
@app.route("/admin/application/<int:application_id>/<decision>",methods=("POST",))
@require("organization","admin")
def update_application(application_id,decision):
    con=db(); record=con.execute("SELECT applications.volunteer_id,tasks.title,tasks.organization_id FROM applications JOIN tasks ON tasks.id=applications.task_id WHERE applications.id=?",(application_id,)).fetchone()
    if decision in ("Accepted","Rejected","Completed") and owns(record):
        con.execute("UPDATE applications SET status=? WHERE id=?",(decision,application_id)); con.execute("INSERT INTO notifications(user_id,message) VALUES(?,?)",(record["volunteer_id"],f"Your application for '{record['title']}' was marked {decision.lower()}.")); con.commit(); flash("Application updated.","success")
    return redirect(url_for("manage_applications"))
@app.route("/admin/login",methods=("GET","POST"))
@app.route("/admin",methods=("GET","POST"))
def admin_login():
    if session.get("role")=="admin": return redirect(url_for("admin_dashboard"))
    if request.method=="POST":
        identifier=request.form["identifier"].strip()
        user=db().execute("SELECT * FROM users WHERE role='admin' AND (lower(email)=lower(?) OR lower(name)=lower(?))",(identifier,identifier)).fetchone()
        if user and check_password_hash(user["password"],request.form["password"]):
            session.clear(); session.update(user_id=user["id"],user_name=user["name"],role=user["role"]); flash("Administrator login successful.","success")
            return redirect(url_for("admin_dashboard"))
        flash("Use a valid administrator username/email and password.","danger")
    return render_template("admin_login.html")
@app.route("/admin/dashboard")
@require("admin")
def admin_dashboard():
    con=db(); counts={"volunteers":con.execute("SELECT COUNT(*) FROM users WHERE role='volunteer'").fetchone()[0],"organizations":con.execute("SELECT COUNT(*) FROM users WHERE role='organization'").fetchone()[0],"tasks":con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],"applications":con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]}; return render_template("admin_dashboard.html",counts=counts)
@app.route("/admin/volunteers")
@require("admin")
def manage_volunteers():
    rows=db().execute("SELECT users.*,volunteer_profiles.skills,volunteer_profiles.interests,volunteer_profiles.availability,volunteer_profiles.location,volunteer_profiles.photo_filename,SUM(CASE WHEN applications.status='Completed' THEN 1 ELSE 0 END) completed_count FROM users LEFT JOIN volunteer_profiles ON users.id=volunteer_profiles.user_id LEFT JOIN applications ON users.id=applications.volunteer_id WHERE users.role='volunteer' GROUP BY users.id").fetchall(); return render_template("manage_volunteers.html",volunteers=rows)
@app.route("/admin/volunteer/<int:volunteer_id>",methods=("GET","POST"))
@require("admin")
def edit_volunteer(volunteer_id):
    con=db(); volunteer=con.execute("SELECT users.*,volunteer_profiles.skills,volunteer_profiles.interests,volunteer_profiles.availability,volunteer_profiles.location FROM users LEFT JOIN volunteer_profiles ON users.id=volunteer_profiles.user_id WHERE users.id=? AND users.role='volunteer'",(volunteer_id,)).fetchone()
    if not volunteer:return redirect(url_for("manage_volunteers"))
    if request.method=="POST":
        con.execute("UPDATE users SET name=?,email=?,date_of_birth=? WHERE id=?",(request.form["name"],request.form["email"],request.form["date_of_birth"],volunteer_id)); profile=con.execute("SELECT id FROM volunteer_profiles WHERE user_id=?",(volunteer_id,)).fetchone(); vals=(request.form["skills"],request.form["interests"],", ".join(request.form.getlist("availability")),request.form["location"],volunteer_id)
        if profile: con.execute("UPDATE volunteer_profiles SET skills=?,interests=?,availability=?,location=? WHERE user_id=?",vals)
        else: con.execute("INSERT INTO volunteer_profiles(skills,interests,availability,location,user_id) VALUES(?,?,?,?,?)",vals)
        con.commit(); flash("Volunteer updated.","success"); return redirect(url_for("manage_volunteers"))
    return render_template("edit_volunteer.html",volunteer=volunteer)
@app.route("/admin/volunteer/<int:volunteer_id>/delete",methods=("POST",))
@require("admin")
def delete_volunteer(volunteer_id):
    con=db(); con.execute("DELETE FROM notifications WHERE user_id=?",(volunteer_id,)); con.execute("DELETE FROM applications WHERE volunteer_id=?",(volunteer_id,)); con.execute("DELETE FROM volunteer_profiles WHERE user_id=?",(volunteer_id,)); con.execute("DELETE FROM users WHERE id=? AND role='volunteer'",(volunteer_id,)); con.commit(); flash("Volunteer deleted.","info"); return redirect(url_for("manage_volunteers"))
@app.route("/admin/organizations")
@require("admin")
def manage_organizations():
    rows=db().execute("SELECT users.*,organization_profiles.organization_name,organization_profiles.contact_person,organization_profiles.phone,organization_profiles.location,organization_profiles.description,COUNT(tasks.id) task_count,GROUP_CONCAT(tasks.title, ' | ') posted_work FROM users JOIN organization_profiles ON users.id=organization_profiles.user_id LEFT JOIN tasks ON users.id=tasks.organization_id WHERE users.role='organization' GROUP BY users.id").fetchall(); return render_template("manage_organizations.html",organizations=rows)
@app.route("/admin/organization/<int:organization_id>/works")
@require("admin")
def organization_works(organization_id):
    con=db()
    organization=con.execute("SELECT users.name,organization_profiles.organization_name FROM users LEFT JOIN organization_profiles ON users.id=organization_profiles.user_id WHERE users.id=? AND users.role='organization'",(organization_id,)).fetchone()
    if not organization: return redirect(url_for("manage_organizations"))
    works=con.execute("SELECT * FROM tasks WHERE organization_id=? ORDER BY id DESC",(organization_id,)).fetchall()
    return render_template("organization_works.html",organization=organization,works=works)
@app.route("/admin/organization/<int:organization_id>",methods=("GET","POST"))
@require("admin")
def edit_organization(organization_id):
    con=db(); org=con.execute("SELECT users.*,organization_profiles.* FROM users JOIN organization_profiles ON users.id=organization_profiles.user_id WHERE users.id=?",(organization_id,)).fetchone()
    if not org:return redirect(url_for("manage_organizations"))
    if request.method=="POST": con.execute("UPDATE users SET name=?,email=? WHERE id=?",(request.form["organization_name"],request.form["email"],organization_id)); con.execute("UPDATE organization_profiles SET organization_name=?,contact_person=?,phone=?,location=?,description=? WHERE user_id=?",(request.form["organization_name"],request.form["contact_person"],request.form["phone"],request.form["location"],request.form["description"],organization_id)); con.commit(); flash("Organization updated.","success"); return redirect(url_for("manage_organizations"))
    return render_template("edit_organization.html",organization=org)

with app.app_context(): init_db()
if __name__=="__main__": app.run(debug=True)
