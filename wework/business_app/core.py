import os
import hashlib
from flask import (
    Flask, render_template, request, redirect,
    session, url_for, flash
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
    # DASHBOARD & PROFILE
    # -------------------------
    def login_required(f):
        from functools import wraps

        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper

    @app.route("/")
    @login_required
    def dashboard():
        business_id = session["user"]["business_id"]

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) AS total_products FROM products WHERE business_id=%s", (business_id,))
        total_products = cursor.fetchone()["total_products"]

        cursor.execute("SELECT COUNT(*) AS total_customers FROM customers WHERE business_id=%s", (business_id,))
        total_customers = cursor.fetchone()["total_customers"]

        cursor.execute("SELECT IFNULL(SUM(total_amount),0) AS total_sales FROM sales WHERE business_id=%s", (business_id,))
        total_sales = cursor.fetchone()["total_sales"]

        return render_template(
            "dashboard.html",
            total_products=total_products,
            total_customers=total_customers,
            total_sales=total_sales
        )

    @app.route("/profile")
    @login_required
    def profile():
        return render_template("profile.html", user=session["user"])

    # -------------------------
    # PRODUCTS
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

        cursor.execute("SELECT * FROM products WHERE business_id=%s", (business_id,))
        items = cursor.fetchall()
        return render_template("products.html", items=items)

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
    # SALES (simple placeholder)
    # -------------------------
    @app.route("/sales")
    @login_required
    def sales():
        return render_template("sales.html")

    # -------------------------
    # SETTINGS
    # -------------------------
    @app.route("/settings")
    @login_required
    def settings():
        return render_template("settings.html")

    # -------------------------
    # GALLERY UPLOAD
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
    # ERROR HANDLERS
    # -------------------------
    @app.errorhandler(404)
    def not_found(e):
        return render_template("base.html", content="Page not found"), 404

    return app