from flask import Flask, render_template, request, redirect, session, url_for, send_file, jsonify
import sqlite3
import razorpay
import os
from datetime import date, datetime
from gtts import gTTS
import io
import random
import string

app = Flask(__name__)
app.secret_key = "akshaya_secret"

# Razorpay Configuration
RAZORPAY_KEY_ID = 'rzp_test_ZMGzPbvu5L6Y8v'
RAZORPAY_KEY_SECRET = 'CcHnHJcgxJd4LE10jCrAWx5x'
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))



def get_db():
    db_path = os.path.join(os.path.dirname(__file__), "akshaya.db")
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

@app.template_filter('format_time_12h')
def format_time_12h(t):
    if not t: return "-"
    from datetime import timedelta, datetime
    if isinstance(t, timedelta):
        total_seconds = int(t.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        period = "AM" if hours < 12 else "PM"
        if hours > 12: hours -= 12
        elif hours == 0: hours = 12
        return f"{hours:02d}:{minutes:02d} {period}"
    if isinstance(t, str):
        try:
            return datetime.strptime(t, "%H:%M:%S").strftime("%I:%M %p")
        except: return t
    return str(t)

@app.template_filter('format_date')
def format_date(d):
    if not d: return "-"
    from datetime import datetime
    if isinstance(d, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(d, fmt).strftime("%d %b %Y")
            except ValueError:
                continue
        return d
    return d.strftime("%d %b %Y")

@app.template_filter('format_datetime')
def format_datetime(d):
    if not d: return "-"
    from datetime import datetime
    if isinstance(d, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S"):
            try:
                return datetime.strptime(d, fmt).strftime("%b %d, %Y %I:%M %p")
            except ValueError:
                continue
        return d
    return d.strftime("%b %d, %Y %I:%M %p")

# ─────────────────────────────────────────────
#  CONTEXT PROCESSORS
# ─────────────────────────────────────────────
@app.context_processor
def inject_manager_info():
    if session.get("role") == "manager":
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name, profile_picture FROM Login WHERE Login_id=?", (session.get("user_id"),))
        user = cursor.fetchone()
        
        centre_name = "Unknown Centre"
        if session.get("centre_id"):
            cursor.execute("SELECT Center_name FROM Akshaya_centers WHERE centre_id=?", (session.get("centre_id"),))
            centre = cursor.fetchone()
            if centre: centre_name = centre[0]
            
        db.close()
        if user:
            pic_path = user[1]
            # Handle cases where the path might already contain 'uploads/'
            if pic_path and pic_path.startswith('uploads/'):
                pic_path = pic_path[8:] # Strip 'uploads/'
                
            return {
                'm_name': user[0],
                'm_pic': pic_path,
                'c_name_branded': centre_name
            }
    return {}

# ─────────────────────────────────────────────
#  ADMIN / STAFF LOGIN
# ─────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form["email"]
        password = request.form["password"]
        
        if len(password) != 8:
            return render_template("login.html", error="Invalid Credentials")
            
        db     = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM Login WHERE email=? AND Password=?", (email, password))
        user = cursor.fetchone()
        
        if user:
            session["user_id"]   = user[0] # This is Login_id
            session["user_name"] = user[1]
            session["role"]      = user[4]
            session["centre_id"] = user[5] if len(user) > 5 else None
            
            if user[4] == "admin":
                db.close()
                return redirect("/admin")
            elif user[4] == "manager":
                db.close()
                return redirect("/manager")
            else:
                # Register Attendance for Staff
                today = str(date.today())
                now_time = datetime.now().strftime("%H:%M:%S")
                try:
                    cursor.execute("INSERT OR IGNORE INTO Attendance (Login_id, centre_id, date, login_time) VALUES (?, ?, ?, ?)",
                                   (user[0], user[5], today, now_time))
                    db.commit()
                except:
                    pass
                db.close()
                return redirect("/staff")
        db.close()
        return render_template("login.html", error="Invalid Credentials")
    return render_template("login.html")

@app.route("/manager_register", methods=["GET", "POST"])
def manager_register():
    db = get_db()
    cursor = db.cursor()

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]
        contact = request.form["Contact_number"]
        address = request.form.get("address", "")
        
        import os
        import time
        profile_pic_filename = None
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename != '':
                filename = f"manager_{int(time.time())}_{file.filename}"
                upload_dir = os.path.join(app.root_path, 'static', 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                file.save(os.path.join(upload_dir, filename))
                profile_pic_filename = f"uploads/{filename}"
                
        err = None
        
        # 0. Passwords match and length is exactly 8
        if password != confirm_password:
            err = "Passwords do not match!"
        elif len(password) != 8:
            err = "Password must be exactly 8 characters!"
        
        # 0.1 Mobile Number format
        if not err and (not contact.isdigit() or len(contact) != 10):
            err = "Mobile number must be exactly 10 digits!"
        
        # 1. Existing email
        if not err:
            cursor.execute("SELECT Login_id FROM Login WHERE email=?", (email,))
            if cursor.fetchone(): err = "This Email ID is already registered!"
            
        # 2. Check active pending/approved requests
        if not err:
            cursor.execute("SELECT email FROM Manager WHERE status IN ('Pending', 'Approved') AND email=?", (email,))
            req_exists = cursor.fetchone()
            if req_exists:
                err = "This Email ID is already under pending/approved requests!"
                
        if err:
            db.close()
            return render_template("manager_register.html", error=err, form_data=request.form)
            
        cursor.execute("INSERT INTO Manager (manager_name, email, password, Contact_number, request_type, profile_picture, address) VALUES (?, ?, ?, ?, 'Registration', ?, ?)",
                       (name, email, password, contact, profile_pic_filename, address))
        db.commit()
        db.close()
        return render_template("manager_register.html", success=True)
        
    db.close()
    return render_template("manager_register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ─────────────────────────────────────────────
@app.route("/citizen")
def citizen_home():
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT centre_id, Center_name, district, Contact_number, latitude, longitude FROM Akshaya_centers")
    centres = cursor.fetchall()
    db.close()
    return render_template("citizen_dashboard.html", centres=centres)

@app.route("/citizen/reviews/<int:centre_id>", methods=["GET"])
def citizen_Reviews(centre_id):
    db     = get_db()
    cursor = db.cursor()
    
    # GET method
    cursor.execute("SELECT Center_name FROM Akshaya_centers WHERE centre_id=?", (centre_id,))
    centre = cursor.fetchone()
    
    cursor.execute("""
        SELECT user_name, rating, review, Created_at 
        FROM Tokens 
        WHERE centre_id=? AND rating IS NOT NULL AND status='Completed' 
        ORDER BY token_id DESC
    """, (centre_id,))
    reviews_list = cursor.fetchall()
    
    # Calculate for bar chart
    ratings_count = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    total_Reviews = len(reviews_list)
    for r in reviews_list:
        if r[1] in ratings_count:
            ratings_count[r[1]] += 1
            
    avg_rating = 0
    if total_Reviews > 0:
        avg_rating = sum(r[1] for r in reviews_list) / total_Reviews
        
    # Create percentage map for the bar chart
    percentages = {}
    for stars, count in ratings_count.items():
        percentages[stars] = (count / total_Reviews * 100) if total_Reviews > 0 else 0
        
    db.close()
    return render_template("centre_reviews.html", centre=centre, centre_id=centre_id, reviews=reviews_list, 
                           ratings_count=ratings_count, percentages=percentages, total_reviews=total_Reviews, avg_rating=round(avg_rating, 1))

@app.route("/api/ivr/Services/<int:centre_id>")
def api_ivr_Services(centre_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT service_id, service_name, service_fee FROM Services WHERE centre_id = ?", (centre_id,))
    Services = cursor.fetchall()
    db.close()
    return {"Services": [{"id": s[0], "name": s[1], "fee": s[2]} for s in Services]}

@app.route("/api/ivr/book", methods=["POST"])
def api_ivr_book():
    try:
        data = request.get_json()
        print(f"DEBUG: Received IVR Booking Request: {data}")
        name = data.get("name", "IVR User")
        mobile = data.get("mobile", "0000000000")
        centre_id = data.get("centre_id")
        service_id = data.get("service_id")
        
        db = get_db()
        cursor = db.cursor()
        
        # We record it as a Service Request first, as it's coming from an unauthenticated voice call
        cursor.execute("""
            INSERT INTO Service_requests (citizen_name, mobile_number, centre_id, service_id, status)
            VALUES (?, ?, ?, ?, 'IVR_Pending')
        """, (name, mobile, centre_id, service_id))
        db.commit()
        request_id = cursor.lastrowid
        
        db.close()
        return jsonify({"status": "success", "message": "IVR Service Request Recorded", "request_id": request_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# ─────────────────────────────────────────────
#  REAL IVR (TWILIO TwiML) ENDPOINTS
# ─────────────────────────────────────────────

@app.route("/ivr/welcome", methods=['POST', 'GET'])
def ivr_welcome():
    response = '<?xml version="1.0" encoding="UTF-8"?><Response>'
    response += '<Gather action="/ivr/menu" numDigits="1">'
    response += '<Say voice="polly.Aditi">Welcome to Akshaya Centre Automation System. </Say>'
    response += '<Say voice="polly.Aditi">Press 1 for English. </Say>'
    response += '<Say voice="polly.Aditi">Malayalathinnayi onnu amarthuka. </Say>'
    response += '</Gather>'
    response += '<Say>No input received. Goodbye.</Say>'
    response += '</Response>'
    return response, 200, {'Content-Type': 'text/xml'}

@app.route("/ivr/menu", methods=['POST', 'GET'])
def ivr_menu():
    digit = request.values.get('Digits')
    response = '<?xml version="1.0" encoding="UTF-8"?><Response>'
    
    if digit == '1': # English/Malayalam (Simplified for demo)
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT centre_id, Center_name FROM Akshaya_centers LIMIT 5")
        centres = cursor.fetchall()
        db.close()
        
        response += '<Gather action="/ivr/center" numDigits="1">'
        response += '<Say>Please select your Akshaya Centre. </Say>'
        for i, c in enumerate(centres):
            response += f'<Say>Press {i+1} for {c[1]}. </Say>'
        response += '</Gather>'
    else:
        response += '<Say>Invalid selection. Goodbye.</Say><Hangup/>'
        
    response += '</Response>'
    return response, 200, {'Content-Type': 'text/xml'}

@app.route("/ivr/center", methods=['POST', 'GET'])
def ivr_center():
    digit = request.values.get('Digits')
    # Fetch center from previously stored session or digit
    # For demo, mapping digit to center
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT centre_id, Center_name FROM Akshaya_centers")
    centres = cursor.fetchall()
    
    response = '<?xml version="1.0" encoding="UTF-8"?><Response>'
    
    try:
        idx = int(digit) - 1
        if 0 <= idx < len(centres):
            c_id = centres[idx][0]
            c_name = centres[idx][1]
            cursor.execute("SELECT service_id, service_name FROM Services WHERE centre_id = ? LIMIT 5", (c_id,))
            services = cursor.fetchall()
            db.close()
            
            response += f'<Gather action="/ivr/book_confirm?centre_id={c_id}" numDigits="1">'
            response += f'<Say>You selected {c_name}. Please select a service. </Say>'
            for i, s in enumerate(services):
                response += f'<Say>Press {i+1} for {s[1]}. </Say>'
            response += '</Gather>'
        else:
            db.close()
            response += '<Say>Invalid selection. </Say><Redirect>/ivr/menu</Redirect>'
    except:
        db.close()
        response += '<Say>An error occurred. </Say><Redirect>/ivr/menu</Redirect>'
        
    response += '</Response>'
    return response, 200, {'Content-Type': 'text/xml'}

@app.route("/ivr/book_confirm", methods=['POST', 'GET'])
def ivr_book_confirm():
    digit = request.values.get('Digits')
    centre_id = request.args.get('centre_id')
    mobile = request.values.get('From', 'Unknown')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT service_id, service_name FROM Services WHERE centre_id = ? LIMIT 5", (centre_id,))
    services = cursor.fetchall()
    
    response = '<?xml version="1.0" encoding="UTF-8"?><Response>'
    
    try:
        idx = int(digit) - 1
        if 0 <= idx < len(services):
            s_id = services[idx][0]
            s_name = services[idx][1]
            
            # Record booking
            today = str(date.today())
            now_time = datetime.now().strftime("%H:%M:%S")
            cursor.execute("""
                INSERT INTO Tokens (user_name, mobile_number, centre_id, service_id, booking_date, booking_time, status, remarks)
                VALUES ('IVR Citizen', ?, ?, ?, ?, ?, 'Pending', '🎙️ Real IVR Call')
            """, (mobile, centre_id, s_id, today, now_time))
            db.commit()
            
            response += f'<Say>Thank you. Your token for {s_name} has been booked. You will receive an SMS confirmation soon. Goodbye.</Say><Hangup/>'
        else:
            response += '<Say>Invalid service selection. </Say><Redirect>/ivr/menu</Redirect>'
    except Exception as e:
        response += f'<Say>Booking failed. {str(e)} </Say><Hangup/>'
    
    db.close()
    response += '</Response>'
    return response, 200, {'Content-Type': 'text/xml'}

# ─────────────────────────────────────────────
#  ANDROID APP APIS
# ─────────────────────────────────────────────
from flask import jsonify

@app.route("/api/android/get_centres", methods=["GET"])
def android_get_centres():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT centre_id, Center_name, district, Contact_number FROM Akshaya_centers")
    centres = cursor.fetchall()
    db.close()
    return jsonify({"status": "success", "centres": [{"id": c[0], "name": c[1], "location": c[2], "phone": c[3]} for c in centres]})

@app.route("/api/android/get_Services/<int:centre_id>", methods=["GET"])
def android_get_Services(centre_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT service_id, service_name, service_fee, description FROM Services WHERE centre_id = ?", (centre_id,))
    Services = cursor.fetchall()
    db.close()
    return jsonify({"status": "success", "Services": [{"id": s[0], "name": s[1], "fee": s[2], "desc": s[3]} for s in Services]})

@app.route("/api/android/book_token", methods=["POST"])
def android_book_token():
    try:
        data = request.get_json()
        user_name = data.get("user_name")
        mobile_number = data.get("mobile_number")
        centre_id = data.get("centre_id")
        service_id = data.get("service_id")
        
        if not mobile_number or not mobile_number.isdigit() or len(mobile_number) != 10:
            return jsonify({"status": "error", "message": "Mobile number must be exactly 10 digits"}), 400
            
        db = get_db()
        cursor = db.cursor()
        today = str(date.today())
        now_time = datetime.now().strftime("%H:%M:%S")

        # Create Tokens
        cursor.execute("""
            INSERT INTO Tokens (token_number, user_name, mobile_number, centre_id, service_id, booking_date, booking_time, status)
            VALUES (NULL, ?, ?, ?, ?, ?, ?, 'Pending')
        """, (user_name, mobile_number, centre_id, service_id, today, now_time))
        db.commit()
        token_id = cursor.lastrowid
        
        # Create Applications number
        import random, string
        app_number = "AKS" + str(today.year) + ''.join(random.choices(string.digits, k=5))
        cursor.execute(
            "INSERT INTO Applications (application_number, token_id, status) VALUES (?, ?, 'Pending')",
            (app_number, token_id)
        )
        db.commit()
        db.close()
        
        return jsonify({
            "status": "success", 
            "message": "Token booked successfully", 
            "token_id": token_id, 
            "application_number": app_number
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/citizen/services/<int:centre_id>")
def citizen_Services(centre_id):
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT service_id, service_name, service_fee, description FROM Services WHERE centre_id=?", (centre_id,))
    services = cursor.fetchall()
    cursor.execute("SELECT centre_id, Center_name, district, Contact_number FROM Akshaya_centers WHERE centre_id=?", (centre_id,))
    centre = cursor.fetchone()
    db.close()
    return render_template("select_service.html", services=services, centre=centre)

@app.route("/citizen/ivr")
def ivr_simulation():
    db = get_db()
    cursor = db.cursor()
    
    # Priority: 1. Query Params (for guests), 2. Session (for logged in), 3. Defaults
    user_name = request.args.get("name")
    user_phone = request.args.get("phone")
    
    if not user_name or not user_phone:
        if session.get("user_id"):
            cursor.execute("SELECT name, phone_number FROM Login WHERE Login_id = ?", (session.get("user_id"),))
            user = cursor.fetchone()
            if user:
                user_name = user_name or user[0]
                user_phone = user_phone or user[1]
    
    user_name = user_name or "IVR Guest"
    user_phone = user_phone or "0000000000"
    
    # Fetch Akshaya_centers for initial selection
    cursor.execute("SELECT centre_id, Center_name FROM Akshaya_centers")
    centres = cursor.fetchall()
    db.close()
    return render_template("ivr_simulation.html", centres=centres, user_name=user_name, user_phone=user_phone)

@app.route("/citizen/documents/<int:service_id>")
def view_documents(service_id):
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT service_name FROM Services WHERE service_id=?", (service_id,))
    s_res = cursor.fetchone()
    service_name = s_res[0] if s_res else "Unknown Service"
    
    cursor.execute("SELECT * FROM Documents WHERE service_id=?", (service_id,))
    docs = cursor.fetchall()
    db.close()
    return render_template("view_documents.html", service_name=service_name, docs=docs)

@app.route("/citizen/book/<int:service_id>", methods=["GET", "POST"])
def book_token(service_id):
    db     = get_db()
    cursor = db.cursor()

    if request.method == "POST":
        user_name     = request.form["user_name"]
        mobile_number = request.form["mobile_number"]
        centre_id     = request.form["centre_id"]
        today         = str(date.today())
        now_time      = datetime.now().strftime("%H:%M:%S")

        if not mobile_number.isdigit() or len(mobile_number) != 10:
            cursor.execute("SELECT service_id, service_name, service_fee, description FROM Services WHERE service_id=?", (service_id,))
            service = cursor.fetchone()
            cursor.execute("SELECT centre_id, Center_name, district, Contact_number FROM Akshaya_centers WHERE centre_id=?", (centre_id,))
            centre = cursor.fetchone()
            cursor.execute("SELECT document_name, is_mandatory FROM Documents WHERE service_id=?", (service_id,))
            docs = cursor.fetchall()
            db.close()
            return render_template("book_token.html", error="Mobile number must be exactly 10 digits!", service=service, centre=centre, docs=docs)

        # Initial request: no Tokens number yet, status is 'Pending'
        cursor.execute("""
            INSERT INTO Tokens (token_number, user_name, mobile_number, centre_id, service_id, booking_date, booking_time, status)
            VALUES (NULL, ?, ?, ?, ?, ?, ?, 'Pending')
        """, (user_name, mobile_number, centre_id, service_id, today, now_time))
        db.commit()
        token_id = cursor.lastrowid
        db.close()
        return render_template("token_confirmation.html", pending=True)

    # GET – show booking form
    cursor.execute("SELECT service_id, service_name, service_fee, description FROM Services WHERE service_id=?", (service_id,))
    service = cursor.fetchone()
    centre_id = request.args.get("centre_id", 1)
    cursor.execute("SELECT centre_id, Center_name, district, Contact_number FROM Akshaya_centers WHERE centre_id=?", (centre_id,))
    centre = cursor.fetchone()
    cursor.execute("SELECT document_name, is_mandatory FROM Documents WHERE service_id=?", (service_id,))
    docs = cursor.fetchall()
    db.close()
    return render_template("book_token.html", service=service, centre=centre, docs=docs)

# NOTE: approve_time and reject_time routes are defined below (lines ~706+)
# with smarter IVR-aware logic. Dummy stubs removed to avoid Flask duplicate route error.

@app.route("/citizen/payment/<int:token_id>")
def citizen_payment(token_id):
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT t.token_number, s.service_name, s.service_fee, c.Center_name, t.user_name, t.status
        FROM Tokens t
        JOIN Services s ON t.service_id = s.service_id
        JOIN Akshaya_centers  c ON t.centre_id  = c.centre_id
        WHERE t.token_id = ?
    """, (token_id,))
    token = cursor.fetchone()
    db.close()
    if not token:
        return "Tokens not found"
    if token[5] == 'Booked':
        return "Already Paid and Booked"
    return render_template("pay_service.html", token=token, token_id=token_id)

@app.route("/citizen/initiate_payment/<int:token_id>", methods=["POST"])
def initiate_payment(token_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT s.service_fee, s.service_name, t.user_name, t.mobile_number
        FROM Tokens t
        JOIN Services s ON t.service_id = s.service_id
        WHERE t.token_id = ?
    """, (token_id,))
    data = cursor.fetchone()
    db.close()

    if not data:
        return "Tokens data not found."

    amount = int(float(data[0]))
    amount_paise = amount * 100
    
    # Instead of Razorpay, redirect to our premium internal simulator
    return redirect(f"/citizen/payment/internal/{token_id}")

@app.route("/citizen/payment/internal/<int:token_id>")
def pay_internal(token_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT s.service_fee, s.service_name, t.user_name, t.mobile_number
        FROM Tokens t
        JOIN Services s ON t.service_id = s.service_id
        WHERE t.token_id = ?
    """, (token_id,))
    data = cursor.fetchone()
    db.close()
    if not data: return "Data not found"
    return render_template("pay_internal.html", token_id=token_id, data=data)

@app.route("/citizen/payment/process/<int:token_id>", methods=["POST"])
def pay_process(token_id):
    # This route just shows the premium animation
    return render_template("pay_processing.html", token_id=token_id)

@app.route("/citizen/payment/complete/<int:token_id>", methods=["POST"])
def pay_complete(token_id):
    db = get_db()
    cursor = db.cursor()
    
    # 1. Get Token and Service Info
    cursor.execute("""
        SELECT s.service_fee, t.service_id, t.centre_id, t.booking_date, t.user_name, t.mobile_number
        FROM Tokens t 
        JOIN Services s ON t.service_id = s.service_id 
        WHERE t.token_id = ?
    """, (token_id,))
    t_info = cursor.fetchone()
    if not t_info:
        db.close()
        return "Transaction Error: Token not found."
        
    amount, service_id, centre_id, b_date, u_name, u_mobile = t_info
    payment_id = "MOCK_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))

    # 2. Insert record into Payments table
    cursor.execute("""
        INSERT INTO Payments (token_id, service_id, amount, payment_status, transaction_id, payment_date)
        VALUES (?, ?, ?, 'Paid', ?, ?)
    """, (token_id, service_id, amount, payment_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    # 3. Assign Tokens Number
    cursor.execute(
        "SELECT COUNT(*) FROM Tokens WHERE centre_id=? AND booking_date=? AND token_number IS NOT NULL",
        (centre_id, b_date)
    )
    count = cursor.fetchone()[0]
    token_number = count + 1
    
    # 4. Generate Application Number
    app_number = "AKS" + str(datetime.now().year) + ''.join(random.choices(string.digits, k=5))
    cursor.execute(
        "INSERT INTO Applications (application_number, token_id, status) VALUES (?, ?, 'Paid')",
        (app_number, token_id)
    )

    # 5. Update Token Status
    cursor.execute("UPDATE Tokens SET token_number=?, status='Paid' WHERE token_id=?", (token_number, token_id))
    db.commit()
    
    # Fetch data for confirmation
    cursor.execute("""
        SELECT t.token_number, s.service_name, s.service_fee, c.Center_name, c.Contact_number,
               t.booking_date, t.booking_time, t.status, t.user_name, t.mobile_number, a.application_number, t.scheduled_time,
               u.name as Staff_name
        FROM Tokens t
        JOIN Services s ON t.service_id = s.service_id
        JOIN Akshaya_centers  c ON t.centre_id  = c.centre_id
        JOIN Applications a ON a.token_id = t.token_id
        LEFT JOIN Login u ON t.scheduled_by = u.Login_id
        WHERE t.token_id = ?
    """, (token_id,))
    token_info = cursor.fetchone()
    db.close()

    sms_msg = f"Dear {token_info[8]}, your payment is successful. Token #{token_info[0]} confirmed at {token_info[3]} - Akshaya"
    return render_template("token_confirmation.html", token=token_info, paid=True, txn_id=payment_id, sms_msg=sms_msg)

@app.route("/citizen/payment_callback/<int:token_id>", methods=["POST"])
def payment_callback(token_id):
    # Retrieve Razorpay Payments details
    payment_id = request.form.get('razorpay_payment_id')
    order_id = request.form.get('razorpay_order_id')
    signature = request.form.get('razorpay_signature')

    params_dict = {
        'razorpay_order_id': order_id,
        'razorpay_payment_id': payment_id,
        'razorpay_signature': signature
    }

    try:
        # Verify the signature
        razorpay_client.utility.verify_payment_signature(params_dict)
        
        db = get_db()
        cursor = db.cursor()
        
        # Get payment amount and Tokens info
        cursor.execute("""
            SELECT s.service_fee, t.service_id, t.centre_id, t.booking_date, t.user_name, t.mobile_number
            FROM Tokens t 
            JOIN Services s ON t.service_id = s.service_id 
            WHERE t.token_id = ?
        """, (token_id,))
        t_info = cursor.fetchone()
        if not t_info:
            db.close()
            return "Transaction Error: Token not found."
            
        amount, service_id, centre_id, b_date, u_name, u_mobile = t_info

        # 1. Insert record into Payments table (Fixed field names)
        cursor.execute("""
            INSERT INTO Payments (token_id, amount, payment_status, transaction_id, payment_date)
            VALUES (?, ?, 'Paid', ?, ?)
        """, (token_id, amount, payment_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        # 2. Assign Tokens Number
        cursor.execute(
            "SELECT COUNT(*) FROM Tokens WHERE centre_id=? AND booking_date=? AND token_number IS NOT NULL",
            (centre_id, b_date)
        )
        count = cursor.fetchone()[0]
        token_number = count + 1
        
        # 3. GENERATE APPLICATION NUMBER NOW
        import random, string
        app_number = "AKS" + str(datetime.now().year) + ''.join(random.choices(string.digits, k=5))
        cursor.execute(
            "INSERT INTO Applications (application_number, token_id, status) VALUES (?, ?, 'Paid')",
            (app_number, token_id)
        )

        # 4. Update Token Status
        cursor.execute("UPDATE Tokens SET token_number=?, status='Paid' WHERE token_id=?", (token_number, token_id))
        db.commit()
        
        # Fetch full info for confirmation (including Staff name)
        cursor.execute("""
            SELECT t.token_number, s.service_name, s.service_fee, c.Center_name, c.Contact_number,
                   t.booking_date, t.booking_time, t.status, t.user_name, t.mobile_number, a.application_number, t.scheduled_time,
                   u.name as Staff_name
            FROM Tokens t
            JOIN Services s ON t.service_id = s.service_id
            JOIN Akshaya_centers  c ON t.centre_id  = c.centre_id
            JOIN Applications a ON a.token_id = t.token_id
            LEFT JOIN Login u ON t.scheduled_by = u.Login_id
            WHERE t.token_id = ?
        """, (token_id,))
        token_info = cursor.fetchone()
        db.close()

        # Generate simulated SMS message
        sms_msg = f"Dear {token_info[8]}, your payment is successful. Token #{token_info[0]}, App No: {token_info[10]} at {token_info[3]} - Akshaya"
        
        return render_template("token_confirmation.html", token=token_info, paid=True, txn_id=payment_id, sms_msg=sms_msg)

    except Exception as e:
        return f"Payments Verification Failed: {str(e)}"

@app.route("/citizen/check_status", methods=["GET", "POST"])
def check_status():
    tokens_list = []
    searched = False
    mobile = None
    
    if request.method == "POST":
        mobile = request.form.get("mobile_number")
    elif request.args.get("mobile"):
        mobile = request.args.get("mobile")
        
    if mobile:
        db     = get_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT t.token_number, s.service_name, c.Center_name, t.status, 
                   t.booking_date, t.booking_time, t.scheduled_time, t.token_id,
                   s.service_fee,
                   (SELECT GROUP_CONCAT(document_name, ', ') FROM Documents WHERE service_id = s.service_id) as document_list,
                   u.name as staff_name, u.profile_picture as staff_pic,
                   t.rating, t.review
            FROM Tokens t
            JOIN Services s ON t.service_id = s.service_id
            JOIN Akshaya_centers  c ON t.centre_id  = c.centre_id
            LEFT JOIN Login u ON t.scheduled_by = u.Login_id
            WHERE t.mobile_number = ?
            ORDER BY t.token_id DESC LIMIT 15
        """, (mobile,))
        tokens_list = cursor.fetchall()
        db.close()
        searched = True
    return render_template("check_status.html", tokens=tokens_list, searched=searched)

@app.route("/citizen/approve_time/<int:token_id>")
def approve_time(token_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT status, mobile_number FROM Tokens WHERE token_id=?", (token_id,))
    row = cursor.fetchone()
    current_status = row[0] if row else None
    mobile = row[1] if row else None
    
    if current_status == 'IVR_Scheduled':
        cursor.execute("UPDATE Tokens SET status='IVR_Confirmed' WHERE token_id=?", (token_id,))
    else:
        cursor.execute("UPDATE Tokens SET status='TimeApproved' WHERE token_id=?", (token_id,))
        
    db.commit()
    db.close()
    if mobile:
        return redirect(f"/citizen/check_status?mobile={mobile}")
    return redirect("/citizen/check_status")

@app.route("/citizen/reject_time/<int:token_id>")
def reject_time(token_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT mobile_number FROM Tokens WHERE token_id=?", (token_id,))
    row = cursor.fetchone()
    mobile = row[0] if row else None
    cursor.execute("UPDATE Tokens SET status='Cancelled' WHERE token_id=?", (token_id,))
    db.commit()
    db.close()
    if mobile:
        return redirect(f"/citizen/check_status?mobile={mobile}")
    return redirect("/citizen/check_status")

@app.route("/citizen/add_review/<int:token_id>", methods=["POST"])
def citizen_add_review(token_id):
    rating = request.form.get("rating")
    review = request.form.get("review")
    db     = get_db()
    cursor = db.cursor()
    
    cursor.execute("SELECT mobile_number FROM Tokens WHERE token_id=?", (token_id,))
    row = cursor.fetchone()
    mobile = row[0] if row else None
    
    cursor.execute("UPDATE Tokens SET rating=?, review=? WHERE token_id=?", (rating, review, token_id))
    db.commit()
    db.close()
    from flask import flash
    flash("Review submitted successfully!", "success")
    if mobile:
        return redirect(f"/citizen/check_status?mobile={mobile}")
    return redirect("/citizen/check_status")

# ─────────────────────────────────────────────
#  ADMIN
# ─────────────────────────────────────────────
@app.route("/admin")
def admin_dashboard():
    if session.get("role") != "admin":
        return redirect("/")
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM Akshaya_centers")
    total_centres = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM Services")
    total_Services = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM Tokens WHERE booking_date=?", (str(date.today()),))
    today_Tokens = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM Tokens WHERE status='Completed' AND booking_date=?", (str(date.today()),))
    completed = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM Service_requests WHERE status='IVR_Pending'")
    pending_service_requests = cursor.fetchone()[0]
    
    db.close()
    return render_template("admin_dashboard.html",
                           total_centres=total_centres,
                           total_Services=total_Services,
                           today_tokens=today_Tokens,
                           completed=completed,
                           pending_service_requests=pending_service_requests)

@app.route("/add_centre", methods=["GET", "POST"])
def add_centre():
    if session.get("role") != "admin":
        return redirect("/")
    db     = get_db()
    cursor = db.cursor()
    if request.method == "POST":
        Center_name    = request.form["Center_name"]
        street_name    = request.form["street_name"]
        building_no    = request.form["building_no"]
        place          = request.form["location_or_place"]
        district       = request.form["district"]
        email_id       = request.form["email_id"]
        Contact_number = request.form["Contact_number"]
        latitude       = request.form.get("latitude")
        longitude      = request.form.get("longitude")
        
        if not Contact_number.isdigit() or len(Contact_number) != 10:
            cursor.execute("SELECT Center_name, latitude, longitude FROM Akshaya_centers WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND latitude != ''")
            db_centres = cursor.fetchall()
            existing_centres = []
            for row in db_centres:
                try:
                    existing_centres.append({
                        "name": row[0],
                        "lat": float(row[1]),
                        "lng": float(row[2])
                    })
                except:
                    pass
            db.close()
            return render_template("add_centre.html", existing_centres=existing_centres, error="Contact number must be exactly 10 digits!")

        cursor.execute("""
            INSERT INTO Akshaya_centers (Center_name, street_name, building_no, location, district, email_id, Contact_number, latitude, longitude) 
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (Center_name, street_name, building_no, place, district, email_id, Contact_number, latitude, longitude))
        db.commit()
        db.close()
        return redirect("/view_centres")
    cursor.execute("SELECT Center_name, latitude, longitude FROM Akshaya_centers WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND latitude != ''")
    db_centres = cursor.fetchall()
    existing_centres = []
    for row in db_centres:
        try:
            existing_centres.append({
                "name": row[0],
                "lat": float(row[1]),
                "lng": float(row[2])
            })
        except:
            pass
    db.close()
    return render_template("add_centre.html", existing_centres=existing_centres)

@app.route("/view_centres")
def view_centres():
    if session.get("role") != "admin":
        return redirect("/")
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT centre_id, Center_name, district, Contact_number FROM Akshaya_centers")
    centres = cursor.fetchall()
    db.close()
    return render_template("view_centres.html", centres=centres)

@app.route("/add_service", methods=["GET", "POST"])
def add_service():
    if session.get("role") != "admin":
        return redirect("/")
    db     = get_db()
    cursor = db.cursor()
    if request.method == "POST":
        service_name = request.form["service_name"]
        service_fee  = request.form["service_fee"]
        description  = request.form.get("description", "")
        doc_desc     = request.form.get("document_description", "")
        centre_id    = request.form["centre_id"]
        Documents_list = request.form.get("Documents", "")

        cursor.execute(
            "INSERT INTO Services (centre_id, service_name, service_fee, description, document_description) VALUES (?,?,?,?,?)",
            (centre_id, service_name, service_fee, description, doc_desc)
        )
        db.commit()
        service_id = cursor.lastrowid

        for doc in [d.strip() for d in Documents_list.split(",") if d.strip()]:
            cursor.execute("INSERT INTO Documents (service_id, document_name, is_mandatory) VALUES (?,?,1)", (service_id, doc))
        db.commit()
        db.close()
        return redirect("/view_Services")

    cursor.execute("SELECT centre_id, Center_name FROM Akshaya_centers")
    centres = cursor.fetchall()
    db.close()
    return render_template("add_service.html", centres=centres)

@app.route("/view_services")
def view_Services():
    if session.get("role") != "admin":
        return redirect("/")
    db     = get_db()
    cursor = db.cursor()
    centre_id = request.args.get('centre_id')
    if centre_id:
        cursor.execute("""
            SELECT s.service_id, s.service_name, s.service_fee, s.description, c.Center_name
            FROM Services s JOIN Akshaya_centers c ON s.centre_id = c.centre_id
            WHERE s.centre_id = ?
            ORDER BY s.service_name
        """, (centre_id,))
    else:
        cursor.execute("""
            SELECT s.service_id, s.service_name, s.service_fee, s.description, c.Center_name
            FROM Services s JOIN Akshaya_centers c ON s.centre_id = c.centre_id
            ORDER BY c.Center_name, s.service_name
        """)
    Services_list = cursor.fetchall()
    
    cursor.execute("SELECT centre_id, Center_name FROM Akshaya_centers")
    centres = cursor.fetchall()
    db.close()
    return render_template("view_services.html", Services=Services_list, centres=centres, selected_centre=centre_id)

@app.route("/admin/all_tokens")
def admin_all_Tokens():
    if session.get("role") != "admin":
        return redirect("/")
    db     = get_db()
    cursor = db.cursor()
    centre_id = request.args.get('centre_id')
    if centre_id:
        cursor.execute("""
            SELECT t.token_number, t.user_name, t.mobile_number, s.service_name, c.Center_name,
                   t.booking_date, t.booking_time, t.status
            FROM Tokens t
            JOIN Services s ON t.service_id = s.service_id
            JOIN Akshaya_centers  c ON t.centre_id  = c.centre_id
            WHERE t.centre_id = ?
            ORDER BY t.token_id DESC LIMIT 50
        """, (centre_id,))
    else:
        cursor.execute("""
            SELECT t.token_number, t.user_name, t.mobile_number, s.service_name, c.Center_name,
                   t.booking_date, t.booking_time, t.status
            FROM Tokens t
            JOIN Services s ON t.service_id = s.service_id
            JOIN Akshaya_centers  c ON t.centre_id  = c.centre_id
            ORDER BY t.token_id DESC LIMIT 50
        """)
    Tokens_list = cursor.fetchall()
    
    cursor.execute("SELECT centre_id, Center_name FROM Akshaya_centers")
    centres = cursor.fetchall()
    db.close()
    return render_template("admin_all_tokens.html", tokens=Tokens_list, centres=centres, selected_centre=centre_id)

@app.route("/admin/delete_all_tokens", methods=["POST"])
def admin_delete_all_tokens():
    if session.get("role") != "admin":
        return redirect("/")
    db = get_db()
    cursor = db.cursor()
    centre_id = request.form.get("centre_id")
    if centre_id:
        cursor.execute("DELETE FROM Payments WHERE token_id IN (SELECT token_id FROM Tokens WHERE centre_id = ?)", (centre_id,))
        cursor.execute("DELETE FROM Applications WHERE token_id IN (SELECT token_id FROM Tokens WHERE centre_id = ?)", (centre_id,))
        cursor.execute("DELETE FROM Tokens WHERE centre_id = ?", (centre_id,))
    else:
        cursor.execute("DELETE FROM Payments")
        cursor.execute("DELETE FROM Applications")
        cursor.execute("DELETE FROM Tokens")
    db.commit()
    db.close()
    return redirect(url_for("admin_all_Tokens", centre_id=centre_id))

@app.route("/admin/manager_requests", methods=["GET", "POST"])
def admin_manager_requests():
    if session.get("role") != "admin": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    view_type = request.args.get('view', 'both')
    
    if request.method == "POST":
        req_id = request.form["req_id"]
        action = request.form["action"]
        if action == "approve":
            cursor.execute("SELECT manager_name, email, password, Center_name, location, Contact_number, centre_id, request_type, profile_picture, address FROM Manager WHERE manager_id=?", (req_id,))
            req = cursor.fetchone()
            if req:
                if req[7] == 'Registration':
                    # Insert manager without centre
                    cursor.execute("INSERT INTO Login (name, email, Password, role, centre_id, phone_number, profile_picture, address) VALUES (?, ?, ?, 'manager', NULL, ?, ?, ?)",
                                   (req[0], req[1], req[2], req[5], req[8], req[9]))
                    cursor.execute("UPDATE Manager SET status='Approved' WHERE manager_id=?", (req_id,))
                elif req[7] == 'CentreRegistration':
                    # Add new centre
                    cursor.execute("INSERT INTO Akshaya_centers (Center_name, location, district, Contact_number) VALUES (?, ?, ?, ?)", (req[3], req[4], req[4], req[5]))
                    new_centre_id = cursor.lastrowid
                    # Update Manager record
                    cursor.execute("UPDATE Manager SET status='Approved', centre_id=? WHERE manager_id=?", (new_centre_id, req_id))
                    # Update Login record
                    cursor.execute("UPDATE Login SET centre_id=? WHERE email=? AND role='manager'", (new_centre_id, req[1]))
        elif action == "reject":
            cursor.execute("UPDATE Manager SET status='Rejected' WHERE manager_id=?", (req_id,))
        db.commit()
        db.close()
        return redirect(url_for("admin_manager_requests", view=view_type))
        
    if view_type == 'centre':
        cursor.execute("""
            SELECT m.manager_id, m.manager_name, m.email, 
                   COALESCE(NULLIF(m.Center_name, ''), NULLIF(c.Center_name, '')) as Center_name, 
                   COALESCE(NULLIF(m.location, ''), NULLIF(c.district, '')) as location, 
                   m.Contact_number, m.status, 
                   COALESCE(NULLIF(m.profile_picture, ''), NULLIF(l.profile_picture, '')) as profile_picture, 
                   COALESCE(NULLIF(m.address, ''), NULLIF(l.address, '')) as address 
            FROM Manager m
            LEFT JOIN Akshaya_centers c ON m.centre_id = c.centre_id
            LEFT JOIN Login l ON m.email = l.email AND l.role = 'manager'
            WHERE m.request_type='CentreRegistration'
            ORDER BY m.manager_id DESC
        """)
    elif view_type == 'manager':
        cursor.execute("""
            SELECT m.manager_id, m.manager_name, m.email, 
                   COALESCE(NULLIF(m.Center_name, ''), NULLIF(c.Center_name, '')) as Center_name, 
                   COALESCE(NULLIF(m.location, ''), NULLIF(c.district, '')) as location, 
                   m.Contact_number, m.status, 
                   COALESCE(NULLIF(m.profile_picture, ''), NULLIF(l.profile_picture, '')) as profile_picture, 
                   COALESCE(NULLIF(m.address, ''), NULLIF(l.address, '')) as address 
            FROM Manager m
            LEFT JOIN Akshaya_centers c ON m.centre_id = c.centre_id
            LEFT JOIN Login l ON m.email = l.email AND l.role = 'manager'
            WHERE m.request_type='Registration'
            ORDER BY m.manager_id DESC
        """)
    else:
        cursor.execute("""
            SELECT m.manager_id, m.manager_name, m.email, 
                   COALESCE(NULLIF(m.Center_name, ''), NULLIF(c.Center_name, '')) as Center_name, 
                   COALESCE(NULLIF(m.location, ''), NULLIF(c.district, '')) as location, 
                   m.Contact_number, m.status, 
                   COALESCE(NULLIF(m.profile_picture, ''), NULLIF(l.profile_picture, '')) as profile_picture, 
                   COALESCE(NULLIF(m.address, ''), NULLIF(l.address, '')) as address 
            FROM Manager m
            LEFT JOIN Akshaya_centers c ON m.centre_id = c.centre_id
            LEFT JOIN Login l ON m.email = l.email AND l.role = 'manager'
            WHERE m.request_type IN ('Registration', 'CentreRegistration')
            ORDER BY m.manager_id DESC
        """)
    requests_list = cursor.fetchall()
    db.close()
    return render_template("admin_manager_requests.html", requests=requests_list, view_type=view_type)


@app.route("/admin/add_manager", methods=["GET", "POST"])
def add_manager():
    if session.get("role") != "admin": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        centre_id = request.form["centre_id"]
        
        if len(password) != 8:
            cursor.execute("SELECT centre_id, Center_name FROM Akshaya_centers")
            centres = cursor.fetchall()
            db.close()
            return render_template("add_manager.html", centres=centres, error="Password must be exactly 8 characters!")
            
        cursor.execute("INSERT INTO Login (name, email, Password, role, centre_id) VALUES (?, ?, ?, 'manager', ?)",
                       (name, email, password, centre_id))
        db.commit()
        db.close()
        return redirect("/admin")
    cursor.execute("SELECT centre_id, Center_name FROM Akshaya_centers")
    centres = cursor.fetchall()
    db.close()
    return render_template("add_manager.html", centres=centres)

@app.route("/admin/delete_manager/<int:manager_id>", methods=["POST"])
def delete_manager(manager_id):
    if session.get("role") != "admin":
        return redirect("/")
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT email FROM Manager WHERE manager_id = ?", (manager_id,))
    row = cursor.fetchone()
    if row:
        email = row[0]
        cursor.execute("DELETE FROM Login WHERE email = ? AND role = 'manager'", (email,))
        cursor.execute("DELETE FROM Manager WHERE email = ?", (email,))
        db.commit()
    db.close()
    return redirect("/admin/manager_requests")

@app.route("/admin/delete_centre/<int:centre_id>", methods=["POST"])
def delete_centre(centre_id):
    if session.get("role") != "admin":
        return redirect("/")
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM Akshaya_centers WHERE centre_id = ?", (centre_id,))
    cursor.execute("DELETE FROM Login WHERE role = 'staff' AND centre_id = ?", (centre_id,))
    cursor.execute("UPDATE Login SET centre_id = NULL WHERE role = 'manager' AND centre_id = ?", (centre_id,))
    cursor.execute("DELETE FROM Staff WHERE centre_id = ?", (centre_id,))
    cursor.execute("DELETE FROM Services WHERE centre_id = ?", (centre_id,))
    cursor.execute("DELETE FROM Service_requests WHERE centre_id = ?", (centre_id,))
    cursor.execute("DELETE FROM Tokens WHERE centre_id = ?", (centre_id,))
    cursor.execute("DELETE FROM Attendance WHERE centre_id = ?", (centre_id,))
    cursor.execute("DELETE FROM Reviews WHERE centre_id = ?", (centre_id,))
    cursor.execute("UPDATE Manager SET centre_id = NULL WHERE centre_id = ?", (centre_id,))
    db.commit()
    db.close()
    return redirect("/view_centres")

@app.route("/admin/service_requests", methods=["GET", "POST"])
def admin_Service_requests():
    if session.get("role") != "admin": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    if request.method == "POST":
        req_id = request.form["req_id"]
        action = request.form["action"]
        if action == "approve":
            cursor.execute("SELECT centre_id, requested_service_name, requested_service_fee, requested_service_desc, requested_documents FROM Manager WHERE manager_id=? AND request_type='ServiceAddition'", (req_id,))
            req = cursor.fetchone()
            if req:
                # 1. Insert Service
                cursor.execute("INSERT INTO Services (centre_id, service_name, service_fee, description) VALUES (?, ?, ?, ?)",
                               (req[0], req[1], req[2], req[3]))
                service_id = cursor.lastrowid
                
                # 2. Insert Documents
                docs_raw = req[4]
                if docs_raw:
                    doc_list = [d.strip() for d in docs_raw.split(",") if d.strip()]
                    for d_name in doc_list:
                        cursor.execute("INSERT INTO Documents (service_id, document_name, is_mandatory) VALUES (?, ?, 1)", (service_id, d_name))
                
                cursor.execute("UPDATE Manager SET status='Approved' WHERE manager_id=?", (req_id,))
        elif action == "reject":
            cursor.execute("UPDATE Manager SET status='Rejected' WHERE manager_id=?", (req_id,))
        db.commit()
        db.close()
        return redirect("/admin/service_requests")
        
    cursor.execute('''
        SELECT m.manager_id, m.requested_service_name, m.requested_service_fee, m.requested_service_desc, c.Center_name, m.manager_name, m.status, m.requested_documents
        FROM Manager m 
        JOIN Akshaya_centers c ON m.centre_id = c.centre_id
        WHERE m.request_type = 'ServiceAddition'
        ORDER BY m.manager_id DESC
    ''')
    requests_list = cursor.fetchall()
    db.close()
    return render_template("admin_service_requests.html", requests=requests_list)

# ─────────────────────────────────────────────
#  MANAGER
# ─────────────────────────────────────────────
@app.route("/manager")
def manager_dashboard():
    if session.get("role") != "manager": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    centre_id = session.get("centre_id")
    
    if not centre_id:
        cursor.execute("SELECT Center_name, status FROM Manager WHERE email = (SELECT email FROM Login WHERE Login_id = ?) AND request_type='CentreRegistration'", (session.get("user_id"),))
        req = cursor.fetchone()
        
        cursor.execute("SELECT Center_name FROM Akshaya_centers")
        registered_centres = [row[0].strip().lower() for row in cursor.fetchall() if row[0]]
        cursor.execute("SELECT Center_name FROM Manager WHERE request_type='CentreRegistration' AND status='Pending'")
        pending_centres = [row[0].strip().lower() for row in cursor.fetchall() if row[0]]
        requested_centres = registered_centres + pending_centres
        
        if req:
            return render_template("manager_dashboard.html", request_mode=True, needs_request=False, Center_name=req[0], status=req[1], requested_centres=requested_centres)
        else:
            return render_template("manager_dashboard.html", request_mode=True, needs_request=True, requested_centres=requested_centres)

    cursor.execute("SELECT COUNT(*) FROM Login WHERE role='staff' AND centre_id=?", (centre_id,))
    total_Staff = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM Services WHERE centre_id=?", (centre_id,))
    total_Services = cursor.fetchone()[0]
    cursor.execute("SELECT Center_name FROM Akshaya_centers WHERE centre_id=?", (centre_id,))
    c_name = cursor.fetchone()
    Center_name = c_name[0] if c_name else "Unknown"
    db.close()
    return render_template("manager_dashboard.html", request_mode=False, total_Staff=total_Staff, total_Services=total_Services, Center_name=Center_name)

@app.route("/manager/request_centre", methods=["POST"])
def manager_request_centre():
    if session.get("role") != "manager": return redirect("/")
    
    c_name = request.form.get("Center_name")
    loc = request.form.get("location")
    contact = request.form.get("Contact_number")
    
    db = get_db()
    cursor = db.cursor()
    
    # Check if centre name already exists
    cursor.execute("SELECT centre_id FROM Akshaya_centers WHERE Center_name = ?", (c_name,))
    if cursor.fetchone():
        db.close()
        from flask import flash
        flash("This Akshaya Centre name is already registered. Please choose a different name.", "error")
        return redirect("/manager")
    
    # Get user details
    cursor.execute("SELECT name, email, Password, profile_picture, address FROM Login WHERE Login_id=?", (session.get("user_id"),))
    user = cursor.fetchone()
    if user:
        name, email, password, profile_pic, address = user
        cursor.execute("INSERT INTO Manager (manager_name, email, password, Center_name, location, Contact_number, request_type, status, profile_picture, address) VALUES (?, ?, ?, ?, ?, ?, 'CentreRegistration', 'Pending', ?, ?)",
                       (name, email, password, c_name, loc, contact, profile_pic, address))
        db.commit()
    db.close()
    
    from flask import flash
    flash("Centre request submitted successfully and is pending admin approval.", "success")
    return redirect("/manager")

@app.route("/manager/Services")
def manager_Services():
    if session.get("role") != "manager": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    centre_id = session.get("centre_id")
    cursor.execute("""
        SELECT s.service_id, s.service_name, s.service_fee, s.description,
               (SELECT GROUP_CONCAT(document_name, ', ') FROM Documents WHERE service_id = s.service_id) as document_list
        FROM Services s 
        WHERE s.centre_id=?
    """, (centre_id,))
    services = cursor.fetchall()
    db.close()
    return render_template("manager_services.html", services=services)

@app.route("/manager/request_service", methods=["GET", "POST"])
def manager_request_service():
    if session.get("role") != "manager": return redirect("/")
    if request.method == "POST":
        s_name = request.form["service_name"]
        s_fee = request.form["service_fee"]
        s_desc = request.form.get("description", "")
        s_docs = request.form.get("documents", "")
        db = get_db()
        cursor = db.cursor()
        # Fetch manager info for the request
        cursor.execute("SELECT name, email, Password, phone_number FROM Login WHERE Login_id=?", (session.get("user_id"),))
        m_info = cursor.fetchone()
        
        cursor.execute("""
            INSERT INTO Manager (manager_name, email, password, Contact_number, centre_id, request_type, requested_service_name, requested_service_fee, requested_service_desc, requested_documents) 
            VALUES (?, ?, ?, ?, ?, 'ServiceAddition', ?, ?, ?, ?)
        """, (m_info[0], m_info[1], m_info[2], m_info[3], session.get("centre_id"), s_name, s_fee, s_desc, s_docs))
        db.commit()
        db.close()
        return redirect("/manager/Services")
    return render_template("manager_request_service.html")

@app.route("/manager/tokens")
def manager_view_tokens():
    if session.get("role") != "manager": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    centre_id = session.get("centre_id")
    cursor.execute("""
        SELECT t.token_number, t.user_name, t.mobile_number, s.service_name,
               t.booking_date, t.booking_time, t.status, t.scheduled_time, t.token_id, u.name as staff_name
        FROM Tokens t
        JOIN Services s ON t.service_id = s.service_id
        LEFT JOIN Login u ON t.scheduled_by = u.Login_id
        WHERE t.centre_id = ? AND t.status NOT IN ('Booked', 'Paid')
        ORDER BY t.token_id DESC
    """, (centre_id,))
    tokens = cursor.fetchall()
    db.close()
    return render_template("manager_all_tokens.html", tokens=tokens)

@app.route("/manager/Staff", methods=["GET", "POST"])
def manager_Staff():
    if session.get("role") != "manager": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    centre_id = session.get("centre_id")
    
    def get_staff_list():
        cursor.execute("""
            SELECT s.staff_id, s.staff_name, s.email_id, l.profile_picture, s.phone_no, l.address, s.salary
            FROM Staff s 
            JOIN Login l ON s.login_id = l.Login_id
            WHERE s.centre_id=?
        """, (centre_id,))
        return cursor.fetchall()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_salary":
            Staff_id = request.form["Staff_id"]
            salary = request.form["salary"]
            cursor.execute("UPDATE Staff SET salary=? WHERE staff_id=? AND centre_id=?", (salary, Staff_id, centre_id))
            db.commit()
        elif action == "delete_staff":
            staff_id = request.form.get("staff_id")
            cursor.execute("SELECT login_id FROM Staff WHERE staff_id=? AND centre_id=?", (staff_id, centre_id))
            row = cursor.fetchone()
            if row:
                login_id = row[0]
                cursor.execute("DELETE FROM Staff WHERE staff_id=?", (staff_id,))
                cursor.execute("DELETE FROM Login WHERE Login_id=?", (login_id,))
                db.commit()
        elif action == "update_staff":
            staff_id = request.form.get("staff_id")
            name     = request.form["name"]
            email    = request.form["email"]
            phone    = request.form.get("phone", "")
            address  = request.form.get("address", "")
            password = request.form.get("password")
            confirm_password = request.form.get("confirm_password")
            
            err = None
            if not phone.isdigit() or len(phone) != 10:
                err = "Mobile number must be exactly 10 digits!"
            elif password:
                if password != confirm_password:
                    err = "Passwords do not match!"
                elif len(password) != 8:
                    err = "Password must be exactly 8 characters!"
            
            if not err:
                # Check if email is already taken by another user
                cursor.execute("SELECT login_id FROM Staff WHERE staff_id=? AND centre_id=?", (staff_id, centre_id))
                row = cursor.fetchone()
                if row:
                    login_id = row[0]
                    cursor.execute("SELECT Login_id FROM Login WHERE email=? AND Login_id != ?", (email, login_id))
                    if cursor.fetchone():
                        err = "Email is already registered to another user!"
            
            if err:
                Staff_list = get_staff_list()
                db.close()
                return render_template("manager_staff.html", Staff_list=Staff_list, error=err)
                
            cursor.execute("SELECT login_id FROM Staff WHERE staff_id=? AND centre_id=?", (staff_id, centre_id))
            row = cursor.fetchone()
            if row:
                login_id = row[0]
                
                profile_pic_filename = None
                if 'profile_picture' in request.files:
                    file = request.files['profile_picture']
                    if file and file.filename != '':
                        import os, time
                        filename = f"staff_{int(time.time())}_{file.filename}"
                        upload_dir = os.path.join(app.root_path, 'static', 'uploads')
                        os.makedirs(upload_dir, exist_ok=True)
                        file.save(os.path.join(upload_dir, filename))
                        profile_pic_filename = f"uploads/{filename}"
                
                if password:
                    cursor.execute("UPDATE Login SET Password=? WHERE Login_id=?", (password, login_id))
                if profile_pic_filename:
                    cursor.execute("UPDATE Login SET profile_picture=? WHERE Login_id=?", (profile_pic_filename, login_id))
                
                cursor.execute("UPDATE Login SET name=?, email=?, phone_number=?, address=? WHERE Login_id=?",
                               (name, email, phone, address, login_id))
                cursor.execute("UPDATE Staff SET staff_name=?, email_id=?, phone_no=? WHERE staff_id=?",
                               (name, email, phone, staff_id))
                db.commit()
        else: # add_staff
            name     = request.form["name"]
            email    = request.form["email"]
            password = request.form["password"]
            confirm_password = request.form["confirm_password"]
            phone    = request.form.get("phone", "")
            address  = request.form.get("address", "")
            salary   = request.form.get("salary", "0")
            
            err = None
            if not phone.isdigit() or len(phone) != 10:
                err = "Mobile number must be exactly 10 digits!"
            elif password != confirm_password:
                err = "Passwords do not match!"
            elif len(password) != 8:
                err = "Password must be exactly 8 characters!"
            else:
                # Check if email is already taken
                cursor.execute("SELECT Login_id FROM Login WHERE email = ?", (email,))
                if cursor.fetchone():
                    err = "Email is already registered!"
                
            if err:
                Staff_list = get_staff_list()
                db.close()
                return render_template("manager_staff.html", Staff_list=Staff_list, error=err)
                
            profile_pic_filename = None
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and file.filename != '':
                    import os, time
                    filename = f"staff_{int(time.time())}_{file.filename}"
                    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
                    os.makedirs(upload_dir, exist_ok=True)
                    file.save(os.path.join(upload_dir, filename))
                    profile_pic_filename = f"uploads/{filename}"
                    
            cursor.execute("INSERT INTO Login (name, email, Password, role, centre_id, phone_number, profile_picture, address) VALUES (?, ?, ?, 'staff', ?, ?, ?, ?)",
                           (name, email, password, centre_id, phone, profile_pic_filename, address))
            login_id = cursor.lastrowid
            
            cursor.execute("INSERT INTO Staff (login_id, centre_id, staff_name, email_id, phone_no, salary) VALUES (?, ?, ?, ?, ?, ?)",
                           (login_id, centre_id, name, email, phone, salary))
            db.commit()
            
        db.close()
        return redirect("/manager/Staff")
        
    Staff_list = get_staff_list()
    db.close()
    return render_template("manager_staff.html", Staff_list=Staff_list)

@app.route("/manager/statistics")
def manager_statistics():
    if session.get("role") != "manager": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    centre_id = session.get("centre_id")
    
    if not centre_id:
        db.close()
        return redirect("/manager")

    # Analytics Calculations for Selected Month
    import calendar
    import math
    from datetime import datetime
    
    # 1. Available Months
    cursor.execute("SELECT DISTINCT substr(booking_date, 1, 7) as ym FROM Tokens WHERE centre_id = ? ORDER BY ym DESC", (centre_id,))
    db_months = [row[0] for row in cursor.fetchall() if row[0]]
    
    current_ym = datetime.now().strftime("%Y-%m")
    if current_ym not in db_months:
        db_months.insert(0, current_ym)
        
    month_names = {
        1: "January", 2: "February", 3: "March", 4: "April",
        5: "May", 6: "June", 7: "July", 8: "August",
        9: "September", 10: "October", 11: "November", 12: "December"
    }
    
    available_months = []
    for ym in db_months:
        try:
            yr, mn = map(int, ym.split('-'))
            available_months.append({
                'value': ym,
                'label': f"{month_names[mn]} {yr}"
            })
        except:
            pass
            
    # Get selected month
    selected_month = request.args.get('month')
    if not selected_month or selected_month not in db_months:
        selected_month = current_ym
        
    try:
        selected_year, selected_mn = map(int, selected_month.split('-'))
    except:
        selected_year, selected_mn = datetime.now().year, datetime.now().month
        selected_month = current_ym
        
    month_label = f"{month_names[selected_mn]} {selected_year}"
    
    # 2. Total completed services in selected month
    month_pattern = f"{selected_month}-%"
    cursor.execute("""
        SELECT COUNT(*) FROM Tokens
        WHERE centre_id = ? AND status = 'Completed' AND booking_date LIKE ?
    """, (centre_id, month_pattern))
    total_completed = cursor.fetchone()[0]
    
    # 3. Service counts
    cursor.execute("""
        SELECT s.service_name, COUNT(t.token_id) as count
        FROM Tokens t
        JOIN Services s ON t.service_id = s.service_id
        WHERE t.centre_id = ? AND t.status = 'Completed' AND t.booking_date LIKE ?
        GROUP BY s.service_id, s.service_name
        ORDER BY count DESC
    """, (centre_id, month_pattern))
    raw_service_counts = cursor.fetchall()
    
    # 4. Most popular service & highest count
    if raw_service_counts:
        most_popular_service = raw_service_counts[0][0]
        highest_service_count = raw_service_counts[0][1]
    else:
        most_popular_service = "None"
        highest_service_count = 0
        
    # 5. Average Daily Services
    days_in_month = calendar.monthrange(selected_year, selected_mn)[1]
    avg_daily = round(total_completed / days_in_month, 2)
    
    # 6. Service Distribution data & chart data
    chart_services = []
    # Palette of colors for chart bars and progress rings
    color_schemes = [
        {"gradient": "linear-gradient(to top, #f59e0b, #fbbf24)", "color": "#f59e0b", "icon": "👤", "label": "Aadhaar"},
        {"gradient": "linear-gradient(to top, #3b82f6, #60a5fa)", "color": "#3b82f6", "icon": "💳", "label": "PAN"},
        {"gradient": "linear-gradient(to top, #10b981, #34d399)", "color": "#10b981", "icon": "📄", "label": "Income"},
        {"gradient": "linear-gradient(to top, #8b5cf6, #a78bfa)", "color": "#8b5cf6", "icon": "👥", "label": "Caste"},
        {"gradient": "linear-gradient(to top, #ec4899, #f472b6)", "color": "#ec4899", "icon": "🏠", "label": "Nativity"},
        {"gradient": "linear-gradient(to top, #f97316, #fb923c)", "color": "#f97316", "icon": "🗳️", "label": "Voter"},
        {"gradient": "linear-gradient(to top, #06b6d4, #22d3ee)", "color": "#06b6d4", "icon": "🛂", "label": "Passport"},
        {"gradient": "linear-gradient(to top, #6b7280, #9ca3af)", "color": "#6b7280", "icon": "📋", "label": "Other"}
    ]
    
    def get_service_meta(name, index):
        name_l = name.lower()
        if 'aadhar' in name_l:
            return color_schemes[0]
        elif 'pan' in name_l:
            return color_schemes[1]
        elif 'income' in name_l:
            return color_schemes[2]
        elif 'caste' in name_l:
            return color_schemes[3]
        elif 'nativity' in name_l:
            return color_schemes[4]
        elif 'voter' in name_l:
            return color_schemes[5]
        elif 'passport' in name_l:
            return color_schemes[6]
        else:
            return color_schemes[min(index + 2, len(color_schemes)-1)]
            
    for idx, row in enumerate(raw_service_counts):
        s_name, s_count = row
        meta = get_service_meta(s_name, idx)
        
        pct = round((s_count / total_completed * 100), 1) if total_completed > 0 else 0
        dash_offset = round(150.8 - (150.8 * pct / 100), 1)
        
        chart_services.append({
            'name': s_name,
            'count': s_count,
            'percentage': pct,
            'dash_offset': dash_offset,
            'gradient': meta['gradient'],
            'color': meta['color'],
            'icon': meta['icon'],
            'label': meta['label']
        })
        
    # Chart Y-Axis Scale
    chart_max = 10
    if highest_service_count > 100:
        chart_max = int(math.ceil(highest_service_count / 100) * 100)
    elif highest_service_count > 50:
        chart_max = 100
    elif highest_service_count > 10:
        chart_max = 50
    elif highest_service_count > 0:
        chart_max = 10
        
    y_axis_ticks = [
        int(chart_max),
        int(chart_max * 0.8),
        int(chart_max * 0.6),
        int(chart_max * 0.4),
        int(chart_max * 0.2),
        0
    ]

    db.close()
    return render_template("manager_stats.html",
                           total_completed=total_completed, chart_services=chart_services,
                           most_popular_service=most_popular_service, highest_service_count=highest_service_count,
                           avg_daily=avg_daily, available_months=available_months, selected_month=selected_month,
                           month_label=month_label, chart_max=chart_max, y_axis_ticks=y_axis_ticks)

@app.route("/manager/attendance")
def manager_Attendance():
    if session.get("role") != "manager": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT a.date, u.name, a.login_time 
        FROM Attendance a
        JOIN Login u ON a.Login_id = u.Login_id
        WHERE a.centre_id=?
        ORDER BY a.date DESC, a.login_time DESC
    ''', (session.get("centre_id"),))
    records = cursor.fetchall()
    db.close()
    return render_template("manager_attendance.html", records=records)

# ─────────────────────────────────────────────
#  STAFF
# ─────────────────────────────────────────────
@app.route("/staff")
def Staff_dashboard():
    if session.get("role") != "staff":
        return redirect("/")
    db     = get_db()
    cursor = db.cursor()
    today  = str(date.today())
    cursor.execute("""
        SELECT t.token_id, t.token_number, t.user_name, t.mobile_number,
               s.service_name, c.Center_name, t.booking_time, t.status, p.payment_status, s.service_fee, t.scheduled_time,
               u.name as Staff_name, t.scheduled_by
        FROM Tokens t
        JOIN Services s ON t.service_id = s.service_id
        JOIN Akshaya_centers  c ON t.centre_id  = c.centre_id
        LEFT JOIN Payments p ON p.token_id = t.token_id
        LEFT JOIN Login u ON t.scheduled_by = u.Login_id
        WHERE t.booking_date = ? AND t.centre_id = ?
        ORDER BY t.token_number ASC, t.token_id ASC
    """, (today, session.get("centre_id")))
    tokens_list = cursor.fetchall()
    
    cursor.execute("""
        SELECT c.Center_name, 
               (SELECT name FROM Login WHERE role='manager' AND centre_id=? LIMIT 1) as manager_name
        FROM Akshaya_centers c WHERE c.centre_id=?
    """, (session.get("centre_id"), session.get("centre_id")))
    info = cursor.fetchone()
    Center_name = info[0] if info else "Unknown Centre"
    manager_name = info[1] if (info and len(info)>1 and info[1]) else "No Manager Assigned"

    cursor.execute("""
        SELECT COUNT(*) FROM Service_requests WHERE centre_id = ? AND status = 'IVR_Pending'
    """, (session.get("centre_id"),))
    pending_count = cursor.fetchone()[0]

    cursor.execute("SELECT name, profile_picture FROM Login WHERE Login_id=?", (session.get("user_id"),))
    row = cursor.fetchone()
    staff_name = row[0] if row else "Staff Member"
    profile_pic = row[1] if row else None

    db.close()
    return render_template("staff_dashboard.html", tokens=tokens_list, today=today, Center_name=Center_name, manager_name=manager_name, pending_count=pending_count, staff_name=staff_name, profile_pic=profile_pic)

@app.route("/Staff/schedule_token/<int:token_id>", methods=["POST"])
def Staff_schedule_token(token_id):
    if session.get("role") != "staff":
        return redirect("/")
    scheduled_time = request.form["scheduled_time"]
    Staff_id = session.get("user_id")
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT status, scheduled_by FROM Tokens WHERE token_id=?", (token_id,))
    row = cursor.fetchone()
    current_status = row[0]
    existing_staff = row[1]
    
    if existing_staff and existing_staff != Staff_id:
        db.close()
        from flask import flash
        flash("This token is already being handled by another staff member.", "error")
        return redirect("/staff")

    if current_status == 'IVR_Pending':
        # Fetch service_id, centre_id, booking_date to calculate token number
        cursor.execute("SELECT service_id, centre_id, booking_date FROM Tokens WHERE token_id=?", (token_id,))
        s_id, c_id, b_date = cursor.fetchone()
        
        cursor.execute(
            "SELECT COUNT(*) FROM Tokens WHERE centre_id=? AND booking_date=? AND token_number IS NOT NULL",
            (c_id, b_date)
        )
        count = cursor.fetchone()[0]
        token_number = count + 1
        
        cursor.execute("UPDATE Tokens SET scheduled_time=?, status='IVR_Scheduled', scheduled_by=?, token_number=? WHERE token_id=?", 
                       (scheduled_time, Staff_id, token_number, token_id))
    else:
        cursor.execute("UPDATE Tokens SET scheduled_time=?, status='Scheduled', scheduled_by=? WHERE token_id=?", 
                       (scheduled_time, Staff_id, token_id))
    
    cursor.execute("""
        SELECT t.user_name, t.mobile_number, t.token_number, s.service_name, s.service_fee,
               (SELECT GROUP_CONCAT(document_name, ', ') FROM Documents WHERE service_id = s.service_id) as document_list
        FROM Tokens t
        JOIN Services s ON t.service_id = s.service_id
        WHERE t.token_id=?
    """, (token_id,))
    t_data = cursor.fetchone()
    if t_data:
        u_name, mobile, token_num, s_name, s_fee, s_docs = t_data
        
        # Malayalam SMS Content with details (ONLY for IVR Bookings)
        if current_status == 'IVR_Pending':
            sms_content = f"""
[DEMO SMS to {mobile}]
പ്രിയപ്പെട്ട {u_name},
നിങ്ങളുടെ {s_name} ടോക്കൺ #{token_num if token_num else 'TBD'} സമയം {scheduled_time} ന് നിശ്ചയിച്ചിരിക്കുന്നു.
ദയവായി ഈ രേഖകൾ കൊണ്ടുവരിക: {s_docs if s_docs else 'ആധാർ കാർഡ്'}.
(ശ്രദ്ധിക്കുക: ഈ ബുക്കിംഗിന് മുൻകൂർ പണമടയ്ക്കേണ്ടതില്ല.)
- അക്ഷയ
"""
            try:
                print(f"\n{sms_content}\n")
            except UnicodeEncodeError:
                print(f"\n{sms_content.encode('ascii', errors='replace').decode('ascii')}\n")
            from flask import flash
            flash(f"Token scheduled! Simulated SMS printed in console.", "success")
        else:
            from flask import flash
            flash(f"Token scheduled!", "success")

    db.commit()
    db.close()
    return redirect("/staff")

@app.route("/Staff/approve_request/<int:request_id>", methods=["POST"])
def Staff_approve_request(request_id):
    if session.get("role") != "staff": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    
    # Fetch request details
    cursor.execute("SELECT citizen_name, mobile_number, centre_id, service_id FROM Service_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    
    if req:
        name, mobile, centre_id, service_id = req
        today = str(date.today())
        now_time = datetime.now().strftime("%H:%M:%S")
        
        # 1. Create the Token (Removed remarks column)
        cursor.execute("""
            INSERT INTO Tokens (token_number, user_name, mobile_number, centre_id, service_id, booking_date, booking_time, status)
            VALUES (NULL, ?, ?, ?, ?, ?, ?, 'IVR_Pending')
        """, (name, mobile, centre_id, service_id, today, now_time))
        
        # 2. Update Request Status
        cursor.execute("UPDATE Service_requests SET status = 'Processed' WHERE id = ?", (request_id,))
        
        # SMS Simulation for Demo (Malayalam)
        sms_content = f"""
[DEMO SMS to {mobile}]
പ്രിയപ്പെട്ട {name},
നിങ്ങളുടെ IVR അപേക്ഷ സ്വീകരിച്ചിരിക്കുന്നു. ജീവനക്കാർ ഉടൻ തന്നെ സമയം നിശ്ചയിച്ച് അറിയിക്കുന്നതാണ്.
- അക്ഷയ
"""
        try:
            print(f"\n{sms_content}\n")
        except UnicodeEncodeError:
            print(f"\n{sms_content.encode('ascii', errors='replace').decode('ascii')}\n")
        
        db.commit()
        
    db.close()
    return redirect("/Staff/citizen_requests")

@app.route("/Staff/citizen_requests")
def Staff_citizen_requests():
    if session.get("role") != "staff": return redirect("/")
    db = get_db()
    cursor = db.cursor()
    c_id = session.get("centre_id")
    print(f"DEBUG: Staff Fetching Requests for centre_id: {c_id}")
    cursor.execute("""
        SELECT sr.id, sr.citizen_name, sr.mobile_number, s.service_name, sr.status, sr.Created_at
        FROM Service_requests sr
        JOIN Services s ON sr.service_id = s.service_id
        WHERE sr.centre_id = ? AND sr.status = 'IVR_Pending'
        ORDER BY sr.Created_at DESC
    """, (c_id,))
    requests_list = cursor.fetchall()
    print(f"DEBUG: Found {len(requests_list)} requests")
    db.close()
    return render_template("staff_citizen_requests.html", requests=requests_list)

@app.route("/Staff/ask_payment/<int:token_id>", methods=["POST"])
def Staff_ask_payment(token_id):
    if session.get("role") != "staff":
        return redirect("/")
    db = get_db()
    cursor = db.cursor()
    
    # Ownership Check
    cursor.execute("SELECT scheduled_by FROM Tokens WHERE token_id=?", (token_id,))
    row = cursor.fetchone()
    if row and row[0] and row[0] != session.get("user_id"):
        db.close()
        from flask import flash
        flash("Unauthorized: This token is handled by another staff member.", "error")
        return redirect("/staff")

    # Update status to 'Payment Requested'
    cursor.execute("UPDATE Tokens SET status='Payment Requested' WHERE token_id=?", (token_id,))
    db.commit()
    db.close()
    return redirect("/staff")

@app.route("/Staff/update_token/<int:token_id>", methods=["POST"])
def update_token(token_id):
    if session.get("role") != "staff":
        return redirect("/")
    # Status comes from the simplified select dropdown
    status  = request.form.get("new_status")
    remarks = request.form.get("remarks", "")
    db      = get_db()
    cursor  = db.cursor()
    
    # Ownership Check
    cursor.execute("SELECT scheduled_by FROM Tokens WHERE token_id=?", (token_id,))
    row = cursor.fetchone()
    if row and row[0] and row[0] != session.get("user_id"):
        db.close()
        from flask import flash
        flash("Unauthorized: This token is handled by another staff member.", "error")
        return redirect("/staff")

    cursor.execute("UPDATE Tokens SET status=?, remarks=? WHERE token_id=?", (status, remarks, token_id))
    # Update linked application if it exists
    cursor.execute("UPDATE Applications SET status=?, remarks=? WHERE token_id=?",
                   (status, remarks, token_id))
    db.commit()
    db.close()
    from flask import flash
    flash("Token status updated successfully!", "success")
    return redirect("/staff")

@app.route("/Staff/mark_paid/<int:token_id>", methods=["POST"])
def Staff_mark_paid(token_id):
    if session.get("role") != "staff":
        return redirect("/")
    
    amount = request.form["amount"]
    db     = get_db()
    cursor = db.cursor()
    
    # Ownership Check
    cursor.execute("SELECT scheduled_by FROM Tokens WHERE token_id=?", (token_id,))
    row = cursor.fetchone()
    if row and row[0] and row[0] != session.get("user_id"):
        db.close()
        from flask import flash
        flash("Unauthorized: This token is handled by another staff member.", "error")
        return redirect("/staff")
        
    # Check if payment already exists
    cursor.execute("SELECT id FROM Payments WHERE token_id = ?", (token_id,))
    if cursor.fetchone():
        db.close()
        return redirect("/Staff")
        
    cursor.execute("""
        INSERT INTO Payments (token_id, amount, payment_method, payment_status, transaction_id, payment_date)
        VALUES (?, ?, 'Cash', 'Paid', 'CASH-PAY', ?)
    """, (token_id, amount, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    db.close()
    return redirect("/Staff")

@app.route('/api/ivr/tts')
def api_ivr_tts():
    text = request.args.get('text', '')
    lang = request.args.get('lang', 'en')
    
    if not text:
        return "No text", 400
        
    try:
        tts = gTTS(text=text, lang=lang)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return send_file(fp, mimetype='audio/mpeg')
    except Exception as e:
        print(f"TTS Error: {e}")
        return "TTS Generation failed", 500

# ─────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)