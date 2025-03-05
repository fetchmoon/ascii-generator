import os
from flask import Flask, request, render_template, send_file, jsonify, redirect, url_for, session
from PIL import Image, ImageEnhance, ImageOps
import pyfiglet
from fpdf import FPDF
import qrcode
import pyttsx3
import speech_recognition as sr
from threading import Thread
from werkzeug.utils import secure_filename
from datetime import datetime
import dropbox
from zipfile import ZipFile
import logging

app = Flask(__name__)
app.secret_key = "your_secret_key"
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "wav", "mp3"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Dropbox configuration (optional)
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN", None)  # Use environment variable for security

logging.basicConfig(level=logging.DEBUG)

# --- Helper Functions ---
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def save_file(file):
    """Save uploaded file securely."""
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)
        return file_path
    return None

def cleanup_directory(directory):
    """Remove all files and subdirectories in a directory."""
    for root, _, files in os.walk(directory):
        for file in files:
            os.remove(os.path.join(root, file))
    os.rmdir(directory)

# --- ASCII Generator Functions ---
def text_to_ascii(text, font="standard", color="default", chars="@%#*+=-:. "):
    try:
        ascii_art = pyfiglet.figlet_format(text, font=font)
        if color != "default":
            colors = {
                "red": "\033[91m",
                "green": "\033[92m",
                "yellow": "\033[93m",
                "blue": "\033[94m",
                "reset": "\033[0m"
            }
            ascii_art = f"{colors.get(color, '')}{ascii_art}{colors['reset']}"
        return ascii_art
    except Exception as e:
        logging.error(f"Error generating ASCII art: {e}")
        return "Error generating ASCII art."

def image_to_ascii(image_path, width=100, contrast=1.0, brightness=1.0, chars="@%#*+=-:. "):
    try:
        img = Image.open(image_path)
        img = ImageEnhance.Contrast(img).enhance(contrast)
        img = ImageEnhance.Brightness(img).enhance(brightness)

        aspect_ratio = img.height / img.width
        new_height = int(width * aspect_ratio * 0.55)
        img = img.resize((width, new_height)).convert("L")
        pixels = img.getdata()
        ascii_pixels = [chars[pixel // 25] for pixel in pixels]
        ascii_image = "\n".join(
            "".join(ascii_pixels[i:i + width]) for i in range(0, len(ascii_pixels), width)
        )
        return ascii_image
    except Exception as e:
        logging.error(f"Error converting image to ASCII: {e}")
        return "Error converting image to ASCII."

def export_to_pdf(text, output_path):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, text)
        pdf.output(output_path)
    except Exception as e:
        logging.error(f"Error exporting to PDF: {e}")

def generate_qr_code(data, output_path):
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill="black", back_color="white")
        img.save(output_path)
    except Exception as e:
        logging.error(f"Error generating QR code: {e}")

def upload_to_dropbox(file_path, dropbox_path):
    if not DROPBOX_ACCESS_TOKEN:
        logging.error("Dropbox access token not configured.")
        return "Dropbox access token not configured."
    try:
        dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
        with open(file_path, "rb") as f:
            dbx.files_upload(f.read(), dropbox_path)
        return "File uploaded successfully."
    except Exception as e:
        logging.error(f"Dropbox upload error: {e}")
        return str(e)

# --- Web Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    ascii_text = ""
    ascii_image = ""
    fonts = pyfiglet.FigletFont.getFonts()
    if request.method == "POST":
        # Handle text input
        text = request.form.get("text", "")
        font = request.form.get("font", "standard")
        color = request.form.get("color", "default")
        chars = request.form.get("chars", "@%#*+=-:. ")
        if text:
            ascii_text = text_to_ascii(text, font, color, chars)

        # Handle image input
        if "image" in request.files:
            image_file = request.files["image"]
            image_path = save_file(image_file)
            if image_path:
                contrast = float(request.form.get("contrast", 1.0))
                brightness = float(request.form.get("brightness", 1.0))
                width = int(request.form.get("width", 100))
                ascii_image = image_to_ascii(image_path, width, contrast, brightness, chars)

        # Export options
        if "export" in request.form:
            export_type = request.form["export"]
            content = ascii_text or ascii_image
            if export_type == "txt":
                output_path = "output.txt"
                with open(output_path, "w") as f:
                    f.write(content)
                return send_file(output_path, as_attachment=True)
            elif export_type == "pdf":
                output_path = "output.pdf"
                export_to_pdf(content, output_path)
                return send_file(output_path, as_attachment=True)
            elif export_type == "qr":
                output_path = "output.png"
                generate_qr_code(content, output_path)
                return send_file(output_path, as_attachment=True)
            elif export_type == "cloud":
                output_path = "output.txt"
                with open(output_path, "w") as f:
                    f.write(content)
                dropbox_path = f"/ascii_outputs/{datetime.now().strftime('%Y%m%d%H%M%S')}_output.txt"
                result = upload_to_dropbox(output_path, dropbox_path)
                if "Error" in result:
                    return jsonify({"status": "error", "message": result})
                return jsonify({"status": "success", "message": "File uploaded to Dropbox."})

    return render_template("index.html", fonts=fonts, ascii_text=ascii_text, ascii_image=ascii_image)

@app.route("/preview", methods=["GET"])
def preview():
    text = request.args.get("text", "")
    font = request.args.get("font", "standard")
    if not text:
        return ""

    ascii_art = text_to_ascii(text, font=font)
    return ascii_art

@app.route("/tts", methods=["POST"])
def tts():
    text = request.form.get("text", "")
    if not text:
        return jsonify({"status": "error", "message": "No text provided."})
    output_path = "output.mp3"

    def generate_tts():
        engine = pyttsx3.init()
        engine.save_to_file(text, output_path)
        engine.runAndWait()

    thread = Thread(target=generate_tts)
    thread.start()
    return jsonify({"status": "success", "message": "Processing text-to-speech..."})

@app.route("/stt", methods=["POST"])
def stt():
    if "audio" not in request.files:
        return jsonify({"status": "error", "message": "No audio file uploaded."})
    
    audio_file = request.files["audio"]
    audio_path = save_file(audio_file)
    if audio_path:
        text = speech_to_text(audio_path)
        return jsonify({"status": "success", "text": text})
    return jsonify({"status": "error", "message": "Invalid audio file."})

@app.route("/batch", methods=["POST"])
def batch_process():
    files = request.files.getlist("files")
    output_dir = "batch_output"
    os.makedirs(output_dir, exist_ok=True)

    for file in files:
        file_path = save_file(file)
        if file_path:
            ascii_image = image_to_ascii(file_path)
            with open(f"{file_path}.txt", "w") as f:
                f.write(ascii_image)

    zip_path = "batch_output.zip"
    with ZipFile(zip_path, "w") as zipf:
        for root, _, files in os.walk(output_dir):
            for file in files:
                zipf.write(os.path.join(root, file), file)

    cleanup_directory(output_dir)
    return send_file(zip_path, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)