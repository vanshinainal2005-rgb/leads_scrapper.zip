from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify
import scrape
import os
import threading
import time

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Global variable to store progress
# In a production app, use a database or Redis keyed by session ID
SCRAPE_STATUS = {
    "running": False,
    "message": "",
    "progress": 0,
    "done": False,
    "filename": ""
}

def progress_callback(message, progress):
    global SCRAPE_STATUS
    SCRAPE_STATUS["message"] = message
    SCRAPE_STATUS["progress"] = progress

def run_scraper_background(keyword, city, pages):
    global SCRAPE_STATUS
    # SCRAPE_STATUS["running"] is set to True in the route handler before threading
    
    try:
        csv_path = scrape.run(keyword=keyword, city=city, pages=pages, progress_callback=progress_callback)
        SCRAPE_STATUS["progress"] = 100
        SCRAPE_STATUS["message"] = "Scraping complete!"
        SCRAPE_STATUS["done"] = True
        SCRAPE_STATUS["filename"] = "leads.csv" if csv_path else ""
    except Exception as e:
        SCRAPE_STATUS["message"] = f"Error: {str(e)}"
        SCRAPE_STATUS["progress"] = 0
    finally:
        SCRAPE_STATUS["running"] = False

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # If scraper is running but claims to be done, reset it
        if SCRAPE_STATUS["running"] and SCRAPE_STATUS["done"]:
             SCRAPE_STATUS["running"] = False
             
        if SCRAPE_STATUS["running"]:
             return jsonify({"status": "error", "message": "Scraper is already running."})

        keyword = request.form.get("keyword")
        city = request.form.get("city")
        pages = int(request.form.get("pages", 1))

        if not keyword or not city:
            return jsonify({"status": "error", "message": "Missing keyword or city"})

        # Reset status for new run
        SCRAPE_STATUS["running"] = True
        SCRAPE_STATUS["done"] = False
        SCRAPE_STATUS["progress"] = 0
        SCRAPE_STATUS["message"] = "Starting scraper..."
        SCRAPE_STATUS["filename"] = ""

        # Start background thread
        thread = threading.Thread(target=run_scraper_background, args=(keyword, city, pages))
        thread.start()
        
        return jsonify({"status": "success", "message": "Scraper started"})

    return render_template("index.html")

@app.route("/progress")
def progress():
    return jsonify(SCRAPE_STATUS)

@app.route("/reset", methods=["POST"])
def reset():
    global SCRAPE_STATUS
    SCRAPE_STATUS["running"] = False
    SCRAPE_STATUS["done"] = False
    SCRAPE_STATUS["progress"] = 0
    SCRAPE_STATUS["message"] = ""
    return jsonify({"status": "success", "message": "Scraper status reset."})

@app.route("/download")
def download():
    csv_path = os.path.abspath("leads.csv")
    if os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=True)
    else:
        flash("File not found. Please scrape data first.", "error")
        return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True, port=5001)
