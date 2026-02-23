import os
import hashlib
from functools import wraps

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


def reduce_stock_on_sale(product_id, store_id, quantity, business_id):
    db = get_db()
    cursor = db.cursor()

    inv_id = get_or_create_inventory(product_id, store_id)

    cursor.execute("""
        UPDATE inventory
        SET quantity = quantity - %s
        WHERE id=%s
    """, (quantity, inv_id))

    cursor.execute("""
        INSERT INTO stock_movements (product_id, business_id, from_store_id, quantity, movement_type)
        VALUES (%s, %s, %s, %s, 'sale')
    """, (product_id, business_id, store_id, quantity))

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
            cursor.execute("""
                INSERT INTO products (business_id, name, price)
                VALUES (%s, %s, %s)
            """, (business_id, name, price))
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
    @app.route("/sales", methods=["GET", "POST"])
    @login_required
    def sales():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Load dropdown data
        cursor.execute("SELECT * FROM products WHERE business_id=%s", (business_id,))
        products_list = cursor.fetchall()

        cursor.execute("SELECT * FROM customers WHERE business_id=%s", (business_id,))
        customers_list = cursor.fetchall()

        cursor.execute("SELECT * FROM stores WHERE business_id=%s", (business_id,))
        stores_list = cursor.fetchall()

        # -------------------------
        # FILTERS
        # -------------------------
        date_filter = request.args.get("date")
        typed_date = request.args.get("typed_date")
        product_name = request.args.get("product_name")

        query = """
            SELECT s.*, p.name AS product_name, c.name AS customer_name
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.id
            LEFT JOIN customers c ON s.customer_id = c.id
            WHERE s.business_id=%s
        """
        params = [business_id]

        if date_filter:
            query += " AND DATE(s.created_at) = %s"
            params.append(date_filter)

        if typed_date:
            query += " AND DATE(s.created_at) = %s"
            params.append(typed_date)

        if product_name:
            query += " AND p.name LIKE %s"
            params.append(f"%{product_name}%")

        query += " ORDER BY s.created_at DESC LIMIT 200"

        cursor.execute(query, params)
        sales_list = cursor.fetchall()

    # -------------------------
    # PROCESS NEW SALE
    # -------------------------
        if request.method == "POST":
            product_id = int(request.form["product_id"])
            customer_id = request.form.get("customer_id") or None
            store_id = int(request.form["store_id"])
            quantity = int(request.form["quantity"])

            cursor.execute("SELECT price FROM products WHERE id=%s", (product_id,))
            product = cursor.fetchone()
            price = float(product["price"])

            total_amount = quantity * price

            cursor.execute("""
                INSERT INTO sales (business_id, product_id, customer_id, total_amount)
                VALUES (%s, %s, %s, %s)
            """, (business_id, product_id, customer_id, total_amount))
            db.commit()

            reduce_stock_on_sale(product_id, store_id, quantity, business_id)

            flash("Sale recorded", "success")
            return redirect(url_for("sales"))

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
    @app.route("/stock-movements", methods=["GET"])
    @login_required
    def stock_movements():
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)

    # --- Filters ---
        date_filter = request.args.get("date")
        typed_date = request.args.get("typed_date")
        product_name = request.args.get("product_name")

        query = """
            SELECT sm.*, p.name AS product_name,
               fs.name AS from_store_name,
               ts.name AS to_store_name
            FROM stock_movements sm
            JOIN products p ON sm.product_id = p.id
            LEFT JOIN stores fs ON sm.from_store_id = fs.id
            LEFT JOIN stores ts ON sm.to_store_id = ts.id
            WHERE sm.business_id=%s
        """
        params = [business_id]

    # Filter by calendar date
        if date_filter:
            query += " AND DATE(sm.created_at) = %s"
            params.append(date_filter)

    # Filter by typed date
        if typed_date:
            query += " AND DATE(sm.created_at) = %s"
            params.append(typed_date)

    # Filter by product name
        if product_name:
            query += " AND p.name LIKE %s"
            params.append(f"%{product_name}%")

        query += " ORDER BY sm.created_at DESC LIMIT 200"

        cursor.execute(query, params)
        movements = cursor.fetchall()

    # Load product list for dropdown
        cursor.execute("SELECT name FROM products WHERE business_id=%s ORDER BY name ASC", (business_id,))
        products = cursor.fetchall()

        return render_template(
            "stock_movements.html",
        movements=movements,
        products=products
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
        business_id = session["user"]["business_id"]
        db = get_db()
        cursor = db.cursor(dictionary=True)

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
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)

                cursor.execute("""
                    INSERT INTO gallery (business_id, filename)
                    VALUES (%s, %s)
                """, (business_id, filename))
                db.commit()
                flash("Image uploaded", "success")
                return redirect(url_for("gallery"))

        cursor.execute("SELECT * FROM gallery WHERE business_id=%s ORDER BY created_at DESC", (business_id,))
        images = cursor.fetchall()
        return render_template("gallery.html", images=images)

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
    app.run(debug=True)