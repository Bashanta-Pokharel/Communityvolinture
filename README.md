# Community Volunteer System

A small beginner Flask application with two roles: **volunteer** and **organization/admin**. It uses SQLite, so no MySQL server is needed.

## Run it

```bash
python3 --version
python3 -m venv venv
source venv/bin/activate       # macOS/Linux
# Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Open `http://127.0.0.1:5000`. Stop the app with `Ctrl+C`; leave the environment with `deactivate`.

Demo organization account: `admin@community.local` / `admin123`.

## Project structure

```
app.py                    Flask routes, login, database helpers, and matching function
schema.sql                SQLite table definitions
community_volunteer.db   Created automatically; contains the application data
templates/                Jinja HTML pages rendered by Flask
static/css/style.css      Small custom styles; Bootstrap does most visual work
static/js/script.js       Optional JavaScript area
requirements.txt          Python packages needed by the project
```

Browser → Flask route in `app.py` → SQLite database (when needed) → Jinja template → browser.

## Data model

| Table | What it stores | Important relationship |
|---|---|---|
| `users` | account name, email, password hash, role | One user is a volunteer or admin |
| `volunteer_profiles` | skills, interests, availability, location | `user_id` links to one volunteer user |
| `tasks` | organization-created opportunities and requirements | Each task can have many applications |
| `applications` | volunteer, task, status, similarity score | `volunteer_id` and `task_id` link the two sides |

A primary key is the table’s unique `id`. A foreign key is a link to an `id` in another table.

## The only matching algorithm: Jaccard similarity

`J(A, B) = |A ∩ B| / |A ∪ B|`

- `A`: volunteer terms, such as skills.
- `B`: task terms, such as required skills.
- `A ∩ B`: intersection—terms shared by both sets.
- `A ∪ B`: union—all unique terms from both sets.
- `| |`: the number of terms in that set.

Example: volunteer skills = `{python, first aid, teaching}`; task skills = `{first aid, teaching, communication}`. The intersection is `{first aid, teaching}` (2); the union is `{python, first aid, teaching, communication}` (4). Therefore `J = 2 / 4 = 0.50`, or **50%**.

Study the Jaccard code in `services/matching.py`. Its `terms()` function makes comma-separated form input into Python sets. Its `jaccard_similarity()` function uses `&` for the intersection and `|` for the union, then calculates `len(intersection) / len(union)`. The Similarity Tool form lets you compare skills, interests, or any other comma-separated terms. No weighted score or other matching algorithm is used.

An application is automatically **Qualified** when its Jaccard skill score is at least 50% and the volunteer has at least one free day in common with the task. This is a simple project rule, not a universal rule. The volunteer receives an in-app message immediately; the organization can still accept, reject, or mark the completed job.

## Bootstrap classes used

| Class | Purpose |
|---|---|
| `container`, `row`, `col-md-*`, `col-lg-*` | Responsive page width and grid columns |
| `navbar`, `navbar-expand-lg`, `navbar-dark`, `bg-success` | Responsive green navigation bar |
| `card`, `card-body`, `card-footer`, `shadow-sm` | Group content into bordered, raised panels |
| `btn`, `btn-success`, `btn-outline-success`, `btn-warning` | Styled action buttons |
| `form-control`, `form-label` | Consistent accessible-looking form inputs and labels |
| `table`, `table-hover`, `table-responsive` | Scrollable and readable application tables |
| `alert`, `alert-success`, `alert-warning` | Temporary feedback messages after actions |
| `badge`, `text-bg-success` | Small labels for locations and status |
| `d-flex`, `justify-content-center`, `align-items-center` | Flexible alignment utilities |
| `py-5`, `mb-3`, `mt-4`, `w-100` | Padding, margins, and full-width sizing |
