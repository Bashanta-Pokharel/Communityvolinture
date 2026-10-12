"""
services/education.py
Education level options and volunteer-task matching logic.
"""

from database import run, commit
from services.matching import jaccard_similarity

# ── Fallback lists used when the DB is offline ───────────────────────────────

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
    "Private / Corporate Social Responsibility (CSR)",
]


def get_education_lists():
    """Return (volunteer_options, task_options, volunteer_ranks, task_ranks) from DB."""
    try:
        rows = run("SELECT * FROM education_catalog ORDER BY rank_level ASC, id ASC").fetchall()
        if rows:
            v_opts  = [r["name"] for r in rows if r.get("category") in ("volunteer", "both")]
            t_opts  = [r["name"] for r in rows if r.get("category") in ("task", "both")]
            v_ranks = {r["name"]: r["rank_level"] for r in rows if r.get("category") in ("volunteer", "both")}
            t_ranks = {r["name"]: r["rank_level"] for r in rows if r.get("category") in ("task", "both")}
            return v_opts, t_opts, v_ranks, t_ranks
    except Exception:
        pass
    return VOLUNTEER_EDUCATION_OPTIONS, TASK_MIN_EDUCATION_OPTIONS, EDUCATION_RANK_VOLUNTEER, EDUCATION_RANK_TASK


def check_education_qualified(vol_edu, task_min_edu):
    """Return True if the volunteer's education meets the task requirement."""
    if not task_min_edu or task_min_edu == "No Formal Education Required":
        return True
    _, _, v_ranks, t_ranks = get_education_lists()
    vol_rank  = v_ranks.get(vol_edu,      EDUCATION_RANK_VOLUNTEER.get(vol_edu, 1))
    task_rank = t_ranks.get(task_min_edu, EDUCATION_RANK_TASK.get(task_min_edu, 1))
    return vol_rank >= task_rank


def match_details(profile, task):
    """Score how well a volunteer matches a task (Jaccard + days + education)."""
    score, vol_skills, req_skills, common_skills, _ = jaccard_similarity(
        profile["skills"], task["required_skills"]
    )
    _, _, _, common_days, _ = jaccard_similarity(profile["availability"], task["availability"])

    all_skills_match = bool(req_skills) and req_skills.issubset(vol_skills)
    edu_qualified    = check_education_qualified(
        profile.get("education_level") or "Uneducated / Basic Literacy",
        task.get("min_education")      or "No Formal Education Required",
    )
    # Qualifies when: (full match OR >30% score) AND shares a free day AND education met
    qualified = (all_skills_match or score > 0.30) and bool(common_days) and edu_qualified

    return {
        "score":            score,
        "common_skills":    sorted(common_skills),
        "common_days":      sorted(common_days),
        "all_skills_match": all_skills_match,
        "edu_qualified":    edu_qualified,
        "qualified":        qualified,
    }


def refresh_applications(volunteer_id):
    """Recalculate pending application statuses when a volunteer updates their profile."""
    profile = run("SELECT * FROM volunteer_profiles WHERE user_id=?", (volunteer_id,)).fetchone()
    if not profile:
        return
    records = run(
        "SELECT applications.id AS application_id, applications.status AS application_status, tasks.* "
        "FROM applications JOIN tasks ON tasks.id=applications.task_id "
        "WHERE applications.volunteer_id=?",
        (volunteer_id,),
    ).fetchall()
    for record in records:
        result = match_details(profile, record)
        if record["application_status"] not in ("Accepted", "Rejected", "Completed"):
            status = "Pending" if result["qualified"] else "Not qualified"
            run("UPDATE applications SET score=?, status=? WHERE id=?",
                (result["score"], status, record["application_id"]))
    commit()
