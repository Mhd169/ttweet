from flask import Flask, request, send_file, jsonify, abort
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from io import BytesIO
import os
import uuid
import arabic_reshaper
from bidi.algorithm import get_display
import requests
import re

app = Flask(__name__)

IMAGE_DIR = "tweet_images"
os.makedirs(IMAGE_DIR, exist_ok=True)

def load_profile_image(url, size=(80, 80)):
    try:
        response = requests.get(url)
        profile = Image.open(BytesIO(response.content)).convert("RGBA")
        profile = profile.resize(size)

        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size[0], size[1]), fill=255)

        result = Image.new("RGBA", size)
        result.paste(profile, (0, 0), mask=mask)

        return result.convert("RGBA")
    except Exception as e:
        print("فشل تحميل صورة البروفايل:", e)
        return None

def is_arabic(word):
    return bool(re.search(r'[\u0600-\u06FF]', word))

def draw_mixed_text(draw, text, font_ar, font_en, start_pos, max_width, line_spacing=10, color=(255, 255, 255)):
    arabic_count = sum(1 for w in text.split() if is_arabic(w))
    if arabic_count >= len(text.split()) * 0.7:
        reshaped_text = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped_text)
        draw.text(start_pos, bidi_text, font=font_ar, fill=color)
        return

    words = text.split(" ")
    x, y = start_pos
    lines = []
    current_line = []
    current_width = 0

    for word in words:
        if is_arabic(word):
            reshaped = arabic_reshaper.reshape(word)
            display_word = get_display(reshaped)
            font = font_ar
        else:
            display_word = word
            font = font_en

        word_width = draw.textlength(display_word + " ", font=font)

        if current_width + word_width > max_width:
            lines.append(current_line)
            current_line = [(display_word, font)]
            current_width = word_width
        else:
            current_line.append((display_word, font))
            current_width += word_width

    if current_line:
        lines.append(current_line)

    for line_words in lines:
        x_line = start_pos[0]
        for word, font in line_words:
            draw.text((x_line, y), word + " ", font=font, fill=color)
            x_line += draw.textlength(word + " ", font=font)
        y += font.getbbox("A")[3] + line_spacing

def create_tweet_image(username, handle, tweet_text, profile_url=None, attached_image_url=None):
    width = 1000
    base_height = 380
    image_padding = 20
    image_box_height = 350
    final_height = base_height + (image_box_height + image_padding if attached_image_url else 0)

    background_color = (0, 0, 0)
    text_color = (255, 255, 255)
    handle_color = (180, 180, 180)

    img = Image.new('RGB', (width, final_height), color=background_color)
    draw = ImageDraw.Draw(img)

    try:
        font_ar = ImageFont.truetype("NotoNaskhArabic-VariableFont_wght.ttf", 36)
        font_en = ImageFont.truetype("Cairo-Regular.ttf", 36)
        font_handle = ImageFont.truetype("Cairo-Regular.ttf", 28)
        font_name_ar = ImageFont.truetype("NotoNaskhArabic-VariableFont_wght.ttf", 40)
        font_name_en = ImageFont.truetype("Cairo-SemiBold.ttf", 36)
    except IOError:
        print("فشل تحميل الخطوط")
        return None

    profile_position = (30, 30)
    if profile_url:
        profile_img = load_profile_image(profile_url)
        if profile_img:
            img.paste(profile_img, profile_position, profile_img)
        else:
            draw.ellipse((30, 30, 110, 110), fill=(100, 100, 100))
    else:
        draw.ellipse((30, 30, 110, 110), fill=(100, 100, 100))

    name_font = font_name_ar if is_arabic(username) else font_name_en
    if is_arabic(username):
        reshaped_name = arabic_reshaper.reshape(username)
        display_name = get_display(reshaped_name)
        draw.text((130, 30), display_name, font=name_font, fill=text_color)
    else:
        draw.text((130, 30), username, font=name_font, fill=text_color)

    draw.text((130, 80), f"@{handle}", font=font_handle, fill=handle_color)

    draw_mixed_text(draw, tweet_text, font_ar, font_en, start_pos=(31, 145), max_width=940, color=text_color)

    if attached_image_url:
        try:
            response = requests.get(attached_image_url)
            attached_img = Image.open(BytesIO(response.content)).convert("RGB")
            attached_img.thumbnail((940, image_box_height))

            w, h = attached_img.size
            border_radius = 30
            rounded_mask = Image.new('L', (w, h), 0)
            ImageDraw.Draw(rounded_mask).rounded_rectangle((0, 0, w, h), radius=border_radius, fill=255)

            rounded_img = Image.new('RGB', (w, h))
            rounded_img.paste(attached_img, (0, 0), mask=rounded_mask)

            img.paste(rounded_img, (30, 260))
        except Exception as e:
            print("فشل تحميل الصورة المرفقة:", e)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    draw.text((40, final_height - 100), now, font=font_handle, fill=handle_color)

    filename = f"tweet_{uuid.uuid4().hex}.png"
    filepath = os.path.join(IMAGE_DIR, filename)
    img.save(filepath)
    return filename

@app.route('/generate_tweet_image', methods=['POST'])
def generate_tweet_image():
    data = request.json
    username = data.get('username', 'User')
    handle = data.get('handle', 'handle')
    tweet_text = data.get('tweet_text', 'تغريدة تجريبية.')
    profile_url = data.get('profile_url')
    attached_image_url = data.get('attached_image_url')

    filename = create_tweet_image(username, handle, tweet_text, profile_url, attached_image_url)
    if not filename:
        return jsonify({"error": "فشل في تحميل الخط أو إنشاء الصورة"}), 500

    image_url = f"/get_image/{filename}"
    return jsonify({"image_url": image_url}), 200

@app.route('/get_image/<filename>', methods=['GET'])
def get_image(filename):
    if '..' in filename or filename.startswith('/'):
        abort(400)
    filepath = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='image/png')
    else:
        return jsonify({"error": "الملف غير موجود"}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)
