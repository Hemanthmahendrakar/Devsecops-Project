# Digital Twin Avatar — update notes

This patch only touches the files below. Drop them into the existing
project at the same paths, overwriting what's there.

```
app.py
stats_engine.py
static/css/style.css
static/js/app.js
templates/index.html
templates/login.html
```

Nothing else in the project (requirements.txt, DB setup, models, etc.)
needs to change.

## What changed

### 1. `stats_engine.py` — rewritten around your real categories
The engine previously referenced categories like `Rent`, `Groceries`,
`Dining`, `Personal Care`, `Insurance`, `Subscriptions` — none of which
exist in your app's `ALLOWED_CATEGORIES`:

```python
ALLOWED_CATEGORIES = [
    "Food", "Transport", "Housing", "Utilities", "Entertainment",
    "Health", "Shopping", "Education", "Travel", "Other",
]
```

It's now built directly off that list:

| Bucket | Categories |
|---|---|
| **Needs** | Food, Transport, Housing, Utilities, Health, Education |
| **Wants** | Entertainment, Shopping, Travel |
| **Other** | Other *(falls into the implicit savings/buffer bucket)* |
| **Fun spend** (happiness signal) | Entertainment, Travel |

The four stats (`health`, `energy`, `happiness`, `wealth_level`) and the
forecast model work exactly as before — 50/30/20 rule, z-score anomaly
detection, fun-spend consistency, EMA trend — just pointed at the right
category names.

Also added `compute_category_breakdown()`, which returns every category
with its amount, % share of the month, and bucket (`need` / `want` /
`other`) — this powers the new "This month by category" card on the
dashboard. It's included automatically in the `/api/avatar/recalculate`
and `/api/avatar/insights` responses as `category_breakdown`.

> Note: `app.py` had one matching one-line fix — it referenced the old
> constant name `ENTERTAINMENT_TRAVEL_CATEGORIES`, which is now
> `FUN_CATEGORIES`.

### 2. Visual redesign + light/dark theme
`static/css/style.css` was rewritten to use theme-aware CSS variables.
Every color in the app now resolves through `:root` variables, with a
light-theme override block:

```css
:root[data-theme="light"] { ... }
```

The theme is:
- Read from `localStorage` (or the OS `prefers-color-scheme`) before
  first paint, via a small inline `<script>` in `<head>` — so there's no
  flash of the wrong theme.
- Toggled with the new sun/moon button in the top bar (and on the login
  page), which just flips `data-theme` on `<html>` and saves the choice.

General visual cleanup: consistent shadows/elevation on panels, a
proper light palette (not just "dark colors that happen to be light"),
slightly larger buttons/touch targets, and a new category-breakdown
card with need/want/other color coding.

### 3. Logout button
The top bar now shows the logged-in username and a **Log out** button
next to the theme toggle. It posts to your existing `/logout` route, so
no backend change was needed there.

### 4. Category breakdown card
New card between the Insights panel and the Trend history chart on the
dashboard, showing every category's spend this month as a labeled bar,
color-coded by need/want/other, with a small legend.

## Files NOT included (unchanged)
- `requirements.txt`
- Anything under `static/models/` (your FBX avatar files)
- DB setup / migrations

## Quick sanity check after copying files in
```bash
python3 -m py_compile app.py stats_engine.py
```
Then run the app as usual and confirm:
- Login page shows the theme toggle, switches correctly, and persists across reload.
- Dashboard shows the logout button with your username.
- Hitting "Refresh now" populates the new category card.
