# Expense Tracker with Analytics

A full-stack expense tracking app with a Flask backend (SQLite) and a vanilla HTML/CSS/JS frontend, featuring login/signup, CRUD for expenses, and analytics charts (pie + bar) powered by Chart.js.

## Features
- User registration & login (session-based auth, hashed passwords)
- Add / edit / delete expenses (title, amount, category, date, note)
- Filter expenses by category
- Dashboard summary cards: total spent, this month, average expense, top category
- Pie chart: spending by category
- Bar chart: spending by month
- SQLite storage (`expenses.db`, auto-created on first run)

## Project Structure
```
expense_tracker/
├── app.py                  # Flask app: routes, auth, CRUD, analytics endpoints
├── requirements.txt
├── templates/
│   ├── login.html
│   ├── register.html
│   └── index.html          # main dashboard
└── static/
    ├── css/
    │   ├── auth.css
    │   └── style.css
    └── js/
        ├── auth.js          # login/register logic
        └── app.js           # dashboard logic: CRUD + charts
```

## Setup & Run

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the app:
   ```bash
   python app.py
   ```

3. Open your browser at: **http://localhost:5000**

The SQLite database (`expenses.db`) is created automatically on first run, including `users` and `expenses` tables.

## Usage
1. Go to `/register` to create an account.
2. Log in at `/login`.
3. Add expenses from the dashboard form (title, amount, category, date, optional note).
4. View live-updating summary cards and charts.
5. Edit or delete any expense from the list; filter the list by category.
6. Click **Logout** to end your session.

## Notes / Next Steps
- Change `app.config["SECRET_KEY"]` in `app.py` before deploying anywhere public.
- For production, use a proper WSGI server (e.g. gunicorn) instead of the Flask dev server, and consider switching `SECRET_KEY` to an environment variable.
- Categories are currently a fixed list in `app.py` (`ALLOWED_CATEGORIES`) — edit that list to customize.
