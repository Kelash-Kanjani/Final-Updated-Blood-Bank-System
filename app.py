from flask import Flask, render_template, request, redirect, flash, session, jsonify
import sqlite3
from datetime import date, timedelta
import random
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

app = Flask(__name__)
app.secret_key = "admin123"

# Blood expires after 42 days. Change for testing.
EXPIRY_DAYS = 42

# ─────────────────────────────────────────────
#  EMAIL CONFIGURATION
#  Steps to get Gmail App Password:
#    1. Go to myaccount.google.com
#    2. Security -> 2-Step Verification (must be ON)
#    3. Security -> App Passwords -> Generate
#    4. Paste the 16-char password below
# ─────────────────────────────────────────────
EMAIL_SENDER   = "your@gmail.com"   # <- your Gmail here
EMAIL_PASSWORD = "abcd efgh ijkl mnop"   # <- 16-char App Password
EMAIL_ENABLED  = True  # <- set True after filling credentials


def send_donor_email(recipient_email, donor_name, donor_code, blood_group,
                     donation_date, units, nationality):
    """Send Donor ID confirmation email. Returns (success: bool, message: str)."""
    if not EMAIL_ENABLED:
        return False, "Email not configured — set EMAIL_ENABLED=True in app.py"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Your Blood Donor ID - {donor_code}"
        msg["From"]    = f"Blood Bank System <{EMAIL_SENDER}>"
        msg["To"]      = recipient_email

        text_body = f"""Dear {donor_name},

Thank you for your generous blood donation!

Your Donor ID : {donor_code}
Blood Group   : {blood_group}
Donated On    : {donation_date}
Units         : {units}

Please save your Donor ID. You will need it for every future donation.

Regards,
Blood Bank System
"""

        html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
body{{font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:0}}
.wrap{{max-width:560px;margin:30px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1)}}
.header{{background:#dc3545;padding:28px 32px;text-align:center}}
.header h1{{color:#fff;margin:0;font-size:1.4rem}}
.header p{{color:rgba(255,255,255,.8);margin:6px 0 0;font-size:.9rem}}
.body{{padding:28px 32px}}
.id-box{{background:#fff3f3;border:2px dashed #dc3545;border-radius:10px;padding:18px;text-align:center;margin:20px 0}}
.id-box .label{{font-size:.75rem;color:#888;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}}
.id-box .code{{font-size:2rem;font-weight:800;color:#dc3545;letter-spacing:.05em}}
.details{{background:#f9f9f9;border-radius:8px;padding:16px 20px;margin-bottom:20px}}
.details table{{width:100%;border-collapse:collapse;font-size:.88rem}}
.details td{{padding:7px 0;border-bottom:1px solid #eee}}
.details td:first-child{{color:#888;width:140px}}
.details tr:last-child td{{border-bottom:none}}
.note{{background:#fffbe6;border-left:4px solid #ffc107;padding:12px 16px;border-radius:6px;font-size:.82rem;color:#555;margin-bottom:20px}}
.footer{{background:#f4f4f4;padding:16px 32px;text-align:center;font-size:.75rem;color:#aaa}}
</style></head>
<body>
<div class="wrap">
  <div class="header"><h1>Blood Bank System</h1><p>Donation Confirmation</p></div>
  <div class="body">
    <p>Dear <strong>{donor_name}</strong>,</p>
    <p>Thank you for your life-saving blood donation!</p>
    <div class="id-box">
      <div class="label">Your Donor ID</div>
      <div class="code">{donor_code}</div>
    </div>
    <div class="details">
      <table>
        <tr><td>Blood Group</td><td><strong>{blood_group}</strong></td></tr>
        <tr><td>Donated On</td><td>{donation_date}</td></tr>
        <tr><td>Units</td><td>{units}</td></tr>
        <tr><td>Nationality</td><td>{nationality}</td></tr>
      </table>
    </div>
    <div class="note">
      <strong>Important:</strong> Save your Donor ID <strong>{donor_code}</strong>.
      You will need it every time you donate blood in the future.
    </div>
    <p>We deeply appreciate your generosity!</p>
  </div>
  <div class="footer">Automated message from Blood Bank System. Do not reply.</div>
</div>
</body></html>"""

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, recipient_email, msg.as_string())

        return True, f"Donor ID emailed successfully to {recipient_email}"

    except smtplib.SMTPAuthenticationError:
        return False, "Email failed: Wrong Gmail address or App Password."
    except smtplib.SMTPException as e:
        return False, f"Email failed: {str(e)}"
    except Exception as e:
        return False, f"Email error: {str(e)}"


# ─────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # ── TABLE 1: Donor (3NF — no transitive dependencies) ──────────────
    # Normalized: donor identity separated from donation facts
    cur.execute("""
    CREATE TABLE IF NOT EXISTS Donor(
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_code   TEXT UNIQUE NOT NULL,
        name         TEXT NOT NULL,
        nationality  TEXT NOT NULL DEFAULT 'Pakistani'
                     CHECK(nationality IN ('Pakistani','Foreigner')),
        cnic         TEXT UNIQUE,
        phone        TEXT UNIQUE,
        email        TEXT UNIQUE,
        blood_group  TEXT NOT NULL
                     CHECK(blood_group IN ('A+','A-','B+','B-',
                                           'O+','O-','AB+','AB-'))
    )
    """)

    # ── TABLE 2: Stock (one row per batch, avoids update anomalies) ─────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS Stock(
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        blood_group   TEXT NOT NULL,
        units         INTEGER NOT NULL CHECK(units >= 0),
        donation_date TEXT NOT NULL,
        expiry_date   TEXT NOT NULL
    )
    """)

    # ── TABLE 3: Donation (FK to Donor — 2NF, no partial dependency) ───
    cur.execute("""
    CREATE TABLE IF NOT EXISTS Donation(
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id      INTEGER NOT NULL
                      REFERENCES Donor(id) ON DELETE CASCADE,
        donation_date TEXT NOT NULL,
        units         INTEGER NOT NULL CHECK(units > 0)
    )
    """)

    # ── TABLE 4: Requests ───────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS Requests(
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        hospital    TEXT NOT NULL,
        blood_group TEXT NOT NULL,
        units       INTEGER NOT NULL CHECK(units > 0),
        status      TEXT NOT NULL DEFAULT 'Pending'
                    CHECK(status IN ('Approved','Rejected','Pending'))
    )
    """)

    # ── TABLE 5: AuditLog (for Trigger records) ─────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS AuditLog(
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        table_name TEXT NOT NULL,
        record_id  INTEGER,
        details    TEXT,
        event_time TEXT NOT NULL
    )
    """)

    # ══════════════════════════════════════════════════════════════════
    #  INDEXES — speed up the most frequent lookups
    # ══════════════════════════════════════════════════════════════════
    cur.execute("CREATE INDEX IF NOT EXISTS idx_donor_cnic       ON Donor(cnic)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_donor_phone      ON Donor(phone)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_donor_blood      ON Donor(blood_group)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_donor_code       ON Donor(donor_code)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stock_blood      ON Stock(blood_group)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stock_expiry     ON Stock(expiry_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_donation_donor   ON Donation(donor_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_donation_date    ON Donation(donation_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_status  ON Requests(status)")

    # ══════════════════════════════════════════════════════════════════
    #  TRIGGERS
    # ══════════════════════════════════════════════════════════════════

    # TRIGGER 1: After a new donation is inserted → write to AuditLog
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_after_donation_insert
    AFTER INSERT ON Donation
    BEGIN
        INSERT INTO AuditLog(event_type, table_name, record_id, details, event_time)
        VALUES(
            'INSERT',
            'Donation',
            NEW.id,
            'Donor ID: ' || NEW.donor_id ||
            ' donated ' || NEW.units || ' unit(s) on ' || NEW.donation_date,
            datetime('now','localtime')
        );
    END
    """)

    # TRIGGER 2: After a stock batch is deleted (expired or used) → log it
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_after_stock_delete
    AFTER DELETE ON Stock
    BEGIN
        INSERT INTO AuditLog(event_type, table_name, record_id, details, event_time)
        VALUES(
            'DELETE',
            'Stock',
            OLD.id,
            OLD.blood_group || ' - ' || OLD.units ||
            ' unit(s) removed. Expiry was: ' || OLD.expiry_date,
            datetime('now','localtime')
        );
    END
    """)

    # TRIGGER 3: After a request is inserted → log whether approved or rejected
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_after_request_insert
    AFTER INSERT ON Requests
    BEGIN
        INSERT INTO AuditLog(event_type, table_name, record_id, details, event_time)
        VALUES(
            'INSERT',
            'Requests',
            NEW.id,
            NEW.hospital || ' requested ' || NEW.units ||
            ' unit(s) of ' || NEW.blood_group ||
            ' — Status: ' || NEW.status,
            datetime('now','localtime')
        );
    END
    """)

    # ══════════════════════════════════════════════════════════════════
    #  VIEWS
    # ══════════════════════════════════════════════════════════════════

    # VIEW 1: Full donation history with donor details joined
    cur.execute("""
    CREATE VIEW IF NOT EXISTS vw_DonationHistory AS
    SELECT
        D.donor_code,
        D.name        AS donor_name,
        D.nationality,
        D.blood_group,
        DN.donation_date,
        DN.units,
        DN.id         AS donation_id
    FROM Donation DN
    JOIN Donor D ON DN.donor_id = D.id
    ORDER BY DN.donation_date DESC
    """)

    # VIEW 2: Current valid stock with days-until-expiry
    cur.execute("""
    CREATE VIEW IF NOT EXISTS vw_StockStatus AS
    SELECT
        id,
        blood_group,
        units,
        donation_date,
        expiry_date,
        CAST(julianday(expiry_date) - julianday('now') AS INTEGER) AS days_remaining
    FROM Stock
    WHERE expiry_date >= date('now')
    ORDER BY blood_group, expiry_date ASC
    """)

    # VIEW 3: Blood group summary — total available units per group
    cur.execute("""
    CREATE VIEW IF NOT EXISTS vw_BloodSummary AS
    SELECT
        blood_group,
        SUM(units)  AS total_units,
        COUNT(*)    AS total_batches,
        MIN(expiry_date) AS earliest_expiry
    FROM Stock
    WHERE expiry_date >= date('now')
    GROUP BY blood_group
    ORDER BY blood_group
    """)

    # VIEW 4: Request report — approved vs rejected counts
    cur.execute("""
    CREATE VIEW IF NOT EXISTS vw_RequestSummary AS
    SELECT
        blood_group,
        COUNT(*)                                      AS total_requests,
        SUM(CASE WHEN status='Approved' THEN 1 ELSE 0 END) AS approved,
        SUM(CASE WHEN status='Rejected' THEN 1 ELSE 0 END) AS rejected,
        SUM(units)                                    AS total_units_requested
    FROM Requests
    GROUP BY blood_group
    ORDER BY total_requests DESC
    """)

    conn.commit()
    conn.close()


def purge_expired_stock():
    today = str(date.today())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM Stock WHERE expiry_date < ?", (today,))
    conn.commit()
    conn.close()


init_db()


# ─────────────────────────────────────────────
#  VALIDATION HELPERS
# ─────────────────────────────────────────────

def validate_cnic(cnic):
    """Must match 00000-0000000-0 pattern exactly."""
    return bool(re.fullmatch(r'\d{5}-\d{7}-\d', cnic.strip()))


def validate_phone(phone):
    """Accepts 03XX-XXXXXXX or 03XXXXXXXXX (Pakistani mobile)."""
    cleaned = phone.replace("-", "").replace(" ", "")
    return bool(re.fullmatch(r'0[3]\d{9}', cleaned))


def format_cnic(raw):
    """Auto-format digits into 00000-0000000-0."""
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 13:
        return f"{digits[:5]}-{digits[5:12]}-{digits[12]}"
    return raw


# ─────────────────────────────────────────────
#  LOGIN
# ─────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == "admin" and password == "12345":
            session["user"] = username
            return redirect("/")
        else:
            flash("Invalid Login")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")


# ─────────────────────────────────────────────
#  HOME
# ─────────────────────────────────────────────

@app.route("/")
def home():
    if "user" not in session:
        return redirect("/login")

    sp_purge_expired_stock()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM Donor")
    donors = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM Donor WHERE nationality='Pakistani'")
    pk_donors = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM Donor WHERE nationality='Foreigner'")
    fg_donors = cur.fetchone()[0]

    cur.execute("SELECT SUM(units) FROM Stock")
    stock = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM Requests")
    requests_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM Requests WHERE status='Approved'")
    approved_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM Requests WHERE status='Rejected'")
    rejected_count = cur.fetchone()[0]

    # Blood group summary from VIEW
    cur.execute("SELECT blood_group, total_units FROM vw_BloodSummary")
    blood_summary = cur.fetchall()

    # Expiring soon (within 7 days) from VIEW
    cur.execute("""
        SELECT COUNT(*) FROM vw_StockStatus
        WHERE days_remaining <= 7
    """)
    expiring_soon = cur.fetchone()[0]

    # Recent activity from AuditLog
    cur.execute("SELECT event_type, table_name, details, event_time FROM AuditLog ORDER BY id DESC LIMIT 6")
    recent_activity = cur.fetchall()

    conn.close()
    return render_template("index.html",
        donors=donors, pk_donors=pk_donors, fg_donors=fg_donors,
        stock=stock, requests=requests_count,
        approved_count=approved_count, rejected_count=rejected_count,
        blood_summary=blood_summary, expiring_soon=expiring_soon,
        recent_activity=recent_activity)


# ─────────────────────────────────────────────
#  DONOR
# ─────────────────────────────────────────────

@app.route("/donor", methods=["GET", "POST"])
def donor():
    if "user" not in session:
        return redirect("/login")
    sp_purge_expired_stock()

    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        donor_type  = request.form["donor_type"]   # "new" or "old"

        # Safe units read — guards against empty string
        try:
            units = int(request.form.get("units", 0))
        except (ValueError, TypeError):
            units = 0
        if units < 1:
            flash("Please enter a valid number of units (minimum 1).")
            conn.close()
            return redirect("/donor")

        today  = str(date.today())
        expiry = str(date.today() + timedelta(days=EXPIRY_DAYS))

        # ── EXISTING DONOR ──────────────────────────────────────
        if donor_type == "old":
            lookup_by = request.form["lookup_by"]   # cnic | phone | donor_code
            lookup_val = request.form["lookup_val"].strip()

            if lookup_by == "cnic":
                lookup_val = format_cnic(lookup_val)
                cur.execute("SELECT * FROM Donor WHERE cnic=?", (lookup_val,))
            elif lookup_by == "phone":
                cur.execute("SELECT * FROM Donor WHERE phone=?", (lookup_val,))
            else:
                cur.execute("SELECT * FROM Donor WHERE donor_code=?", (lookup_val,))

            row = cur.fetchone()

            if not row:
                flash(f"No donor found with that {lookup_by.replace('_',' ').title()}. Please check and try again.")
                conn.close()
                return redirect("/donor")

            donor_id = row["id"]
            bg       = row["blood_group"]
            flash(f"Welcome back, {row['name']}!")

        # ── NEW DONOR ────────────────────────────────────────────
        else:
            nationality = request.form["nationality"]   # Pakistani | Foreigner
            name        = request.form["name"].strip()
            bg          = request.form["blood_group"]
            email       = request.form.get("email", "").strip()
            cnic        = request.form.get("cnic", "").strip()
            phone       = request.form.get("phone", "").strip()

            # ── Validation ──
            errors = []

            if nationality == "Pakistani":
                # CNIC mandatory
                if not cnic:
                    errors.append("CNIC is required for Pakistani donors.")
                else:
                    cnic = format_cnic(cnic)
                    if not validate_cnic(cnic):
                        errors.append("CNIC format must be: 00000-0000000-0")
                # Phone mandatory
                if not phone:
                    errors.append("Mobile number is required for Pakistani donors.")
                elif not validate_phone(phone):
                    errors.append("Phone must be a valid Pakistani number (e.g. 0300-1234567).")
                # Email optional — but if provided must look valid
                if email and "@" not in email:
                    errors.append("Please enter a valid email address.")

            else:  # Foreigner
                # Email mandatory
                if not email:
                    errors.append("Email is mandatory for foreign donors.")
                elif "@" not in email or "." not in email:
                    errors.append("Please enter a valid email address.")
                # CNIC and phone not required for foreigners
                cnic  = None
                phone = None

            # Duplicate check
            if nationality == "Pakistani" and cnic and not errors:
                cur.execute("SELECT id FROM Donor WHERE cnic=?", (cnic,))
                if cur.fetchone():
                    errors.append(f"A donor with CNIC {cnic} already exists.")

            if nationality == "Pakistani" and phone and not errors:
                cur.execute("SELECT id FROM Donor WHERE phone=?", (phone,))
                if cur.fetchone():
                    errors.append(f"A donor with phone {phone} already exists.")

            if nationality == "Foreigner" and email and not errors:
                cur.execute("SELECT id FROM Donor WHERE email=?", (email,))
                if cur.fetchone():
                    errors.append(f"A donor with email {email} already exists.")

            if errors:
                for e in errors:
                    flash(e)
                conn.close()
                return redirect("/donor")

            # Generate donor code
            donor_code = "D" + date.today().strftime("%d%m%Y") + str(random.randint(100, 999))

            # ── Stored Procedure: RegisterNewDonor ──────────────
            donor_id = sp_register_donor(
                name, nationality,
                cnic or None, phone or None, email or None,
                bg, donor_code
            )

            # ── Send Donor ID by email ──────────────────────────
            if email:
                ok, msg = send_donor_email(
                    recipient_email = email,
                    donor_name      = name,
                    donor_code      = donor_code,
                    blood_group     = bg,
                    donation_date   = today,
                    units           = units,
                    nationality     = nationality
                )
                if ok:
                    flash(f"Donor ID {donor_code} has been emailed to {email}")
                else:
                    # Email failed — still show ID on screen so staff can note it
                    flash(f"New Donor ID: {donor_code}  |  Note: {msg}")
            elif phone:
                flash(f"New Donor registered! Donor ID: {donor_code} — give this to the donor.")
            else:
                flash(f"New Donor ID: {donor_code}")

        # ── Stored Procedure: RecordDonation ─────────────────────
        ok, msg = sp_record_donation(donor_id, bg, units, today, expiry)
        if ok:
            flash(f"Donation saved! {units} unit(s) of {bg} added to stock. Expires: {expiry}")
        else:
            flash(f"Error saving donation: {msg}")

    # ── FETCH DONOR LIST ─────────────────────────────────────────
    cur.execute("SELECT * FROM Donor ORDER BY id DESC")
    donors = cur.fetchall()
    conn.close()

    return render_template("donor.html", donors=donors)


# ─────────────────────────────────────────────
#  API — lookup donor for existing-donor flow
# ─────────────────────────────────────────────

@app.route("/api/lookup_donor")
def lookup_donor():
    if "user" not in session:
        return jsonify({"error": "unauthorized"})

    by  = request.args.get("by", "")
    val = request.args.get("val", "").strip()

    conn = get_db()
    cur  = conn.cursor()

    if by == "cnic":
        val = format_cnic(val)
        cur.execute("SELECT donor_code, name, blood_group, nationality, phone, email FROM Donor WHERE cnic=?", (val,))
    elif by == "phone":
        cur.execute("SELECT donor_code, name, blood_group, nationality, phone, email FROM Donor WHERE phone=?", (val,))
    elif by == "donor_code":
        cur.execute("SELECT donor_code, name, blood_group, nationality, phone, email FROM Donor WHERE donor_code=?", (val,))
    else:
        return jsonify({"error": "invalid lookup"})

    row = cur.fetchone()
    conn.close()

    if row:
        return jsonify(dict(row))
    return jsonify({"error": "not found"})


# ─────────────────────────────────────────────
#  DELETE DONOR
# ─────────────────────────────────────────────

@app.route("/delete/<int:id>")
def delete(id):
    if "user" not in session:
        return redirect("/login")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM Donor WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect("/donor")


# ─────────────────────────────────────────────
#  STOCK
# ─────────────────────────────────────────────

@app.route("/stock")
def stock():
    if "user" not in session:
        return redirect("/login")
    sp_purge_expired_stock()

    conn = get_db()
    cur = conn.cursor()

    # Using VIEW: vw_StockStatus (includes days_remaining)
    cur.execute("SELECT * FROM vw_StockStatus")
    batches = cur.fetchall()

    # Using VIEW: vw_BloodSummary
    cur.execute("SELECT blood_group, total_units as total FROM vw_BloodSummary")
    summary = cur.fetchall()
    conn.close()

    today_str   = str(date.today())
    warning_str = str(date.today() + timedelta(days=7))

    return render_template("stock.html", batches=batches, summary=summary,
                           today_date=today_str, expiry_warning=warning_str)


# ─────────────────────────────────────────────
#  HISTORY
# ─────────────────────────────────────────────

@app.route("/history")
def history():
    if "user" not in session:
        return redirect("/login")
    conn = get_db()
    cur = conn.cursor()
    # Using VIEW: vw_DonationHistory
    cur.execute("SELECT * FROM vw_DonationHistory")
    data = cur.fetchall()
    conn.close()
    return render_template("history.html", data=data)


# ─────────────────────────────────────────────
#  REQUEST
# ─────────────────────────────────────────────

@app.route("/request", methods=["GET", "POST"])
def request_page():
    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":
        hospital = request.form["hospital"]
        bg       = request.form["blood_group"]
        units    = int(request.form["units"])

        # ── Stored Procedure: ProcessBloodRequest ────────────────
        sp_purge_expired_stock()
        status = sp_process_blood_request(hospital, bg, units)
        flash(f"Request {status}")

    return render_template("request.html")


# ─────────────────────────────────────────────
#  VIEW REQUESTS
# ─────────────────────────────────────────────

@app.route("/requests")
def requests():
    if "user" not in session:
        return redirect("/login")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM Requests ORDER BY id DESC")
    data = cur.fetchall()
    conn.close()
    return render_template("requests.html", data=data)


# ─────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────



# ─────────────────────────────────────────────
#  EMAIL SETTINGS (configure from browser)
# ─────────────────────────────────────────────

@app.route("/settings/email", methods=["GET", "POST"])
def email_settings():
    if "user" not in session:
        return redirect("/login")

    global EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_ENABLED

    test_result = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "save":
            EMAIL_SENDER   = request.form["email_sender"].strip()
            EMAIL_PASSWORD = request.form["email_password"].strip()
            EMAIL_ENABLED  = request.form.get("email_enabled") == "on"
            flash("Email settings saved for this session.")

        elif action == "test":
            EMAIL_SENDER   = request.form["email_sender"].strip()
            EMAIL_PASSWORD = request.form["email_password"].strip()
            EMAIL_ENABLED  = True
            test_to = request.form.get("test_to", EMAIL_SENDER).strip()
            ok, msg = send_donor_email(
                recipient_email = test_to,
                donor_name      = "Test User",
                donor_code      = "D-TEST-001",
                blood_group     = "O+",
                donation_date   = str(date.today()),
                units           = 1,
                nationality     = "Pakistani"
            )
            test_result = ("success", msg) if ok else ("danger", msg)

    return render_template("email_settings.html",
                           sender=EMAIL_SENDER,
                           password=EMAIL_PASSWORD,
                           enabled=EMAIL_ENABLED,
                           test_result=test_result)


# ══════════════════════════════════════════════════════════════════
#  STORED PROCEDURES (implemented as Python functions)
#  SQLite has no native SP syntax, so these encapsulate
#  multi-step DB logic exactly as a stored procedure would.
# ══════════════════════════════════════════════════════════════════

def sp_register_donor(name, nationality, cnic, phone, email, blood_group, donor_code):
    """
    SP: RegisterNewDonor
    Inserts a new donor and returns the new donor_id.
    Equivalent SQL stored procedure logic:
        INSERT INTO Donor(...) VALUES(...);
        SELECT last_insert_rowid();
    """
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO Donor(donor_code, name, nationality, cnic, phone, email, blood_group)
        VALUES(?,?,?,?,?,?,?)
    """, (donor_code, name, nationality, cnic, phone, email, blood_group))
    donor_id = cur.lastrowid
    conn.commit()
    conn.close()
    return donor_id


def sp_record_donation(donor_id, blood_group, units, donation_date, expiry_date):
    """
    SP: RecordDonation
    Inserts into both Donation and Stock in one atomic operation.
    If either insert fails, neither is committed (atomicity).
    """
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO Donation(donor_id, donation_date, units)
            VALUES(?,?,?)
        """, (donor_id, donation_date, units))

        cur.execute("""
            INSERT INTO Stock(blood_group, units, donation_date, expiry_date)
            VALUES(?,?,?,?)
        """, (blood_group, units, donation_date, expiry_date))

        conn.commit()
        return True, "Donation recorded successfully."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def sp_process_blood_request(hospital, blood_group, units_needed):
    """
    SP: ProcessBloodRequest
    Checks stock, deducts using FIFO from oldest batches,
    inserts into Requests with status, all in one transaction.
    """
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            "SELECT SUM(units) FROM Stock WHERE blood_group=?", (blood_group,)
        )
        available = cur.fetchone()[0] or 0

        if available >= units_needed:
            remaining = units_needed
            cur.execute("""
                SELECT id, units FROM Stock WHERE blood_group=?
                ORDER BY donation_date ASC
            """, (blood_group,))
            batches = cur.fetchall()
            for batch in batches:
                if remaining <= 0:
                    break
                if batch["units"] <= remaining:
                    remaining -= batch["units"]
                    cur.execute("DELETE FROM Stock WHERE id=?", (batch["id"],))
                else:
                    cur.execute(
                        "UPDATE Stock SET units = units - ? WHERE id=?",
                        (remaining, batch["id"])
                    )
                    remaining = 0
            status = "Approved"
        else:
            status = "Rejected"

        cur.execute("""
            INSERT INTO Requests(hospital, blood_group, units, status)
            VALUES(?,?,?,?)
        """, (hospital, blood_group, units_needed, status))

        conn.commit()
        return status
    except Exception as e:
        conn.rollback()
        return "Rejected"
    finally:
        conn.close()


def sp_purge_expired_stock():
    """
    SP: PurgeExpiredStock
    Removes all expired batches. Trigger trg_after_stock_delete
    fires automatically for each deleted row and logs it.
    """
    today = str(date.today())
    conn  = get_db()
    cur   = conn.cursor()
    cur.execute("DELETE FROM Stock WHERE expiry_date < ?", (today,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


# ─────────────────────────────────────────────
#  DBMS INFO PAGE — shows all DB objects
# ─────────────────────────────────────────────

@app.route("/dbms")
def dbms_info():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur  = conn.cursor()

    # Fetch all indexes
    cur.execute("""
        SELECT name, tbl_name, sql
        FROM sqlite_master
        WHERE type='index' AND name NOT LIKE 'sqlite_%'
        ORDER BY tbl_name
    """)
    indexes = cur.fetchall()

    # Fetch all triggers
    cur.execute("""
        SELECT name, tbl_name, sql
        FROM sqlite_master
        WHERE type='trigger'
        ORDER BY name
    """)
    triggers = cur.fetchall()

    # Fetch all views
    cur.execute("""
        SELECT name, sql
        FROM sqlite_master
        WHERE type='view'
        ORDER BY name
    """)
    views = cur.fetchall()

    # Fetch all tables with row counts
    cur.execute("""
        SELECT name FROM sqlite_master WHERE type='table'
        AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    tables_raw = cur.fetchall()
    tables = []
    for t in tables_raw:
        cur.execute(f"SELECT COUNT(*) FROM [{t['name']}]")
        count = cur.fetchone()[0]
        tables.append({"name": t["name"], "rows": count})

    # Data from views
    cur.execute("SELECT * FROM vw_BloodSummary")
    blood_summary = cur.fetchall()

    cur.execute("SELECT * FROM vw_RequestSummary")
    request_summary = cur.fetchall()

    cur.execute("SELECT * FROM vw_StockStatus LIMIT 20")
    stock_view = cur.fetchall()

    # Audit log
    cur.execute("SELECT * FROM AuditLog ORDER BY id DESC LIMIT 50")
    audit_logs = cur.fetchall()

    conn.close()

    return render_template("dbms_info.html",
                           indexes=indexes,
                           triggers=triggers,
                           views=views,
                           tables=tables,
                           blood_summary=blood_summary,
                           request_summary=request_summary,
                           stock_view=stock_view,
                           audit_logs=audit_logs)


# ─────────────────────────────────────────────
#  AUDIT LOG PAGE (standalone)
# ─────────────────────────────────────────────

@app.route("/audit")
def audit():
    if "user" not in session:
        return redirect("/login")
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM AuditLog ORDER BY id DESC")
    logs = cur.fetchall()
    conn.close()
    return render_template("audit.html", logs=logs)

if __name__ == "__main__":
    app.run(debug=True)
