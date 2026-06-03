# 🩸 Blood Bank System – k-project

## Setup

1. Install dependencies:
   ```
   pip install flask
   ```

2. Run the app:
   ```
   python app.py
   ```

3. Open browser: http://127.0.0.1:5000

4. Login: **admin / 12345**

---

## Fixes Applied

### ✅ Expiry Date Bug Fixed
- Blood now expires **42 days** after donation (standard shelf life)
- To test with fewer days, change `EXPIRY_DAYS = 42` in `app.py`
- Each donation creates its **own batch row** with its own expiry date

### ✅ Stock Shows Per-Batch Info
- Donating O+ on March 25 → row: O+ | 2 units | donated: 25-Mar | expires: 6-May
- Donating O+ again on March 27 → **new separate row** with correct new expiry
- Summary table at top shows total units per blood group

### ✅ Auto-Removal of Expired Stock
- `purge_expired_stock()` runs automatically on every page load
- Any batch past its expiry date is deleted from the database
- Dashboard only shows valid (non-expired) unit counts

### ✅ Press Enter to Submit
- All forms (Login, Donor, Request) now accept **Enter key** to submit
- No need to click the Submit button with mouse

### ✅ FIFO Blood Dispensing
- When a blood request is approved, oldest batches are used first
- This minimises waste of blood nearing expiry

---

## Project Structure

```
k-project/
├── app.py                    ← Main Flask application
├── database.db               ← Auto-created on first run
├── static/
│   └── style.css             ← Styling
└── templates/
    ├── base.html             ← Layout with navbar + sidebar
    ├── login.html            ← Login page
    ├── index.html            ← Dashboard
    ├── donor.html            ← Add/manage donors
    ├── stock.html            ← View blood stock (per batch)
    ├── history.html          ← Donation history
    ├── request.html          ← Request blood form
    └── requests.html         ← All requests list
```
