import sqlite3
import os

def reinit_database():
    db_path = os.path.join(os.path.dirname(__file__), "akshaya.db")
    
    # Remove existing db file if it exists to start fresh
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing {db_path}")

    try:
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL;")
        cursor = db.cursor()
        
        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = OFF;")

        all_tables = [
            "Login", "Akshaya_centers", "Manager", "Staff", "Services", 
            "Service_requests", "Tokens", "Attendance", "Payments", 
            "Reviews", "Applications", "Documents"
        ]
        for t in all_tables:
            cursor.execute(f"DROP TABLE IF EXISTS {t}")

        # 1. Login
        cursor.execute("""
            CREATE TABLE Login (
                Login_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, 
                email TEXT UNIQUE,
                Password TEXT, 
                role TEXT,
                centre_id INTEGER,
                phone_number TEXT,
                profile_picture TEXT,
                address TEXT
            )
        """)

        # 2. Akshaya_centers
        cursor.execute("""
            CREATE TABLE Akshaya_centers (
                centre_id INTEGER PRIMARY KEY AUTOINCREMENT,
                Center_name TEXT, 
                email_id TEXT,
                Contact_number TEXT,
                location TEXT, 
                location_or_place TEXT,
                street_name TEXT,
                building_no TEXT, 
                district TEXT,
                latitude TEXT,
                longitude TEXT,
                Created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Manager
        cursor.execute("""
            CREATE TABLE Manager (
                manager_id INTEGER PRIMARY KEY AUTOINCREMENT,
                manager_name TEXT, 
                email TEXT,
                password TEXT, 
                Center_name TEXT,
                location TEXT, 
                Contact_number TEXT,
                profile_picture TEXT,
                address TEXT,
                status TEXT DEFAULT 'Pending',
                request_type TEXT DEFAULT 'Registration',
                requested_service_name TEXT,
                requested_service_fee DECIMAL(10,2),
                requested_service_desc TEXT,
                requested_documents TEXT,
                centre_id INTEGER,
                Created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. Staff
        cursor.execute("""
            CREATE TABLE Staff (
                Staff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                login_id INTEGER, 
                centre_id INTEGER,
                Staff_name TEXT, 
                email_id TEXT,
                phone_no TEXT, 
                salary DECIMAL(10,2),
                FOREIGN KEY (login_id) REFERENCES Login(Login_id),
                FOREIGN KEY (centre_id) REFERENCES Akshaya_centers(centre_id)
            )
        """)

        # 5. Services
        cursor.execute("""
            CREATE TABLE Services (
                service_id INTEGER PRIMARY KEY AUTOINCREMENT,
                centre_id INTEGER, 
                service_name TEXT,
                service_fee DECIMAL(10,2), 
                description TEXT,
                document_description TEXT,
                FOREIGN KEY (centre_id) REFERENCES Akshaya_centers(centre_id)
            )
        """)

        # 6. Service_requests
        cursor.execute("""
            CREATE TABLE Service_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                citizen_name TEXT, 
                mobile_number TEXT,
                centre_id INTEGER, 
                service_id INTEGER,
                status TEXT DEFAULT 'Pending',
                Created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (centre_id) REFERENCES Akshaya_centers(centre_id),
                FOREIGN KEY (service_id) REFERENCES Services(service_id)
            )
        """)

        # 7. Tokens
        cursor.execute("""
            CREATE TABLE Tokens (
                token_id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_number INTEGER, 
                user_name TEXT,
                mobile_number TEXT, 
                centre_id INTEGER,
                service_id INTEGER, 
                booking_date DATE,
                booking_time TIME, 
                scheduled_time TIME,
                scheduled_by INTEGER, 
                status TEXT DEFAULT 'Pending',
                Created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                rating INTEGER,
                review TEXT,
                remarks TEXT,
                FOREIGN KEY (centre_id) REFERENCES Akshaya_centers(centre_id),
                FOREIGN KEY (service_id) REFERENCES Services(service_id)
            )
        """)

        # 8. Attendance
        cursor.execute("""
            CREATE TABLE Attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Login_id INTEGER, 
                centre_id INTEGER,
                date DATE, 
                login_time TIME,
                UNIQUE (Login_id, date),
                FOREIGN KEY (Login_id) REFERENCES Login(Login_id),
                FOREIGN KEY (centre_id) REFERENCES Akshaya_centers(centre_id)
            )
        """)

        # 9. Payments
        cursor.execute("""
            CREATE TABLE Payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id INTEGER, 
                service_id INTEGER,
                amount DECIMAL(10,2), 
                payment_method TEXT,
                payment_status TEXT DEFAULT 'Pending',
                transaction_id TEXT, 
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (token_id) REFERENCES Tokens(token_id)
            )
        """)

        # 10. Reviews
        cursor.execute("""
            CREATE TABLE Reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                centre_id INTEGER, 
                user_name TEXT,
                rating INTEGER, 
                review_text TEXT,
                Created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (centre_id) REFERENCES Akshaya_centers(centre_id)
            )
        """)

        # 11. Applications
        cursor.execute("""
            CREATE TABLE Applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_number TEXT UNIQUE,
                token_id INTEGER, 
                status TEXT DEFAULT 'Pending',
                remarks TEXT,
                FOREIGN KEY (token_id) REFERENCES Tokens(token_id)
            )
        """)

        # 12. Documents
        cursor.execute("""
            CREATE TABLE Documents (
                document_id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER, 
                document_name TEXT,
                is_mandatory INTEGER DEFAULT 1,
                doc_detail1 TEXT,
                doc_detail2 TEXT,
                doc_detail3 TEXT,
                doc_detail4 TEXT,
                FOREIGN KEY (service_id) REFERENCES Services(service_id)
            )
        """)

        # Insert default admin user
        cursor.execute("INSERT INTO Login (Login_id, name, email, Password, role) VALUES (1, 'Admin', 'admin@gmail.com', 'admin123', 'admin')")

        cursor.execute("PRAGMA foreign_keys = ON;")
        db.commit()
        db.close()
        print("SQLite Database Schema re-initialized! SQLite file: akshaya.db")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    reinit_database()
