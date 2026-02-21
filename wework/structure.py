import os

# Define the full folder structure
structure = {
    "business_app": [
        "app.py",
        "core.py",
        "requirements.txt",
        ("templates", [
            "base.html",
            "login.html",
            "register.html",
            "dashboard.html",
            "profile.html",
            "products.html",
            "customers.html",
            "sales.html",
            "settings.html",
            "gallery.html"
        ]),
        ("static", [
            ("css", ["theme.css"])
        ]),
        ("uploads", [])
    ]
}

def create_structure(base_path, structure_dict):
    for root, items in structure_dict.items():
        root_path = os.path.join(base_path, root)
        os.makedirs(root_path, exist_ok=True)

        for item in items:
            if isinstance(item, str):
                # Create file
                file_path = os.path.join(root_path, item)
                open(file_path, "w").close()

            elif isinstance(item, tuple):
                # Create subfolder and its contents
                folder_name, sub_items = item
                folder_path = os.path.join(root_path, folder_name)
                os.makedirs(folder_path, exist_ok=True)

                for sub_item in sub_items:
                    if isinstance(sub_item, str):
                        open(os.path.join(folder_path, sub_item), "w").close()
                    elif isinstance(sub_item, tuple):
                        subfolder_name, subfolder_files = sub_item
                        subfolder_path = os.path.join(folder_path, subfolder_name)
                        os.makedirs(subfolder_path, exist_ok=True)

                        for f in subfolder_files:
                            open(os.path.join(subfolder_path, f), "w").close()

if __name__ == "__main__":
    base_directory = os.getcwd()  # Creates structure in current working directory
    create_structure(base_directory, structure)
    print("Project structure created successfully!")