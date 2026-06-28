from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from pdf2docx import Converter
import os, uuid, sqlite3
from datetime import datetime

app = Flask(__name__)
CORS(app)

UPLOAD_DIR = "/tmp/conversions"
os.makedirs(UPLOAD_DIR, exist_ok=True)
DB_NAME = "conversions.db"
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            converted_at TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init_db()


def log_conversion(filename, status):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO conversions (filename, converted_at, status) VALUES (?, ?, ?)",
        (filename, datetime.now().isoformat(), status)
    )
    conn.commit()
    conn.close()


@app.route("/convert", methods=["POST"])
def convert():
    api_key = request.headers.get("X-API-Key")
    expected_key = os.environ.get("API_SECRET_KEY")

    if not expected_key:
        return jsonify({"error": "Server not configured properly"}), 500

    if api_key != expected_key:
        return jsonify({"error": "Unauthorized - invalid or missing API key"}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE_BYTES:
        return jsonify({
            "error": f"File too large. Maximum allowed size is {MAX_FILE_SIZE_MB}MB. "
                     f"Your file is {round(file_size / (1024*1024), 2)}MB."
        }), 413

    job_id = str(uuid.uuid4())
    pdf_path = f"{UPLOAD_DIR}/{job_id}.pdf"
    docx_path = f"{UPLOAD_DIR}/{job_id}.docx"

    try:
        file.save(pdf_path)
        cv = Converter(pdf_path)
        cv.convert(docx_path)
        cv.close()

        log_conversion(file.filename, "success")

        return send_file(docx_path, as_attachment=True,
                          download_name="converted.docx")
    except Exception as e:
        log_conversion(file.filename, "failed")
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


@app.route("/history", methods=["GET"])
def get_history():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM conversions ORDER BY id DESC"
    ).fetchall()
    conn.close()

    result = [
        {
            "filename": row["filename"],
            "converted_at": row["converted_at"],
            "status": row["status"]
        }
        for row in rows
    ]
    return jsonify(result)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
