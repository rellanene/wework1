import os
import hashlib
from openpyxl import Workbook
from flask import send_file
from io import BytesIO
from datetime import datetime
from datetime import date
from datetime import date, datetime
from functools import wraps
from flask import jsonify
import pdfkit
from flask import send_file
import json




from flask import (
    Flask, render_template, request, redirect,
    session, url_for, flash, send_from_directory
)
import mysql.connector
from werkzeug.utils import secure_filename

# -----------------------------
# CONFIG
# -----------------------------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Clement-88",
    "database": "business_app"
}

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}


# -----------------------------
# HELPERS
# -----------------------------
def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------- INVENTORY HELPERS ----------

def get_or_create_inventory(product_id, store_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM inventory
        WHERE product_id=%s AND store_id=%s
    """, (product_id, store_id))
    row = cursor.fetchone()

    if row:
        return row["id"]

    cursor.execute("""
        INSERT INTO inventory (product_id, store_id, quantity)
        VALUES (%s, %s, 0)
    """, (product_id, store_id))
    db.commit()
    return cursor.lastrowid


def add_stock(product_id, quantity, store_id, user_id, business_id):
    db = get_db()
    cursor = db.cursor()

    # Update stock_levels
    cursor.execute("""
        INSERT INTO stock_levels (business_id, product_id, store_id, quantity)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
    """, (business_id, product_id, store_id, quantity))

    # Log movement (aligned with your DB)
    cursor.execute("""
        INSERT INTO stock_movements 
        (business_id, product_id, movement_type, quantity, to_store_id, user_id)
        VALUES (%s, %s, 'stock_in', %s, %s, %s)
    """, (business_id, product_id, quantity, store_id, user_id))

    db.commit()




def reduce_stock_on_sale(product_id, user_id, store_id, quantity, business_id, sale_id):
    db = get_db()
    cursor = db.cursor()

    # Reduce stock
    cursor.execute("""
        UPDATE stock_levels
        SET quantity = quantity - %s
        WHERE product_id=%s AND store_id=%s AND business_id=%s
    """, (quantity, product_id, store_id, business_id))

    # Log movement
    cursor.execute("""
        INSERT INTO stock_movements 
        (business_id, product_id, movement_type, quantity, from_store_id, user_id, sale_id)
        VALUES (%s, %s, 'sale', %s, %s, %s, %s)
    """, (business_id, product_id, quantity, store_id, user_id, sale_id))

    db.commit()



def transfer_stock(product_id, user_id, from_store_id, to_store_id, quantity, business_id):
    db = get_db()
    cursor = db.cursor()

    # Reduce from source store
    cursor.execute("""
        UPDATE stock_levels
        SET quantity = quantity - %s
        WHERE product_id=%s AND store_id=%s AND business_id=%s
    """, (quantity, product_id, from_store_id, business_id))

    # Add to destination store
    cursor.execute("""
        INSERT INTO stock_levels (business_id, product_id, store_id, quantity)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
    """, (business_id, product_id, to_store_id, quantity))

    # Log movement
    cursor.execute("""
        INSERT INTO stock_movements 
        (business_id, product_id, movement_type, quantity, from_store_id, to_store_id, user_id)
        VALUES (%s, %s, 'transfer', %s, %s, %s, %s)
    """, (business_id, product_id, quantity, from_store_id, to_store_id, user_id))

    db.commit()




# -----------------------------
# APP FACTORY
# -----------------------------
def create_app():
    app = Flask(__name__)
    app.secret_key = "your_secret_key_here"
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # -------------------------
    # LOGIN REQUIRED DECORATOR
    # -------------------------
    def login_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper
    
    #-----------Global Access-----
    @app.context_processor
    def inject_permissions():
        if "user" in session:
            permissions = get_permissions(session["user"]["id"])  # your logic here
            return dict(permissions=permissions)
        return dict(permissions=None)

    # -------------------------
    # AUTH & REGISTRATION
    # -------------------------
    @app.route("/register", methods=["GET", "POST"])
    def register():
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id, name FROM businesses")
        businesses = cursor.fetchall()
    
        if request.method == "POST":
            user_type = request.form["user_type"]
            name = request.form["name"]
            email = request.form["email"]
            password = hash_password(request.form["password"])
    
            # Security questions
            q1 = request.form["question1"]
            a1 = request.form["answer1"]
            q2 = request.form["question2"]
            a2 = request.form["answer2"]
            q3 = request.form["question3"]
            a3 = request.form["answer3"]
            q4 = request.form["question4"]
            a4 = request.form["answer4"]
            q5 = request.form["question5"]
            a5 = request.form["answer5"]
    
            # -----------------------------
            # OWNER REGISTRATION
            # -----------------------------
            if user_type == "end_user":
                business_name = request.form["business_name"]
    
                # Create business
                cursor.execute("INSERT INTO businesses (name) VALUES (%s)", (business_name,))
                business_id = cursor.lastrowid
    
                # Create owner user
                cursor.execute("""
                    INSERT INTO users (business_id, name, email, password, role)
                    VALUES (%s, %s, %s, %s, 'owner')
                """, (business_id, name, email, password))
                user_id = cursor.lastrowid
    
                # Save security questions
                cursor.execute("""
                    INSERT INTO user_security_questions (
                        user_id, question1, answer1, question2, answer2,
                        question3, answer3, question4, answer4, question5, answer5
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (user_id, q1, a1, q2, a2, q3, a3, q4, a4, q5, a5))
    
                # Owner gets full permissions
                cursor.execute("""
                    INSERT INTO user_permissions (
                        user_id,
                        can_view_dashboard,
                        can_view_products,
                        can_view_customers,
                        can_view_sales,
                        can_view_pos,
                        can_view_finances,
                        can_view_reports,
                        can_view_visuals,
                        can_view_stores,
                        can_view_stock_in,
                        can_view_stock_transfer,
                        can_view_movements,
                        can_view_gallery,
                        can_view_settings,
                        can_view_profile
                    ) VALUES (%s, 1,1,1,1,1,1,1,1,1,1,1,1,1,1,1)
                """, (user_id,))
    
            # -----------------------------
            # STAFF REGISTRATION
            # -----------------------------
            elif user_type == "staff":
                business_id = request.form["business_id"]
    
                cursor.execute("""
                    INSERT INTO users (business_id, name, email, password, role)
                    VALUES (%s, %s, %s, %s, 'staff')
                """, (business_id, name, email, password))
                user_id = cursor.lastrowid
    
                # Save security questions
                cursor.execute("""
                    INSERT INTO user_security_questions (
                        user_id, question1, answer1, question2, answer2,
                        question3, answer3, question4, answer4, question5, answer5
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (user_id, q1, a1, q2, a2, q3, a3, q4, a4, q5, a5))
    
                # Staff gets ZERO permissions by default
                cursor.execute("""
                    INSERT INTO user_permissions (
                        user_id,
                        can_view_dashboard,
                        can_view_products,
                        can_view_customers,
                        can_view_sales,
                        can_view_pos,
                        can_view_finances,
                        can_view_reports,
                        can_view_visuals,
                        can_view_stores,
                        can_view_stock_in,
                        can_view_stock_transfer,
                        can_view_movements,
                        can_view_gallery,
                        can_view_settings,
                        can_view_profile
                    ) VALUES (%s, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0)
                """, (user_id,))
    
            db.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))
    
        return render_template("register.html", businesses=businesses)


    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form["email"]
            password = hash_password(request.form["password"])

            db = get_db()
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email=%s AND password=%s", (email, password))
            user = cursor.fetchone()

            if user:
                session["user"] = {
                    "id": user["id"],
                    "name": user["name"],
                    "email": user["email"],
                    "role": user["role"],
                    "business_id": user["business_id"]
                }
                return redirect(url_for("dashboard"))

            flash("Invalid email or password", "danger")

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
    
    #---------------Forgot Password Page---------
    @app.route("/forgot_password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            email = request.form["email"]
    
            db = get_db()
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cursor.fetchone()
    
            if not user:
                flash("Email not found", "danger")
                return redirect(url_for("forgot_password"))
    
            # Load security questions
            cursor.execute("SELECT * FROM user_security_questions WHERE user_id=%s", (user["id"],))
            questions = cursor.fetchone()
    
            return render_template("answer_questions.html", user=user, questions=questions)
    
        return render_template("forgot_password.html")
    
    #----------------Validate Answers----------
    @app.route("/validate_answers", methods=["POST"])
    def validate_answers():
        user_id = request.form["user_id"]
    
        answers = [
            request.form["answer1"],
            request.form["answer2"],
            request.form["answer3"],
            request.form["answer4"],
            request.form["answer5"]
        ]
    
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_security_questions WHERE user_id=%s", (user_id,))
        q = cursor.fetchone()
    
        correct = [
            q["answer1"], q["answer2"], q["answer3"], q["answer4"], q["answer5"]
        ]
    
        if answers == correct:
            return render_template("reset_password.html", user_id=user_id)
    
        flash("Incorrect answers", "danger")
        return redirect(url_for("forgot_password"))
    
    #----------------Save New Password-----------
    @app.route("/reset_password", methods=["POST"])
    def reset_password():
        user_id = request.form["user_id"]
        new_password = hash_password(request.form["password"])
    
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE users SET password=%s WHERE id=%s", (new_password, user_id))
        db.commit()
    
        flash("Password reset successful. Please log in.", "success")
        return redirect(url_for("login"))



    
    #---------------ADD STOCK BARCODE-------------
    
    @app.route("/get_product_by_barcode/<barcode>")
    def get_product_by_barcode(barcode):
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        cursor.execute("""
            SELECT id, name 
            FROM products 
            WHERE barcode=%s AND business_id=%s
        """, (barcode, business_id))
    
        product = cursor.fetchone()
    
        if product:
            return jsonify({"found": True, "id": product["id"], "name": product["name"]})
    
        return jsonify({"found": False, "barcode": barcode})
    
    #--------------SAVE STOCK BARCODE-----------
    @app.route("/add_product_from_stockin", methods=["POST"])
    def add_product_from_stockin():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor()
    
        name = request.form["name"]
        barcode = request.form["barcode"]
        wholesale = request.form["wholesale_price"]
        price = request.form["price"]
    
        cursor.execute("""
            INSERT INTO products (business_id, name, barcode, wholesale_price, price)
            VALUES (%s, %s, %s, %s, %s)
        """, (business_id, name, barcode, wholesale, price))
    
        db.commit()
    
        return jsonify({"success": True, "product_id": cursor.lastrowid})

    # -------------------------
    # DASHBOARD
    # -------------------------
    @app.route("/")
    @login_required
    def dashboard():
        user = session["user"]
        business_id = user["business_id"]
    
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # Existing metrics
        cursor.execute("SELECT COUNT(*) AS total_products FROM products WHERE business_id=%s", (business_id,))
        total_products = cursor.fetchone()["total_products"]
    
        cursor.execute("SELECT COUNT(*) AS total_customers FROM customers WHERE business_id=%s", (business_id,))
        total_customers = cursor.fetchone()["total_customers"]
    
        cursor.execute("SELECT IFNULL(SUM(total_amount),0) AS total_sales FROM sales WHERE business_id=%s", (business_id,))
        total_sales = cursor.fetchone()["total_sales"]
    
        # Sales chart (existing)
        cursor.execute("""
            SELECT DATE(created_at) AS day, IFNULL(SUM(total_amount),0) AS total
            FROM sales
            WHERE business_id=%s
            GROUP BY DATE(created_at)
            ORDER BY day DESC
            LIMIT 7
        """, (business_id,))
        rows = cursor.fetchall()
        chart_labels = [str(r["day"]) for r in rows][::-1]
        chart_values = [float(r["total"]) for r in rows][::-1]
    
        # NEW: Returns widget data
        cursor.execute("""
            SELECT 
                COUNT(*) AS total_returns,
                IFNULL(SUM(total_refund), 0) AS total_refund_amount
            FROM returns
            WHERE business_id=%s
        """, (business_id,))
        returns_data = cursor.fetchone()
    
        return render_template(
            "dashboard.html",
            user=user,
            total_products=total_products,
            total_customers=total_customers,
            total_sales=total_sales,
            chart_labels=chart_labels,
            chart_values=chart_values,
            returns_data=returns_data  # <-- NEW
        )


    # -------------------------
    # PROFILE
    # -------------------------
    @app.route("/profile")
    @login_required
    def profile():
        user = session["user"]
        return render_template("profile.html", user=user)

    # -------------------------
    # STORES (simple management)
    # -------------------------
    @app.route("/stores", methods=["GET", "POST"])
    @login_required
    def stores():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)

        if request.method == "POST":
            name = request.form["name"]
            cursor.execute("""
                INSERT INTO stores (business_id, name)
                VALUES (%s, %s)
            """, (business_id, name))
            db.commit()
            return redirect(url_for("stores"))

        cursor.execute("SELECT * FROM stores WHERE business_id=%s", (business_id,))
        stores_list = cursor.fetchall()
        return render_template("stores.html", stores=stores_list)
    
    #Store Items
    @app.route("/store/<int:store_id>/products")
    @login_required
    def store_products(store_id):
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # Validate store
        cursor.execute("""
            SELECT id FROM stores 
            WHERE id=%s AND business_id=%s
        """, (store_id, business_id))
        store = cursor.fetchone()
    
        if not store:
            return jsonify({"products": []})
    
        # Return ALL products, even if no stock exists
        cursor.execute("""
            SELECT 
                p.id,
                p.name,
                COALESCE(p.price, 0) AS price,
                COALESCE(sl.quantity, 0) AS quantity
            FROM products p
            LEFT JOIN stock_levels sl
                ON sl.product_id = p.id
                AND sl.store_id = %s
                AND sl.business_id = %s
            WHERE p.business_id = %s
            ORDER BY p.name
        """, (store_id, business_id, business_id))
    
        products = cursor.fetchall()
    
        return jsonify({"products": products})




    # -------------------------
    # PRODUCTS (with total quantity)
    # -------------------------
    @app.route("/products", methods=["GET", "POST"])
    @login_required
    def products():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)

        if request.method == "POST":
            name = request.form["name"]
            price = request.form["price"]
            wholesale_price = request.form["wholesale_price"]

            cursor.execute("""
                INSERT INTO products (business_id, name, price, wholesale_price)
                VALUES (%s, %s, %s, %s)
            """, (business_id, name, price, wholesale_price))
            db.commit()
            return redirect(url_for("products"))

        cursor.execute("""
            SELECT p.*,
           IFNULL(SUM(i.quantity),0) AS total_quantity
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            WHERE p.business_id=%s
            GROUP BY p.id
        """, (business_id,))
        items = cursor.fetchall()
        return render_template("products.html", items=items)

    # -------------------------
    # STOCK IN (add stock to store)
    # -------------------------
    @app.route("/stock-in", methods=["GET", "POST"])
    @login_required
    def stock_in():
        business_id = session["user"]["business_id"]
        user_id = session["user"]["id"]  # REQUIRED
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        cursor.execute("SELECT * FROM products WHERE business_id=%s", (business_id,))
        products_list = cursor.fetchall()
    
        cursor.execute("SELECT * FROM stores WHERE business_id=%s", (business_id,))
        stores_list = cursor.fetchall()
    
        if request.method == "POST":
            product_id = request.form["product_id"]
            store_id = request.form["store_id"]
            quantity = int(request.form["quantity"])
    
            # FIXED: pass user_id + business_id in correct order
            add_stock(product_id, quantity, store_id, user_id, business_id)
    
            flash("Stock added successfully", "success")
            return redirect(url_for("stock_in"))
    
        return render_template("stock_in.html", products=products_list, stores=stores_list)
    
    #-----------------ROUTE: returns page
# -------------------- ROUTE: Returns Page
    @app.route("/returns")
    @login_required
    def returns_page():
        return render_template("returns.html")
    
    
    # -------------------- ROUTE: Load invoice + items
    @app.route("/returns/load/<invoice>")
    @login_required
    def load_invoice(invoice):
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        cursor.execute("""
            SELECT 
                s.id,
                s.id AS invoice_number,
                s.created_at AS date,
                s.store_id,
                st.name AS store_name,
                c.name AS customer_name
            FROM sales s
            JOIN stores st ON st.id = s.store_id
            LEFT JOIN customers c ON c.id = s.customer_id
            WHERE s.id=%s AND s.business_id=%s
        """, (invoice, business_id))
    
        sale = cursor.fetchone()
        
        # 0️⃣ Prevent duplicate returns for the same invoice
        cursor.execute("""
            SELECT id 
            FROM returns 
            WHERE sale_id=%s AND business_id=%s
            LIMIT 1
        """, (invoice, business_id))
        
        existing = cursor.fetchone()
        
        if existing:
            return jsonify({
                "status": "error",
                "message": "A return has already been processed for this invoice."
            }), 400

    
        if not sale:
            return jsonify({"success": False, "message": "Invoice not found."})
    
        cursor.execute("""
            SELECT si.product_id, p.name, si.quantity
            FROM sale_items si
            JOIN products p ON p.id = si.product_id
            WHERE si.sale_id=%s
        """, (sale["id"],))
    
        items = cursor.fetchall()
    
        return jsonify({
            "success": True,
            "customer": sale["customer_name"],
            "date": sale["date"],
            "store": sale["store_name"],
            "items": items
        })


# -------------------- ROUTE: Process the return
    @app.route("/returns/process/<invoice>", methods=["POST"])
    def process_return(invoice):
    
        # ALWAYS FIRST
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
    
        data = request.get_json()
        items = data.get("items", [])
    
        # Load sold quantities
        cursor.execute("""
            SELECT product_id, quantity 
            FROM sale_items 
            WHERE sale_id=%s
        """, (invoice,))
        sale_items = cursor.fetchall()
    
        sold_lookup = {str(row["product_id"]): row["quantity"] for row in sale_items}
    
        # VALIDATION
        for item in items:
            pid = str(item["product_id"])
            return_qty = int(item["quantity"])
            sold_qty = int(sold_lookup.get(pid, 0))
    
            if return_qty > sold_qty:
                return jsonify({
                    "success": False,
                    "message": "Return quantity cannot exceed sold quantity."
                }), 400

    # Continue with your normal return logic...

    
        if not items:
            return jsonify({"success": False, "message": "No items selected."})
    
        user = session["user"]
        business_id = user["business_id"]
        user_id = user["id"]
    
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # Load sale
        cursor.execute("""
            SELECT id, store_id
            FROM sales
            WHERE id=%s AND business_id=%s
        """, (invoice, business_id))
    
        sale = cursor.fetchone()
    
        if not sale:
            return jsonify({"success": False, "message": "Invoice not found."})
    
        store_id = sale["store_id"]
        
        
    
        # 1️⃣ Create return record (temporary reference)
        # DEBUG — see what DB and table Flask is REALLY using
        cursor.execute("SELECT DATABASE()")
        print("ACTIVE DB:", cursor.fetchone())
        
        cursor.execute("SHOW COLUMNS FROM returns")
        print("COLUMNS:", cursor.fetchall())

        cursor.execute("""
            INSERT INTO returns (
                business_id,
                sale_id,
                store_id,
                user_id,
                total_refund,
                reference
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (business_id, sale["id"], store_id, user_id, 0, ""))


    
        return_id = cursor.lastrowid
        db.commit() 
    
        # Generate proper reference
        reference = f"RETURN-{return_id}"
    
        cursor.execute("""
            UPDATE returns
            SET reference=%s
            WHERE id=%s
        """, (reference, return_id))
    
        total_refund = 0
    
        # 2️⃣ Process each returned item
        for item in items:
            product_id = item["product_id"]
            qty = int(item["quantity"])
    
            cursor.execute("SELECT price FROM products WHERE id=%s", (product_id,))
            product = cursor.fetchone()
    
            if not product:
                continue
    
            price = product["price"]
            total_refund += price * qty
    
            # Add stock back
            cursor.execute("""
                INSERT INTO stock_levels (business_id, product_id, store_id, quantity)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
            """, (business_id, product_id, store_id, qty))
    
            # Insert stock movement
            cursor.execute("""
                INSERT INTO stock_movements
                (business_id, product_id, movement_type, quantity, to_store_id, user_id)
                VALUES (%s, %s, 'return', %s, %s, %s)
            """, (business_id, product_id, qty, store_id, user_id))


    
            # Save return item
            cursor.execute("""
                INSERT INTO return_items (return_id, product_id, quantity, price)
                VALUES (%s, %s, %s, %s)
            """, (return_id, product_id, qty, price))
    
        # 3️⃣ Finance entry (negative sale)
        cursor.execute("""
            INSERT INTO finances (business_id, type, amount, reference, user_id)
            VALUES (%s, 'return', %s, %s, %s)
        """, (business_id, -total_refund, reference, user_id))
    
        # 4️⃣ Update total_refund in returns table
        cursor.execute("""
            UPDATE returns
            SET total_refund=%s
            WHERE id=%s
        """, (total_refund, return_id))
    
        db.commit()
    
        return jsonify({"success": True, "return_id": return_id})
    
    
    # -------------------- ROUTE: Return Document (HTML)
    @app.route("/returns/document/<int:return_id>")
    @login_required
    def return_document(return_id):
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        cursor.execute("""
            SELECT 
                r.id,
                r.created_at AS date,
                r.total_refund,
                s.id AS invoice_number,
                c.name AS customer_name,
                st.name AS store_name,
                u.name AS user_name
            FROM returns r
            JOIN sales s ON s.id = r.sale_id
            LEFT JOIN customers c ON c.id = s.customer_id
            JOIN stores st ON st.id = s.store_id
            JOIN users u ON u.id = r.user_id
            WHERE r.id=%s AND r.business_id=%s
        """, (return_id, business_id))
    
        ret = cursor.fetchone()
    
        cursor.execute("""
            SELECT ri.quantity, ri.price, p.name
            FROM return_items ri
            JOIN products p ON p.id = ri.product_id
            WHERE ri.return_id=%s
        """, (return_id,))
    
        items = cursor.fetchall()
    
        return render_template("return_document.html", ret=ret, items=items)
    
    
    # -------------------- ROUTE: Generate PDF
    @app.route("/returns/document/<int:return_id>/pdf")
    @login_required
    def return_document_pdf(return_id):
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        cursor.execute("""
            SELECT 
                r.id,
                r.created_at AS date,
                r.reference,
                r.total_refund,
                s.id AS invoice_number,
                c.name AS customer_name,
                st.name AS store_name,
                u.name AS user_name
            FROM returns r
            JOIN sales s ON s.id = r.sale_id
            LEFT JOIN customers c ON c.id = s.customer_id
            JOIN stores st ON st.id = s.store_id
            JOIN users u ON u.id = r.user_id
            WHERE r.id=%s AND r.business_id=%s
        """, (return_id, business_id))
    
        ret = cursor.fetchone()
    
        cursor.execute("""
            SELECT ri.quantity, ri.price, p.name
            FROM return_items ri
            JOIN products p ON p.id = ri.product_id
            WHERE ri.return_id=%s
        """, (return_id,))
    
        items = cursor.fetchall()
    
        html = render_template("return_document.html", ret=ret, items=items)
        pdf = generate_pdf(html)
    
        return pdf








    # -------------------------
    # STOCK TRANSFER
    # -------------------------
    @app.route("/stock-transfer", methods=["GET", "POST"])
    @login_required
    def stock_transfer():
        business_id = session["user"]["business_id"]
        user_id = session["user"]["id"]   # <-- REQUIRED
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        cursor.execute("SELECT * FROM products WHERE business_id=%s", (business_id,))
        products_list = cursor.fetchall()
    
        cursor.execute("SELECT * FROM stores WHERE business_id=%s", (business_id,))
        stores_list = cursor.fetchall()
    
        if request.method == "POST":
            product_id = request.form["product_id"]
            from_store = request.form["from_store"]
            to_store = request.form["to_store"]
            quantity = int(request.form["quantity"])
    
            if from_store == to_store:
                flash("Source and destination store cannot be the same", "danger")
                return redirect(url_for("stock_transfer"))
    
            # FIXED ARGUMENT ORDER
            transfer_stock(
                product_id,
                user_id,        # <-- MUST BE SECOND
                from_store,
                to_store,
                quantity,
                business_id
            )
    
            flash("Stock transferred successfully", "success")
            return redirect(url_for("stock_transfer"))
    
        return render_template("stock_transfer.html", products=products_list, stores=stores_list)


# -------------------------
# SALES (WITH FILTERS)
# -------------------------
    @app.route("/sales", methods=["GET"])
    @login_required
    def sales():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # -------------------------
        # LOAD DROPDOWNS
        # -------------------------
        cursor.execute("SELECT * FROM products WHERE business_id=%s", (business_id,))
        products_list = cursor.fetchall()
    
        cursor.execute("SELECT * FROM customers WHERE business_id=%s", (business_id,))
        customers_list = cursor.fetchall()
    
        cursor.execute("SELECT * FROM stores WHERE business_id=%s", (business_id,))
        stores_list = cursor.fetchall()
    
        # -------------------------
        # FILTERS
        # -------------------------
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        product_name = request.args.get("product_name")
    
        query = """
            SELECT s.*, 
                   c.name AS customer_name,
                   st.name AS store_name
            FROM sales s
            LEFT JOIN customers c ON s.customer_id = c.id
            LEFT JOIN stores st ON s.store_id = st.id
            WHERE s.business_id = %s
        """
        params = [business_id]
    
        # DATE FILTERS
        if start_date:
            query += " AND DATE(s.created_at) >= %s"
            params.append(start_date)
    
        if end_date:
            query += " AND DATE(s.created_at) <= %s"
            params.append(end_date)
    
        # PRODUCT FILTER (multi-item)
        if product_name:
            query += """
                AND s.id IN (
                    SELECT si.sale_id
                    FROM sale_items si
                    JOIN products p ON si.product_id = p.id
                    WHERE p.name LIKE %s
                )
            """
            params.append(f"%{product_name}%")
    
        query += " ORDER BY s.created_at DESC LIMIT 200"
    
        cursor.execute(query, params)
        sales_list = cursor.fetchall()
    
        return render_template(
            "sales.html",
            products=products_list,
            customers=customers_list,
            stores=stores_list,
            sales=sales_list
        )
        
    #------------Load POS----------
    @app.route("/pos_page")
    @login_required
    def pos_page():
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        business_id = session["user"]["business_id"]
    
        cursor.execute("""
            SELECT id, name, price 
            FROM products 
            WHERE business_id = %s
            ORDER BY name ASC
        """, (business_id,))
        products = cursor.fetchall()
    
        return render_template("POS.html", products=products) 
    
    #----------Process POS----------
    @app.route("/pos_process_sale", methods=["POST"])
    @login_required
    def pos_process_sale():
        import json
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        try:
            # -------------------------
            # CART
            # -------------------------
            cart_json = request.form.get("cart_data")
            if not cart_json:
                raise Exception("Cart is empty")
    
            cart = json.loads(cart_json)
            if len(cart) == 0:
                raise Exception("Cart is empty")
    
            # -------------------------
            # PAYMENT DETAILS
            # -------------------------
            payment_method = request.form.get("payment_method")
            amount_paid = float(request.form.get("amount_paid") or 0)
            change_due = request.form.get("change_due") or "0"
    
            # -------------------------
            # BUSINESS + STORE
            # -------------------------
            business_id = session["user"]["business_id"]
            store_id = session["user"].get("store_id", None)
            user_id = session["user"]["id"]
    
            # -------------------------
            # TOTALS
            # -------------------------
            subtotal = sum(item["price"] * item["qty"] for item in cart)
            vat_amount = subtotal * 0.15
            total_amount = subtotal + vat_amount
    
            # -------------------------
            # INSERT SALE
            # -------------------------
            cursor.execute("""
                INSERT INTO sales (business_id, store_id, subtotal, vat_amount, total_amount, payment_method)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (business_id, store_id, subtotal, vat_amount, total_amount, payment_method))
            db.commit()
    
            sale_id = cursor.lastrowid
    
            # -------------------------
            # INSERT ITEMS
            # -------------------------
            for item in cart:
                line_total = item["price"] * item["qty"]
    
                cursor.execute("""
                    INSERT INTO sale_items (sale_id, product_id, quantity, price, line_total)
                    VALUES (%s, %s, %s, %s, %s)
                """, (sale_id, item["id"], item["qty"], item["price"], line_total))
    
            db.commit()
    
            return redirect(f"/pos_invoice/{sale_id}")
    
        except Exception as e:
            db.rollback()
            print("POS ERROR:", e)
            flash(str(e), "danger")
            return redirect("/pos_page")
        
    #-----------Bookkeeping Main-------------
    from flask import request, render_template, flash, redirect
    from datetime import date, datetime
    import decimal

    @app.route("/reports", methods=["GET"])
    @login_required
    def reports():
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        business_id = session["user"]["business_id"]
    
        # --------- DATE FILTERS ----------
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        store_id = request.args.get("store_id")
    
        if not start_date or not end_date:
            today = date.today()
            start_date = today.replace(day=1).isoformat()
            end_date = today.isoformat()
    
        # --------- STORES LIST ----------
        cursor.execute("""
            SELECT id, name 
            FROM stores 
            WHERE business_id = %s
        """, (business_id,))
        stores = cursor.fetchall()
    
        store_filter_sql = ""
        store_filter_params = []
        if store_id:
            store_filter_sql = " AND s.store_id = %s "
            store_filter_params.append(store_id)
    
        # ================================
        # 1) INCOME STATEMENT
        # ================================
    
        # Total Sales
        cursor.execute(f"""
            SELECT IFNULL(SUM(s.total_amount), 0) AS total_sales
            FROM sales s
            WHERE s.business_id = %s
              AND DATE(s.created_at) BETWEEN %s AND %s
              {store_filter_sql}
        """, (business_id, start_date, end_date, *store_filter_params))
        row_sales = cursor.fetchone()
        total_sales = row_sales["total_sales"]
    
        # COGS (simple version: sum wholesale * qty)
        cursor.execute(f"""
            SELECT IFNULL(SUM(p.wholesale_price * si.quantity), 0) AS cogs
            FROM sale_items si
            JOIN sales s ON si.sale_id = s.id
            JOIN products p ON si.product_id = p.id
            WHERE s.business_id = %s
              AND DATE(s.created_at) BETWEEN %s AND %s
              {store_filter_sql}
        """, (business_id, start_date, end_date, *store_filter_params))
        row_cogs = cursor.fetchone()
        cogs = row_cogs["cogs"]
    
        gross_profit = total_sales - cogs
    
        # Operating Expenses (assuming expenses table)
        cursor.execute("""
            SELECT IFNULL(SUM(amount), 0) AS expenses
            FROM expenses
            WHERE business_id = %s
              AND DATE(expense_date) BETWEEN %s AND %s
        """, (business_id, start_date, end_date))
        row_exp = cursor.fetchone()
        expenses = row_exp["expenses"]
    
        net_profit = gross_profit - expenses
    
        income = {
            "total_sales": round(total_sales, 2),
            "cogs": round(cogs, 2),
            "gross_profit": round(gross_profit, 2),
            "expenses": round(expenses, 2),
            "net_profit": round(net_profit, 2),
        }
    
        # ================================
        # 2) BALANCE SHEET
        # ================================
    
        # Cash (simple: sum of cash movements or just a placeholder)
        cursor.execute("""
            SELECT IFNULL(SUM(amount), 0) AS cash
            FROM cash_movements
            WHERE business_id = %s
        """, (business_id,))
        row_cash = cursor.fetchone()
        cash = row_cash["cash"]
    
        # Inventory value (retail or cost)
        cursor.execute("""
            SELECT IFNULL(SUM(i.quantity * p.wholesale_price), 0) AS inventory_value
            FROM inventory i
            JOIN products p ON p.id = i.product_id
            WHERE p.business_id = %s
        """, (business_id,))
        row_inv = cursor.fetchone()
        inventory_value = row_inv["inventory_value"]
    
        # Receivables (customers owing)
        cursor.execute("""
            SELECT IFNULL(SUM(balance), 0) AS receivables
            FROM customers
            WHERE business_id = %s
        """, (business_id,))
        row_rec = cursor.fetchone()
        receivables = row_rec["receivables"]
    
        # Payables (suppliers owing)
        cursor.execute("""
            SELECT IFNULL(SUM(balance), 0) AS payables
            FROM suppliers
            WHERE business_id = %s
        """, (business_id,))
        row_pay = cursor.fetchone()
        payables = row_pay["payables"]
    
        # Loans (simple table)
        cursor.execute("""
            SELECT IFNULL(SUM(outstanding_amount), 0) AS loans
            FROM loans
            WHERE business_id = %s
        """, (business_id,))
        row_loans = cursor.fetchone()
        loans = row_loans["loans"]
    
        # Equity (very simplified: assets - liabilities)
        total_assets = cash + inventory_value + receivables
        total_liabilities = payables + loans
        equity = total_assets - total_liabilities
    
        balance = {
            "cash": round(cash, 2),
            "inventory": round(inventory_value, 2),
            "receivables": round(receivables, 2),
            "payables": round(payables, 2),
            "loans": round(loans, 2),
            "equity": round(equity, 2),
        }
    
        # ================================
        # 3) CASH FLOW
        # ================================
    
        # Cash inflows: sales received (simplified)
        cursor.execute(f"""
            SELECT IFNULL(SUM(s.total_amount), 0) AS inflows
            FROM sales s
            WHERE s.business_id = %s
              AND DATE(s.created_at) BETWEEN %s AND %s
              {store_filter_sql}
        """, (business_id, start_date, end_date, *store_filter_params))
        row_in = cursor.fetchone()
        inflows = row_in["inflows"]
    
        # Cash outflows: expenses + purchases (simplified)
        cursor.execute("""
            SELECT IFNULL(SUM(amount), 0) AS exp_out
            FROM expenses
            WHERE business_id = %s
              AND DATE(expense_date) BETWEEN %s AND %s
        """, (business_id, start_date, end_date))
        row_exp_out = cursor.fetchone()
        exp_out = row_exp_out["exp_out"]
    
        cursor.execute("""
            SELECT IFNULL(SUM(total_amount), 0) AS purchases_out
            FROM purchases
            WHERE business_id = %s
              AND DATE(purchase_date) BETWEEN %s AND %s
        """, (business_id, start_date, end_date))
        row_pur_out = cursor.fetchone()
        pur_out = row_pur_out["purchases_out"]
    
        outflows = exp_out + pur_out
        net_cash = inflows - outflows
    
        cashflow = {
            "inflows": round(inflows, 2),
            "outflows": round(outflows, 2),
            "net": round(net_cash, 2),
        }
    
        # ================================
        # 4) INVENTORY & COGS BLOCK
        # ================================
    
        # Opening stock (assume stored in a table or approximate)
        cursor.execute("""
            SELECT IFNULL(SUM(opening_qty * p.wholesale_price), 0) AS opening_stock
            FROM opening_stock os
            JOIN products p ON p.id = os.product_id
            WHERE os.business_id = %s
        """, (business_id,))
        row_open = cursor.fetchone()
        opening_stock = row_open["opening_stock"]
    
        # Purchases in period
        cursor.execute("""
            SELECT IFNULL(SUM(pi.quantity * pi.cost_price), 0) AS purchases
            FROM purchase_items pi
            JOIN purchases pu ON pi.purchase_id = pu.id
            WHERE pu.business_id = %s
              AND DATE(pu.purchase_date) BETWEEN %s AND %s
        """, (business_id, start_date, end_date))
        row_pur = cursor.fetchone()
        purchases = row_pur["purchases"]
    
        # Closing stock (current inventory)
        closing_stock = inventory_value
    
        cogs_calc = opening_stock + purchases - closing_stock
    
        cogs_block = {
            "opening_stock": round(opening_stock, 2),
            "purchases": round(purchases, 2),
            "closing_stock": round(closing_stock, 2),
            "cogs": round(cogs_calc, 2),
        }
    
        return render_template(
            "reports.html",
            start_date=start_date,
            end_date=end_date,
            stores=stores,
            store_id=int(store_id) if store_id else None,
            income=income,
            balance=balance,
            cashflow=cashflow,
            cogs=cogs_block,
        )
        
    #-----------Bookeeping EXT data----------
    @app.route("/reports/import", methods=["POST"])
    @login_required
    def reports_import():
        db = get_db()
        cursor = db.cursor(dictionary=True)
        business_id = session["user"]["business_id"]
    
        file = request.files.get("file")
        if not file:
            flash("No file selected", "danger")
            return redirect("/reports")
    
        filename = file.filename.lower()
        if not (filename.endswith(".csv") or filename.endswith(".xlsx")):
            flash("Only CSV or Excel files are supported", "danger")
            return redirect("/reports")
    
        # For now, just store file metadata in a table for later processing
        cursor.execute("""
            INSERT INTO imports (business_id, filename, uploaded_at)
            VALUES (%s, %s, NOW())
        """, (business_id, filename))
        db.commit()
    
        flash("File uploaded successfully. Processing logic can be added later.", "success")
        return redirect("/reports")
    
    #-----------Bookeeping Journal-----------
    @app.route("/reports/journal", methods=["POST"])
    @login_required
    def reports_journal():
        db = get_db()
        cursor = db.cursor(dictionary=True)
        business_id = session["user"]["business_id"]
    
        date_str = request.form.get("date")
        description = request.form.get("description")
        debit_account = request.form.get("debit_account")
        credit_account = request.form.get("credit_account")
        debit_amount = float(request.form.get("debit_amount") or 0)
        credit_amount = float(request.form.get("credit_amount") or 0)
    
        if abs(debit_amount - credit_amount) > 0.0001:
            flash("Debit and credit must be equal for a balanced journal entry.", "danger")
            return redirect("/reports")
    
        try:
            cursor.execute("""
                INSERT INTO journal_entries 
                    (business_id, entry_date, description, debit_account, credit_account, amount)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (business_id, date_str, description, debit_account, credit_account, debit_amount))
            db.commit()
            flash("Journal entry posted successfully.", "success")
        except Exception as e:
            db.rollback()
            print("JOURNAL ERROR:", e)
            flash("Error posting journal entry: " + str(e), "danger")
    
        return redirect("/reports")
    
    #-----------Load permissions, branding, configa---#
    def get_permissions(user_id):
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_permissions WHERE user_id = %s", (user_id,))
        return cursor.fetchone()
    

    def get_branding(business_id):
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM business_branding WHERE business_id = %s", (business_id,))
        row = cursor.fetchone()
        return row
    
    
    def get_config(business_id):
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM business_config WHERE business_id = %s", (business_id,))
        row = cursor.fetchone()
        return row
    
    #--------------MAIN SETTINGS PAGE ROUTE
    @app.route("/settings")
    @login_required
    def settings_page():
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # ⭐ Do NOT load the owner
        cursor.execute("""
            SELECT * FROM users 
            WHERE business_id=%s AND role != 'owner'
        """, (session["user"]["business_id"],))
        users = cursor.fetchall()
    
        cursor.execute("SELECT * FROM branding WHERE business_id=%s", (session["user"]["business_id"],))
        branding = cursor.fetchone()
    
        cursor.execute("SELECT * FROM business_config WHERE business_id=%s", (session["user"]["business_id"],))
        config = cursor.fetchone()
    
        return render_template("settings.html", users=users, branding=branding, config=config)

        
     #----------SAVE USER PERMISSIONS
    @app.route("/settings/permissions", methods=["POST"])
    @login_required
    def settings_permissions():
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        user_id = request.form.get("user_id")
    
        fields = [
            "can_view_dashboard",
            "can_view_products",
            "can_view_customers",
            "can_view_sales",
            "can_view_finances",
            "can_view_visuals",
            "can_view_stores",
            "can_view_stock_in",
            "can_view_stock_transfer",
            "can_view_movements",
            "can_view_gallery",
            "can_view_settings"
        ]
    
        values = [request.form.get(f) for f in fields]
    
        # Check if permissions exist
        cursor.execute("SELECT id FROM user_permissions WHERE user_id = %s", (user_id,))
        exists = cursor.fetchone()
    
        if exists:
            # Update
            sql = f"""
                UPDATE user_permissions SET 
                {", ".join([f"{f}=%s" for f in fields])}
                WHERE user_id = %s
            """
            cursor.execute(sql, (*values, user_id))
        else:
            # Insert
            sql = f"""
                INSERT INTO user_permissions 
                (user_id, {", ".join(fields)})
                VALUES (%s, {", ".join(["%s"] * len(fields))})
            """
            cursor.execute(sql, (user_id, *values))
    
        db.commit()
        flash("Permissions updated successfully.", "success")
        return redirect("/settings")
    
   
    #-----------SAVE BRANDING (LOGO + COLORS + BUSINESS NAME)    
  

    @app.route("/settings/branding", methods=["POST"])
    @login_required
    def settings_branding():
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        business_id = session["user"]["business_id"]
    
        business_name = request.form.get("business_name")
        primary_color = request.form.get("primary_color")
        secondary_color = request.form.get("secondary_color")
    
        logo_file = request.files.get("logo")
        logo_path = None
    
        if logo_file and logo_file.filename:
            filename = secure_filename(logo_file.filename)
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            logo_file.save(save_path)
            logo_path = f"/static/uploads/logos/{filename}"
    
        # Check if branding exists
        cursor.execute("SELECT id FROM business_branding WHERE business_id = %s", (business_id,))
        exists = cursor.fetchone()
    
        if exists:
            if logo_path:
                cursor.execute("""
                    UPDATE business_branding
                    SET business_name=%s, primary_color=%s, secondary_color=%s, logo_path=%s
                    WHERE business_id=%s
                """, (business_name, primary_color, secondary_color, logo_path, business_id))
            else:
                cursor.execute("""
                    UPDATE business_branding
                    SET business_name=%s, primary_color=%s, secondary_color=%s
                    WHERE business_id=%s
                """, (business_name, primary_color, secondary_color, business_id))
        else:
            cursor.execute("""
                INSERT INTO business_branding (business_id, business_name, primary_color, secondary_color, logo_path)
                VALUES (%s, %s, %s, %s, %s)
            """, (business_id, business_name, primary_color, secondary_color, logo_path))
    
        db.commit()
        flash("Branding updated successfully.", "success")
        return redirect("/settings")
    
    
    #-------------SAVE BUSINESS CONFIGURATION
    @app.route("/settings/config", methods=["POST"])
    @login_required
    def settings_config():
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        business_id = session["user"]["business_id"]
    
        vat_percentage = request.form.get("vat_percentage")
        currency = request.form.get("currency")
        invoice_prefix = request.form.get("invoice_prefix")
        enable_vat = request.form.get("enable_vat")
    
        cursor.execute("SELECT id FROM business_config WHERE business_id = %s", (business_id,))
        exists = cursor.fetchone()
    
        if exists:
            cursor.execute("""
                UPDATE business_config
                SET vat_percentage=%s, currency=%s, invoice_prefix=%s, enable_vat=%s
                WHERE business_id=%s
            """, (vat_percentage, currency, invoice_prefix, enable_vat, business_id))
        else:
            cursor.execute("""
                INSERT INTO business_config (business_id, vat_percentage, currency, invoice_prefix, enable_vat)
                VALUES (%s, %s, %s, %s, %s)
            """, (business_id, vat_percentage, currency, invoice_prefix, enable_vat))
    
        db.commit()
        flash("Business configuration updated successfully.", "success")
        return redirect("/settings")








    
    
        
    #------------POS Invoice---------
    @app.route("/pos_invoice/<int:sale_id>")
    @login_required
    def pos_invoice(sale_id):
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        cursor.execute("""
            SELECT s.*, 
                   st.name AS store_name
            FROM sales s
            LEFT JOIN stores st ON s.store_id = st.id
            WHERE s.id = %s
        """, (sale_id,))
        sale = cursor.fetchone()
    
        cursor.execute("""
            SELECT si.*, p.name AS product_name
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            WHERE si.sale_id = %s
        """, (sale_id,))
        items = cursor.fetchall()
    
        cashier_name = session["user"]["name"]
    
        return render_template(
            "invoice.html",
            sale_id=sale_id,
            sale=sale,
            items=items,
            subtotal=sale["subtotal"],
            vat_amount=sale["vat_amount"],
            total_amount=sale["total_amount"],
            cashier_name=cashier_name
        )   

    # -------------------------
    # STOCK MOVEMENTS HISTORY (optional view)
    # -------------------------
    @app.route("/movements")
    @login_required
    def stock_movements():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # -------------------------
        # PRODUCTS FOR DROPDOWN
        # -------------------------
        cursor.execute("""
            SELECT name 
            FROM products 
            WHERE business_id=%s 
            ORDER BY name ASC
        """, (business_id,))
        products = cursor.fetchall()
    
        # -------------------------
        # FILTERS
        # -------------------------
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        product_name = request.args.get("product_name")
    
        # -------------------------
        # BASE QUERY
        # -------------------------
        query = """
            SELECT sm.*,
                   p.name AS product_name,
                   u.name AS user_name,
                   fs.name AS from_store_name,
                   ts.name AS to_store_name,
                   sm.sale_id
            FROM stock_movements sm
            LEFT JOIN products p ON sm.product_id = p.id
            LEFT JOIN users u ON sm.user_id = u.id
            LEFT JOIN stores fs ON sm.from_store_id = fs.id
            LEFT JOIN stores ts ON sm.to_store_id = ts.id
        """
    
        conditions = ["sm.business_id = %s"]
        params = [business_id]
    
        # -------------------------
        # APPLY FILTERS
        # -------------------------
    
        if start_date:
            conditions.append("DATE(sm.created_at) >= %s")
            params.append(start_date)
    
        if end_date:
            conditions.append("DATE(sm.created_at) <= %s")
            params.append(end_date)
    
        if product_name:
            conditions.append("p.name LIKE %s")
            params.append(f"%{product_name}%")
    
        # Final query
        query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY sm.created_at DESC LIMIT 200"
    
        cursor.execute(query, params)
        movements = cursor.fetchall()
    
        return render_template(
            "stock_movements.html",
            products=products,
            movements=movements
        )
    
    # -------------------------
    # CUSTOMERS
    # -------------------------
    @app.route("/customers", methods=["GET", "POST"])
    @login_required
    def customers():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)

        if request.method == "POST":
            name = request.form["name"]
            email = request.form.get("email")
            phone = request.form.get("phone")
            cursor.execute("""
                INSERT INTO customers (business_id, name, email, phone)
                VALUES (%s, %s, %s, %s)
            """, (business_id, name, email, phone))
            db.commit()
            return redirect(url_for("customers"))

        cursor.execute("SELECT * FROM customers WHERE business_id=%s", (business_id,))
        data = cursor.fetchall()
        return render_template("customers.html", customers=data)

    # -------------------------
    # SETTINGS
    # -------------------------
    #@app.route("/settings")
    #@login_required
    #def settings():
        #return render_template("settings.html")

    # -------------------------
    # GALLERY
    # -------------------------
    @app.route("/gallery", methods=["GET", "POST"])
    @login_required
    def gallery():
        db = get_db()
        cursor = db.cursor(dictionary=True)
        business_id = session["user"]["business_id"]
    
        # -------------------------
        # HANDLE FILE UPLOAD
        # -------------------------
        if request.method == "POST":
            if "file" not in request.files:
                flash("No file part", "danger")
                return redirect(request.url)
    
            file = request.files["file"]
    
            if file.filename == "":
                flash("No selected file", "danger")
                return redirect(request.url)
    
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
    
                # Ensure upload folder exists
                os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)
    
                cursor.execute("""
                    INSERT INTO gallery (business_id, filename)
                    VALUES (%s, %s)
                """, (business_id, filename))
                db.commit()
    
                flash("File uploaded successfully", "success")
                return redirect(url_for("gallery"))
    
        # -------------------------
        # FETCH FILES (ALWAYS RUNS)
        # -------------------------
        cursor.execute("""
            SELECT * FROM gallery
            WHERE business_id=%s
            ORDER BY created_at DESC
        """, (business_id,))
        
        files = cursor.fetchall()
    
        return render_template("gallery.html", files=files)
    
    # -------------------------
    # FINANCES PAGE
    # -------------------------
    @app.route("/finances")
    @login_required
    def finances():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # -------------------------
        # FILTERS
        # -------------------------
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
    
        # -------------------------
        # SALES CALCULATIONS (with date filters)
        # -------------------------
        sales_query = """
            SELECT IFNULL(SUM(total_amount),0) AS total_sales,
                   COUNT(*) AS total_units,
                   IFNULL(AVG(total_amount),0) AS avg_sale_value
            FROM sales
            WHERE business_id=%s
        """
    
        params = [business_id]
    
        if start_date:
            sales_query += " AND DATE(created_at) >= %s"
            params.append(start_date)
    
        if end_date:
            sales_query += " AND DATE(created_at) <= %s"
            params.append(end_date)
    
        cursor.execute(sales_query, params)
        sales_stats = cursor.fetchone()
    
        # -------------------------
        # PROFIT MARGINS
        # -------------------------
        cursor.execute("""
            SELECT id, name, price, wholesale_price
            FROM products
            WHERE business_id=%s
        """, (business_id,))
        rows = cursor.fetchall()
    
        margins = []
        for r in rows:
            price = r["price"] or 0
            wholesale = r["wholesale_price"] or 0
    
            margin_value = price - wholesale
            margin_percent = (margin_value / wholesale * 100) if wholesale else 0
    
            margins.append({
                "name": r["name"],
                "price": price,
                "wholesale_price": wholesale,
                "margin_value": margin_value,
                "margin_percent": margin_percent
            })
    
        # -------------------------
        # STOCK VALUATION
        # -------------------------
        cursor.execute("""
            SELECT p.id, p.name, p.price, p.wholesale_price,
                   IFNULL(SUM(i.quantity),0) AS total_quantity
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            WHERE p.business_id=%s
            GROUP BY p.id
        """, (business_id,))
        stock_rows = cursor.fetchall()
    
        stock_value = []
        total_wholesale_value = 0
        total_retail_value = 0
    
        for row in stock_rows:
            wholesale_price = row["wholesale_price"] or 0
            price = row["price"] or 0
            qty = row["total_quantity"] or 0
    
            wholesale_total = qty * wholesale_price
            retail_total = qty * price
    
            total_wholesale_value += wholesale_total
            total_retail_value += retail_total
    
            stock_value.append({
                "name": row["name"],
                "total_quantity": row["total_quantity"],
                "wholesale_total": wholesale_total,
                "retail_total": retail_total
            })
    
        # -------------------------
        # PRODUCTS FOR SUPPLIER ORDERING
        # -------------------------
        cursor.execute("SELECT id, name FROM products WHERE business_id=%s", (business_id,))
        products = cursor.fetchall()
    
        # -------------------------
        # FINAL DATA PACKAGE
        # -------------------------
        finances_data = {
            "total_sales": sales_stats["total_sales"],
            "total_units": sales_stats["total_units"],
            "avg_sale_value": sales_stats["avg_sale_value"],
            "margins": margins,
            "stock_value": stock_value,
            "total_wholesale_value": total_wholesale_value,
            "total_retail_value": total_retail_value,
            "products": products
        }
    
        return render_template(
            "finances.html",
            finances=finances_data,
            start_date=start_date,
            end_date=end_date
        )
    
#---------------VISUALS--------------------------
    @app.route("/visuals", methods=["GET", "POST"])
    @login_required
    def visuals():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # Date filters
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
    
        if not start_date or not end_date:
            cursor.execute("SELECT DATE_SUB(CURDATE(), INTERVAL 30 DAY) AS d")
            start_date = cursor.fetchone()["d"]
            end_date = date.today()
    
        # PRODUCTS SUMMARY
        cursor.execute("""
            SELECT COUNT(*) AS total_products
            FROM products
            WHERE business_id=%s
        """, (business_id,))
        products_summary = cursor.fetchone()
    
        # SALES SUMMARY + TIME SERIES
        cursor.execute("""
            SELECT IFNULL(SUM(total_amount),0) AS total_sales,
                   IFNULL(COUNT(*),0) AS total_transactions
            FROM sales
            WHERE business_id=%s AND DATE(created_at) BETWEEN %s AND %s
        """, (business_id, start_date, end_date))
        sales_summary = cursor.fetchone()
    
        cursor.execute("""
            SELECT DATE(created_at) AS day, SUM(total_amount) AS total
            FROM sales
            WHERE business_id=%s AND DATE(created_at) BETWEEN %s AND %s
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at)
        """, (business_id, start_date, end_date))
        sales_timeseries = cursor.fetchall()
    
        # STORES SUMMARY
        cursor.execute("""
            SELECT COUNT(*) AS total_stores
            FROM stores
            WHERE business_id=%s
        """, (business_id,))
        stores_summary = cursor.fetchone()
    
        # ⭐ TOTAL PROFIT (replaces customers)
        cursor.execute("""
            SELECT 
                IFNULL(SUM(s.total_amount), 0) AS total_sales,
                IFNULL(SUM(p.wholesale_price * si.quantity), 0) AS total_cost
            FROM sales s
            LEFT JOIN sale_items si ON s.id = si.sale_id
            LEFT JOIN products p ON si.product_id = p.id
            WHERE s.business_id = %s
              AND DATE(s.created_at) BETWEEN %s AND %s
        """, (business_id, start_date, end_date))
    
        profit_row = cursor.fetchone()
        total_profit = profit_row["total_sales"] - profit_row["total_cost"]
    
        # FINANCES SUMMARY
        cursor.execute("""
            SELECT IFNULL(SUM(i.quantity * p.wholesale_price),0) AS wholesale_value,
                   IFNULL(SUM(i.quantity * p.price),0) AS retail_value
            FROM inventory i
            JOIN products p ON p.id = i.product_id
            WHERE p.business_id=%s
        """, (business_id,))
        finances_summary = cursor.fetchone()
    
        data = {
            "products": products_summary,
            "sales": sales_summary,
            "stores": stores_summary,
            "total_profit": total_profit,   # ⭐ FIXED
            "finances": finances_summary,
            "sales_timeseries": sales_timeseries,
            "start_date": start_date,
            "end_date": end_date
        }
    
        return render_template("visuals.html", data=data)
    
    
    #-------------invoice--------


# Correct wkhtmltopdf configuration (must be an object, not a dict)
    path_wkhtmltopdf = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

    if not os.path.exists(path_wkhtmltopdf):
        raise Exception("wkhtmltopdf NOT FOUND. Check installation path.")

    config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
   


   


# ---------- RECORD SALE ROUTE ----------
    @app.route("/record_sale", methods=["POST"])
    @login_required
    def record_sale():
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        try:
            business_id = session["user"]["business_id"]
            cashier_name = session["user"]["name"]
            user_id = session["user"]["id"]   # FIXED
    
            product_ids = request.form.getlist("product_id[]")
            quantities = request.form.getlist("quantity[]")
            customer_id = request.form.get("customer_id") or None
            store_id = int(request.form.get("store_id") or 0)
    
            items = []
            total_amount = 0.0
    
            # -------------------------
            # BUILD SALE ITEMS
            # -------------------------
            for pid_raw, qty_raw in zip(product_ids, quantities):
    
                if not pid_raw or not pid_raw.isdigit():
                    continue
    
                product_id = int(pid_raw)
                quantity = int(qty_raw or 0)
    
                if quantity <= 0:
                    continue
    
                cursor.execute("SELECT name, price FROM products WHERE id=%s", (product_id,))
                product = cursor.fetchone()
    
                if not product:
                    continue
    
                price = float(product["price"])
                line_total = price * quantity
                total_amount += line_total
    
                items.append({
                    "product_id": product_id,
                    "quantity": quantity,
                    "price": price,
                    "line_total": line_total
                })
    
            if not items:
                raise Exception("No valid sale items")
    
            # VAT calculations
            vat_rate = 0.15
            subtotal = total_amount / (1 + vat_rate)
            vat_amount = total_amount - subtotal
    
            # -------------------------
            # INSERT SALE
            # -------------------------
            cursor.execute("""
                INSERT INTO sales (business_id, customer_id, store_id, subtotal, vat_amount, total_amount)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (business_id, customer_id, store_id, subtotal, vat_amount, total_amount))
    
            db.commit()
            sale_id = cursor.lastrowid
    
            # -------------------------
            # INSERT ITEMS + REDUCE STOCK
            # -------------------------
            for item in items:
                cursor.execute("""
                    INSERT INTO sale_items (sale_id, product_id, quantity, price, line_total)
                    VALUES (%s, %s, %s, %s, %s)
                """, (sale_id, item["product_id"], item["quantity"], item["price"], item["line_total"]))
    
                reduce_stock_on_sale(
                    item["product_id"],
                    user_id,
                    store_id,
                    item["quantity"],
                    business_id,
                    sale_id
                )
    
            db.commit()
    
            # -------------------------
            # GENERATE PDF + SAVE TO GALLERY
            # -------------------------
            cursor.execute("SELECT * FROM sales WHERE id=%s", (sale_id,))
            sale_data = cursor.fetchone()
    
            cursor.execute("""
                SELECT si.*, p.name 
                FROM sale_items si
                JOIN products p ON si.product_id = p.id
                WHERE si.sale_id=%s
            """, (sale_id,))
            sale_items = cursor.fetchall()
    
            sale_data["items"] = sale_items
    
            # Your existing PDF generator
            generate_invoice_for_sale(sale_id, sale_data)
            flash("Sale recorded successfully!", "success")    
            return redirect("/sales")
    
        except Exception as e:
            db.rollback()
            print("SALE ERROR:", e)
            flash(str(e), "danger")
            return redirect("/sales")

    
            # -------------------------
            # INSERT ITEMS + STOCK MOVEMENTS
            # -------------------------
            for item in items:
                cursor.execute("""
                    INSERT INTO sale_items (sale_id, product_id, quantity, price, line_total)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    sale_id,
                    item["product_id"],
                    item["quantity"],
                    item["price"],
                    item["line_total"]
                ))
    
                if store_id:
                    reduce_stock_on_sale(
                        item["product_id"],
                        user_id,
                        session["user_id"],
                        store_id,
                        item["quantity"],
                        business_id,
                        sale_id
                    )
    
            db.commit()
    
            # -------------------------
            # FETCH SALE DATA FOR INVOICE
            # -------------------------
            cursor.execute("SELECT * FROM sales WHERE id=%s", (sale_id,))
            sale_data = cursor.fetchone()
    
            cursor.execute("""
                SELECT si.*, p.name AS product_name
                FROM sale_items si
                LEFT JOIN products p ON si.product_id = p.id
                WHERE si.sale_id=%s
            """, (sale_id,))
            sale_data["items"] = cursor.fetchall()
    
            # -------------------------
            # GENERATE INVOICE PDF (using invoice.html)
            # -------------------------
            generate_invoice_for_sale(sale_id, sale_data)
    
            flash("Sale recorded successfully!", "success")
            return redirect("/sales")
    
        except Exception as e:
            db.rollback()
            print("SALE ERROR:", str(e))
            flash(str(e), "danger")
            return redirect("/sales")
        
    #--------------SALE SCANNER---------------
    @app.route("/check_barcode")
    @login_required
    def check_barcode():
        code = request.args.get("code")
        business_id = session["user"]["business_id"]
    
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        cursor.execute("""
            SELECT id, name, price
            FROM products
            WHERE barcode = %s AND business_id = %s
        """, (code, business_id))
    
        product = cursor.fetchone()
    
        if not product:
            return {"found": False}
    
        return {
            "found": True,
            "id": product["id"],
            "name": product["name"],
            "price": product["price"]
        }
        
    from decimal import Decimal

    @app.route("/invoice/<int:sale_id>")
    def invoice(sale_id):
        db = get_db()
        cursor = db.cursor(dictionary=True)
    
        # 1. GET SALE + CUSTOMER NAME
        cursor.execute("""
            SELECT s.*, 
                   c.name AS customer_name,
                   c.email AS customer_email,
                   c.phone AS customer_phone
            FROM sales s
            LEFT JOIN customers c ON s.customer_id = c.id
            WHERE s.id = %s
        """, (sale_id,))
        sale = cursor.fetchone()
    
        # 2. GET SALE ITEMS
        cursor.execute("""
            SELECT si.*, p.name AS product_name
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            WHERE si.sale_id = %s
        """, (sale_id,))
        items = cursor.fetchall()
    
        # 3. GET STORE NAME
        cursor.execute("SELECT name FROM stores WHERE id = %s", (sale["store_id"],))
        business_name = cursor.fetchone()["name"]
    
        # 4. GET CASHIER NAME FROM PROFILE (SESSION)
        cashier_name = session["user"]["name"]
    
        # 5. TOTALS (Decimal-safe)
        subtotal = sum(Decimal(item["price"]) * Decimal(item["quantity"]) for item in items)
        vat_amount = subtotal * Decimal("0.15")
        total_amount = subtotal + vat_amount
    
        return render_template(
            "invoice.html",
            sale_id=sale_id,
            sale=sale,
            items=items,
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_amount=total_amount,
            business_name=business_name,
            cashier_name=cashier_name
        )
        
     #Outlook
        @app.route("/email_invoice/<int:sale_id>")
        @login_required
        def email_invoice(sale_id):
            db = get_db()
            cursor = db.cursor(dictionary=True)
        
            # Get sale + items
            cursor.execute("SELECT * FROM sales WHERE id=%s", (sale_id,))
            sale_data = cursor.fetchone()
        
            cursor.execute("""
                SELECT si.*, p.name 
                FROM sale_items si
                JOIN products p ON si.product_id = p.id
                WHERE si.sale_id=%s
            """, (sale_id,))
            sale_items = cursor.fetchall()
        
            sale_data["items"] = sale_items
        
            # Generate PDF
            generate_invoice_for_sale(sale_id, sale_data)
            pdf_path = os.path.abspath(f"static/invoices/invoice_{sale_id}.pdf")
        
            # Get customer email
            cursor.execute("""
                SELECT c.email, c.name
                FROM sales s
                LEFT JOIN customers c ON s.customer_id = c.id
                WHERE s.id=%s
            """, (sale_id,))
            row = cursor.fetchone()
        
            customer_email = row["email"] if row else ""
            customer_name = row["name"] if row else "Customer"
        
            subject = f"Invoice #{sale_id}"
            body = f"Dear {customer_name},%0D%0A%0D%0APlease find your invoice attached.%0D%0A%0D%0ARegards,%0D%0A{session['user']['name']}"
        
            # Open Outlook with attachment
            os.system(f'start outlook.exe /a "{pdf_path}"')
        
            flash("Opening Outlook with invoice attached…", "success")
            return redirect("/sales")

        
        #Whatsapp
        @app.route("/whatsapp_invoice/<int:sale_id>")
        @login_required
        def whatsapp_invoice(sale_id):
            db = get_db()
            cursor = db.cursor(dictionary=True)
        
            # Get sale + items
            cursor.execute("SELECT * FROM sales WHERE id=%s", (sale_id,))
            sale_data = cursor.fetchone()
        
            cursor.execute("""
                SELECT si.*, p.name 
                FROM sale_items si
                JOIN products p ON si.product_id = p.id
                WHERE si.sale_id=%s
            """, (sale_id,))
            sale_items = cursor.fetchall()
        
            sale_data["items"] = sale_items
        
            # Generate PDF
            generate_invoice_for_sale(sale_id, sale_data)
            pdf_path = os.path.abspath(f"static/invoices/invoice_{sale_id}.pdf")
        
            # Get customer phone
            cursor.execute("""
                SELECT c.phone, c.name
                FROM sales s
                LEFT JOIN customers c ON s.customer_id = c.id
                WHERE s.id=%s
            """, (sale_id,))
            row = cursor.fetchone()
        
            phone = row["phone"] if row else ""
            customer_name = row["name"] if row else "Customer"
        
            message = f"Hello {customer_name}, your invoice #{sale_id} is ready."
        
            # Open WhatsApp Desktop
            os.system(f'start whatsapp://send?phone={phone}&text={message}')
        
            # Open PDF so user can drag-drop into WhatsApp
            os.system(f'start "" "{pdf_path}"')
        
            flash("Opening WhatsApp…", "success")
            return redirect("/sales")


    


    # -------------------------
    # SUPPLIER ORDER SUBMISSION
    # -------------------------
    @app.route("/supplier-order", methods=["POST"])
    @login_required
    def supplier_order():
        business_id = session["user"]["business_id"]
        product_id = request.form["product_id"]
        quantity = request.form["quantity"]
        supplier = request.form["supplier"]
    
        db = get_db()
        cursor = db.cursor()
    
        cursor.execute("""
            INSERT INTO supplier_orders (business_id, product_id, quantity, supplier)
            VALUES (%s, %s, %s, %s)
        """, (business_id, product_id, quantity, supplier))
        db.commit()
    
        flash("Supplier order placed successfully!", "success")
        return redirect(url_for("finances"))
    
    
    from flask import render_template
    from decimal import Decimal
    
    def generate_invoice_for_sale(sale_id, sale_data):
        try:
            # -------------------------
            # WKHTMLTOPDF SETUP
            # -------------------------
            path_wkhtmltopdf = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
    
            if not os.path.exists(path_wkhtmltopdf):
                raise Exception("wkhtmltopdf NOT FOUND")
    
            config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
    
            # -------------------------
            # PATH SETUP
            # -------------------------
            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            invoices_folder = os.path.join(BASE_DIR, "static", "invoices")
            os.makedirs(invoices_folder, exist_ok=True)
    
            filename = f"invoice_{sale_id}.pdf"
            output_path = os.path.join(invoices_folder, filename)
    
            # -------------------------
            # FETCH FULL SALE DATA (same as View Invoice)
            # -------------------------
            db = get_db()
            cursor = db.cursor(dictionary=True)
    
            # 1. SALE + CUSTOMER
            cursor.execute("""
                SELECT s.*,
                       c.name AS customer_name,
                       c.email AS customer_email,
                       c.phone AS customer_phone
                FROM sales s
                LEFT JOIN customers c ON s.customer_id = c.id
                WHERE s.id = %s
            """, (sale_id,))
            sale = cursor.fetchone()
    
            # 2. ITEMS
            cursor.execute("""
                SELECT si.*, p.name AS product_name
                FROM sale_items si
                JOIN products p ON si.product_id = p.id
                WHERE si.sale_id = %s
            """, (sale_id,))
            items = cursor.fetchall()
    
            # 3. STORE NAME
            cursor.execute("SELECT name FROM stores WHERE id = %s", (sale["store_id"],))
            store_row = cursor.fetchone()
            business_name = store_row["name"] if store_row else "Unknown Store"
    
            # 4. CASHIER NAME
            cashier_name = session["user"]["name"]
    
            # 5. TOTALS
            subtotal = sum(Decimal(i["price"]) * Decimal(i["quantity"]) for i in items)
            vat_amount = subtotal * Decimal("0.15")
            total_amount = subtotal + vat_amount
    
            # -------------------------
            # RENDER HTML (IDENTICAL TO VIEW INVOICE)
            # -------------------------
            html = render_template(
                "invoice.html",
                sale_id=sale_id,
                sale=sale,
                items=items,
                subtotal=subtotal,
                vat_amount=vat_amount,
                total_amount=total_amount,
                business_name=business_name,
                cashier_name=cashier_name
            )
    
            # -------------------------
            # GENERATE PDF
            # -------------------------
            pdfkit.from_string(html, output_path, configuration=config)
    
            print("✅ Invoice generated:", output_path)
    
            # -------------------------
            # SAVE TO GALLERY
            # -------------------------
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO gallery (business_id, filename)
                VALUES (%s, %s)
            """, (sale["business_id"], filename))
    
            db.commit()
    
            print("✅ Invoice saved to gallery DB")
    
            return output_path
    
        except Exception as e:
            print("❌ ERROR GENERATING INVOICE:", str(e))
            raise
    
   
    #--------------View Invoice-----------
    @app.route("/invoice/<int:sale_id>")
    @login_required
    def view_invoice(sale_id):
        import os
        from flask import send_file, flash, redirect, abort
    
        # Safe absolute path
        invoice_path = os.path.abspath(
            os.path.join("static", "invoices", f"invoice_{sale_id}.pdf")
        )
    
        print("LOOKING FOR INVOICE:", invoice_path)
    
        # Ensure file exists
        if not os.path.isfile(invoice_path):
            print("❌ FILE NOT FOUND")
            flash("Invoice PDF does not exist. Regenerate the sale.", "danger")
            return redirect("/sales")
    
        try:
            print("✅ FILE FOUND, SENDING...")
            return send_file(
                invoice_path,
                mimetype="application/pdf",
                as_attachment=False
            )
    
        except Exception as e:
            print("❌ ERROR SENDING FILE:", str(e))
            abort(500)  

    # -------------------------
    # UPLOADS (Serve files)
    # -------------------------
    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    # -------------------------
    # ERROR HANDLER
    # -------------------------
    @app.errorhandler(404)
    def not_found(e):
        return render_template("base.html", content="Page not found"), 404

    return app


# -----------------------------
# RUN APP
# -----------------------------
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)