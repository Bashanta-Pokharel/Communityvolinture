# Community Volunteer System

A simple Flask project where volunteers apply for work, organizations post work, and an admin manages both.

## Run the project

1. Start **MySQL** in XAMPP.
2. Open this project folder in the terminal.
3. Run these commands:

```bash
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

4. Open `http://127.0.0.1:5000` in the browser.

The project creates the `community_volinturee` MySQL database automatically when XAMPP MySQL is running.

## Demo login accounts

| Role | Username / email | Password |
|---|---|---|
| Admin | `admin` or `admin@gmail.com` | `admin123` |
| Volunteer | `bashanta27` or `bashanta@gmail.com` | `Bashanta123` |
| Volunteer | `sweekriti42` or `sweekriti@gmail.com` | `Bashanta123` |
| Volunteer | `kusum65` or `kusum@gmail.com` | `Bashanta123` |
| Volunteer | `aagaman18` or `aagaman@gmail.com` | `Bashanta123` |
| Volunteer | `bhuban83` or `bhuban@gmail.com` | `Bashanta123` |

These are classroom demo accounts. Passwords are stored as hashes in the MySQL database.

## Main files

| File | Simple purpose |
|---|---|
| `app.py` | Flask routes, login, and MySQL connection |
| `schema.sql` | MySQL tables |
| `services/matching.py` | Jaccard similarity calculation |
| `templates/` | HTML pages |
| `static/css/style.css` | Page colors and layout |
| `static/js/script.js` | Browser actions and status indicator |

## Jaccard similarity

The project uses one matching algorithm:

`J(A, B) = |A ∩ B| / |A ∪ B|`

- `A` is the volunteer’s skills.
- `B` is the work’s required skills.
- `A ∩ B` means the skills both have.
- `A ∪ B` means every different skill from both lists.

Example: volunteer has `Teaching, First Aid`; a task needs `Teaching, Communication`.

Common skills = 1 (`Teaching`). All different skills = 3. The result is `1 / 3 = 33%`.

The Bashanta demo profile has 9 skills. Four demo works deliberately require 5, 6, 7, and 8 of those skills, so they show `55.56%`, `66.67%`, `77.78%`, and `88.89%` Jaccard similarity.
