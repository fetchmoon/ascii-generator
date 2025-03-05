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
import shutil
from pathlib import Path

app = Flask(__name__)
app.config.from_object('config.Config')
UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
Path(UPLOAD_FOLDER).mkdir(exist_ok=True)

logging.basicConfig(level=logging.DEBUG)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def save_file(file):
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        return file_path
    return None

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
        logging.error(f"ASCII generation error: {e}")
        return "Error generating ASCII art."

def image_to_ascii(image_path, width=100, contrast=1.0, brightness=1.0, chars="@%#*+=-:. "):
    try:
        with Image.open(image_path) as img:
            img = ImageEnhance.Contrast(img).enhance(contrast)
            img = ImageEnhance.Brightness(img).enhance(brightness)
            aspect_ratio = img.height / img.width
            new_height = int(width * aspect_ratio * 0.55)
            img = img.resize((width, new_height)).convert("L")
            pixels = img.getdata()
            ascii_pixels = [chars[pixel // 25] for pixel in pixels]
            return "\n".join(
                "".join(ascii_pixels[i:i + width]) for i in range(0, len(ascii_pixels), width)
            )
    except Exception as e:
        logging.error(f"Image conversion error: {e}")
        return "Error converting image to ASCII."

def export_to_pdf(text, output_path):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, text)
        pdf.output(output_path)
        return True
    except Exception as e:
        logging.error(f"PDF export error: {e}")
        return False

def generate_qr_code(data, output_path):
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data)
        qr.make(fit=True)
        qr.make_image(fill="black", back_color="white").save(output_path)
        return True
    except Exception as e:
        logging.error(f"QR code error: {e}")
        return False

def upload_to_dropbox(file_path, dropbox_path):
    if not app.config['DROPBOX_ACCESS_TOKEN']:
        return "Dropbox access token not configured."
    try:
        dbx = dropbox.Dropbox(app.config['DROPBOX_ACCESS_TOKEN'])
        with open(file_path, "rb") as f:
            dbx.files_upload(f.read(), dropbox_path)
        return "File uploaded successfully."
    except Exception as e:
        logging.error(f"Dropbox error: {e}")
        return str(e)

@app.route("/", methods=["GET", "POST"])
def index():
    ascii_text = ""
    ascii_image = ""
    fonts = pyfiglet.FigletFont.getFonts()
    
    if request.method == "POST":
        text = request.form.get("text", "")
        if text:
            ascii_text = text_to_ascii(
                text,
                request.form.get("font", "standard"),
                request.form.get("color", "default"),
                request.form.get("chars", "@%#*+=-:. ")
            )
        
        image_file = request.files.get("image")
        if image_file:
            image_path = save_file(image_file)
            if image_path:
                try:
                    contrast = float(request.form.get("contrast", 1.0))
                    brightness = float(request.form.get("brightness", 1.0))
                    width = int(request.form.get("width", 100))
                    ascii_image = image_to_ascii(image_path, width, contrast, brightness)
                except ValueError:
                    ascii_image = "Invalid parameters provided."

        export_type = request.form.get("export")
        if export_type:
            content = ascii_text or ascii_image
            if not content:
                return jsonify({"status": "error", "message": "No content to export."}), 400
                
            try:
                if export_type == "txt":
                    return send_file(
                        path_or_file=content,
                        mimetype="text/plain",
                        as_attachment=True,
                        download_name="output.txt"
                    )
                elif export_type == "pdf":
                    pdf_path = os.path.join(UPLOAD_FOLDER, "output.pdf")
                    if export_to_pdf(content, pdf_path):
                        return send_file(pdf_path, as_attachment=True)
                    raise Exception("PDF export failed")
                elif export_type == "qr":
                    qr_path = os.path.join(UPLOAD_FOLDER, "output.png")
                    if generate_qr_code(content, qr_path):
                        return send_file(qr_path, as_attachment=True)
                    raise Exception("QR generation failed")
                elif export_type == "cloud":
                    temp_path = os.path.join(UPLOAD_FOLDER, "temp.txt")
                    with open(temp_path, "w") as f:
                        f.write(content)
                    dropbox_path = f"/ascii_outputs/{datetime.now().strftime('%Y%m%d%H%M%S')}_output.txt"
                    result = upload_to_dropbox(temp_path, dropbox_path)
                    os.remove(temp_path)
                    return jsonify({"status": "success" if "success" in result else "error", "message": result})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500

    return render_template("index.html", fonts=fonts, ascii_text=ascii_text, ascii_image=ascii_image)

@app.route("/preview")
def preview():
    text = request.args.get("text", "")
    font = request.args.get("font", "standard")
    return text_to_ascii(text, font) if text else ""

@app.route("/tts", methods=["POST"])
def tts():
    text = request.form.get("text")
    if not text:
        return jsonify({"status": "error", "message": "No text provided."}), 400
        
    output_path = os.path.join(UPLOAD_FOLDER, "output.mp3")
    
    def generate_audio():
        engine = pyttsx3.init()
        engine.save_to_file(text, output_path)
        engine.runAndWait()
        
    Thread(target=generate_audio).start()
    return jsonify({"status": "processing", "message": "Text-to-speech processing started."})

@app.route("/stt", methods=["POST"])
def stt():
    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"status": "error", "message": "No audio file uploaded."}), 400
        
    audio_path = save_file(audio_file)
    if not audio_path:
        return jsonify({"status": "error", "message": "Invalid audio file."}), 400
        
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_path) as source:
        try:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)
            return jsonify({"status": "success", "text": text})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/batch", methods=["POST"])
def batch_process():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"status": "error", "message": "No files uploaded."}), 400
        
    output_dir = os.path.join(UPLOAD_FOLDER, f"batch_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    Path(output_dir).mkdir(exist_ok=True)
    
    try:
        for file in files:
            file_path = save_file(file)
            if file_path:
                ascii_art = image_to_ascii(file_path)
                output_path = os.path.join(output_dir, f"{Path(file.filename).stem}.txt")
                with open(output_path, "w") as f:
                    f.write(ascii_art)
        
        zip_path = os.path.join(UPLOAD_FOLDER, "batch_output.zip")
        with ZipFile(zip_path, "w") as zipf:
            for root, _, files in os.walk(output_dir):
                for file in files:
                    zipf.write(os.path.join(root, file), file)
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
    
    return send_file(zip_path, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=app.config['DEBUG'])