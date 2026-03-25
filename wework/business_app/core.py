import os
import hashlib
from datetime import date
from datetime import date, datetime
from functools import wraps
from flask import jsonify
import pdfkit
from flask import send_file



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


def add_stock(product_id, store_id, quantity, business_id):
    db = get_db()
    cursor = db.cursor()

    inv_id = get_or_create_inventory(product_id, store_id)

    cursor.execute("""
        UPDATE inventory
        SET quantity = quantity + %s
        WHERE id=%s
    """, (quantity, inv_id))

    cursor.execute("""
        INSERT INTO stock_movements (product_id, business_id, to_store_id, quantity, movement_type)
        VALUES (%s, %s, %s, %s, 'stock_in')
    """, (product_id, business_id, store_id, quantity))

    db.commit()


def reduce_stock_on_sale(product_id, store_id, quantity, business_id, sale_id):
    db = get_db()
    cursor = db.cursor()

    inv_id = get_or_create_inventory(product_id, store_id)

    # Reduce stock
    cursor.execute("""
        UPDATE inventory
        SET quantity = quantity - %s
        WHERE id=%s
    """, (quantity, inv_id))

    # Record movement WITH sale_id (IMPORTANT)
    cursor.execute("""
        INSERT INTO stock_movements 
        (product_id, business_id, from_store_id, quantity, movement_type, sale_id)
        VALUES (%s, %s, %s, %s, 'sale', %s)
    """, (product_id, business_id, store_id, quantity, sale_id))

    db.commit()


def transfer_stock(product_id, from_store, to_store, quantity, business_id):
    db = get_db()
    cursor = db.cursor()

    from_inv = get_or_create_inventory(product_id, from_store)
    to_inv = get_or_create_inventory(product_id, to_store)

    cursor.execute("""
        UPDATE inventory SET quantity = quantity - %s WHERE id=%s
    """, (quantity, from_inv))

    cursor.execute("""
        UPDATE inventory SET quantity = quantity + %s WHERE id=%s
    """, (quantity, to_inv))

    cursor.execute("""
        INSERT INTO stock_movements (product_id, business_id, from_store_id, to_store_id, quantity, movement_type)
        VALUES (%s, %s, %s, %s, %s, 'transfer')
    """, (product_id, business_id, from_store, to_store, quantity))

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

            if user_type == "end_user":
                business_name = request.form["business_name"]
                cursor.execute("INSERT INTO businesses (name) VALUES (%s)", (business_name,))
                business_id = cursor.lastrowid

                cursor.execute("""
                    INSERT INTO users (business_id, name, email, password, role)
                    VALUES (%s, %s, %s, %s, 'owner')
                """, (business_id, name, email, password))

            elif user_type == "staff":
                business_id = request.form["business_id"]
                cursor.execute("""
                    INSERT INTO users (business_id, name, email, password, role)
                    VALUES (%s, %s, %s, %s, 'staff')
                """, (business_id, name, email, password))

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

        cursor.execute("SELECT COUNT(*) AS total_products FROM products WHERE business_id=%s", (business_id,))
        total_products = cursor.fetchone()["total_products"]

        cursor.execute("SELECT COUNT(*) AS total_customers FROM customers WHERE business_id=%s", (business_id,))
        total_customers = cursor.fetchone()["total_customers"]

        cursor.execute("SELECT IFNULL(SUM(total_amount),0) AS total_sales FROM sales WHERE business_id=%s", (business_id,))
        total_sales = cursor.fetchone()["total_sales"]

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

        return render_template(
            "dashboard.html",
            user=user,
            total_products=total_products,
            total_customers=total_customers,
            total_sales=total_sales,
            chart_labels=chart_labels,
            chart_values=chart_values
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
            add_stock(product_id, store_id, quantity, business_id)
            flash("Stock added successfully", "success")
            return redirect(url_for("stock_in"))

        return render_template("stock_in.html", products=products_list, stores=stores_list)

    # -------------------------
    # STOCK TRANSFER
    # -------------------------
    @app.route("/stock-transfer", methods=["GET", "POST"])
    @login_required
    def stock_transfer():
        business_id = session["user"]["business_id"]
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

            transfer_stock(product_id, from_store, to_store, quantity, business_id)
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
                   fs.name AS from_store_name,
                   ts.name AS to_store_name,
                   sm.sale_id
            FROM stock_movements sm
            LEFT JOIN products p ON sm.product_id = p.id
            LEFT JOIN stores fs ON sm.from_store_id = fs.id
            LEFT JOIN stores ts ON sm.to_store_id = ts.id
        """
    
        conditions = ["sm.business_id = %s"]
        params = [business_id]
    
        # -------------------------
        # APPLY FILTERS
        # -------------------------
    
        # Start Date
        if start_date:
            conditions.append("DATE(sm.created_at) >= %s")
            params.append(start_date)
    
        # End Date
        if end_date:
            conditions.append("DATE(sm.created_at) <= %s")
            params.append(end_date)
    
        # Product Name
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
    @app.route("/settings")
    @login_required
    def settings():
        return render_template("settings.html")

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
    # SALES CALCULATIONS
    # -------------------------
        cursor.execute("""
            SELECT IFNULL(SUM(total_amount),0) AS total_sales,
                   COUNT(*) AS total_units,
                   IFNULL(AVG(total_amount),0) AS avg_sale_value
            FROM sales
            WHERE business_id=%s
        """, (business_id,))
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
    
        return render_template("finances.html", finances=finances_data)
    
    
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
    
        # CUSTOMERS SUMMARY
        cursor.execute("""
            SELECT COUNT(*) AS total_customers
            FROM customers
            WHERE business_id=%s
        """, (business_id,))
        customers_summary = cursor.fetchone()
    
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
            "customers": customers_summary,
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
    
    #-------------Generate Invoice-----------


    from flask import render_template
    
    def generate_invoice_for_sale(sale_id, sale_data):
        """
        Generates a PDF invoice and saves it to disk,
        then records it in the gallery table.
        """
    
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
            # VALIDATE SALE DATA
            # -------------------------
            if not sale_data:
                raise Exception("Sale data is missing")
    
            if "business_id" not in sale_data:
                raise Exception("business_id missing in sale_data")
    
            # -------------------------
            # RENDER HTML
            # -------------------------
            html = render_template(
                "invoice.html",
                sale_id=sale_id,
                sale=sale_data,
                items=sale_data.get("items", []),
                subtotal=sale_data.get("subtotal", 0),
                vat_amount=sale_data.get("vat_amount", 0),
                total_amount=sale_data.get("total_amount", 0),
                cashier_name=sale_data.get("cashier_name", "N/A")
            )
    
            # -------------------------
            # GENERATE PDF
            # -------------------------
            pdfkit.from_string(html, output_path, configuration=config)
    
            print("✅ Invoice generated:", output_path)
    
            # -------------------------
            # SAVE TO GALLERY (OPTION A)
            # -------------------------
            db = get_db()
            cursor = db.cursor()
    
            cursor.execute("""
                INSERT INTO gallery (business_id, filename)
                VALUES (%s, %s)
            """, (
                sale_data["business_id"],
                filename
            ))
    
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