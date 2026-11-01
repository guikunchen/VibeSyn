from flask import Flask, request, jsonify
import requests
import json
import base64
import mimetypes
import os
from PIL import Image
from io import BytesIO

# Initialize the Flask application
app = Flask(__name__)
# URL of the downstream LabVIEW separation optimization (TLC) WebService endpoint
URL = 'http://127.0.0.1:8001/AutoExecution_WebService/SepOpt_HTTP'


# Health-check endpoint to verify the server is running
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "online"})


# Main endpoint: receives device input JSON, forwards it to the target server,
# and returns TLC result images from the image_path provided by the target server.
# Unlike other servers, this endpoint does not check task_status — it directly
# retrieves and returns images upon receiving a response.
@app.route('/receive_data', methods=['POST'])
def receive_data():
    try:
        # Parse the incoming JSON payload from the client
        device_input_str = request.get_json()
        print(device_input_str)

        # Forward the payload to the downstream target server
        response_from_target = send_to_target_server(device_input_str)

        if response_from_target:
            # Extract the image folder path directly from the response (no status check)
            folder_path = response_from_target.get("image_path")
            if folder_path:
                folder_path = str(folder_path).strip()
                # Encode all TLC images from the folder (with 90° clockwise rotation)
                images = encode_images_from_folder(folder_path)
                response = {"status": "success", "images": images}
            else:
                # No image path returned; TLC completed but no images to return
                response = {"status": "success", "message": "TLC completed"}
        else:
            response = {"status": "error", "message": "Failed to get response from target server"}

        return jsonify(response)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# Forward the input data to the downstream target server via HTTP POST.
# Handles both JSON and non-JSON responses gracefully.
def send_to_target_server(device_input_str):
    try:
        response = requests.post(URL, json=device_input_str, timeout=60)

        print(response)
        print("Response Content (Raw):", response.content)
        print("Response status code:", response.status_code)
        print("Response text:", response.text)

        if response.status_code == 200:
            try:
                # Return parsed JSON if the response body is valid JSON
                return response.json()
            except ValueError:
                # Response is not JSON (e.g. plain text or HTML); log and return None
                print("Response is not JSON. Raw response:", response.text)
                return None
        else:
            print(f"Failed with status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"Exception occurred: {e}")
        return None


# Read all image files from the given folder, rotate each image 90° clockwise,
# and return them as a list of base64-encoded dicts.
# The rotation is applied because TLC plates are typically photographed in portrait
# orientation and need to be rotated for correct display.
def encode_images_from_folder(folder_path):
    image_list = []
    if folder_path and os.path.isdir(folder_path):
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path):
                # Only process files whose MIME type starts with 'image/'
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type and mime_type.startswith('image/'):
                    # Open the image and rotate it 90° clockwise for correct orientation
                    with Image.open(file_path) as img:
                        rotated_img = img.rotate(-90, expand=True)

                        # Save the rotated image to an in-memory buffer (no disk write)
                        buffer = BytesIO()
                        rotated_img.save(buffer, format=img.format)
                        img_data = buffer.getvalue()

                    # Encode the rotated image data to base64
                    img_base64 = base64.b64encode(img_data).decode('utf-8')
                    image_list.append({'image_data': img_base64})
    return image_list


if __name__ == '__main__':
    # Start the Flask server on the specified host and port
    app.run(host='', port=8004)
