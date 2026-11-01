from flask import Flask, request, jsonify
import requests
import json
import base64
import mimetypes
import os
from PIL import Image
import io

# Initialize the Flask application
app = Flask(__name__)
# URL of the downstream LabVIEW reaction execution WebService endpoint
URL = 'http://127.0.0.1:8001/AutoExecution_WebService/Reaction_HTTP'


# Health-check endpoint to verify the server is running
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "online"})


# Main endpoint: receives device input JSON, forwards it to the target server,
# and returns the task status or encoded result images
@app.route('/receive_data', methods=['POST'])
def receive_data():
    try:
        # Parse the incoming JSON payload from the client
        device_input_str = request.get_json()
        print(device_input_str)

        # Forward the payload to the downstream target server
        response_from_target = send_to_target_server(device_input_str)

        if response_from_target:
            task_status = response_from_target.get("status")
            print(task_status)

            # If the task is still in progress or has errored, pass the status through directly
            if task_status in ["running", "error", "idle"]:
                response = {"status": task_status}

            # If the task has completed, retrieve and encode result images
            elif task_status == "completed":
                folder_path = response_from_target.get("image_path")

                if folder_path:
                    folder_path = str(folder_path).strip()
                    # Encode all images found in the result folder to base64 (with optional cropping)
                    images = encode_images_from_folder(folder_path)
                    response = {"status": "success", "images": images}
                else:
                    # No image path returned; reaction completed but no images to return
                    response = {"status": "success", "message": "Reaction completed"}

            else:
                response = {"status": "error", "message": "Unknown task status"}
        else:
            response = {"status": "error", "message": "Failed to get response from target server"}

        return jsonify(response)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# Forward the input data to the downstream target server via HTTP POST
def send_to_target_server(device_input_str):
    try:
        response = requests.post(URL, json=device_input_str, timeout=60)
        print("Response status code:", response.status_code)
        print("Response text:", response.text)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed with status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"Exception occurred: {e}")
        return None


# Read all image files from the given folder, optionally crop each image,
# and return them as a list of base64-encoded dicts.
# crop_box: (left, top, right, bottom) pixel coordinates; defaults to (650, 300, 1250, 900)
def encode_images_from_folder(folder_path, crop_box=(650, 300, 1250, 900)):
    image_list = []
    if folder_path and os.path.isdir(folder_path):
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path):
                # Only process files whose MIME type starts with 'image/'
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type and mime_type.startswith('image/'):
                    with open(file_path, 'rb') as img_file:
                        img_data = img_file.read()

                    # Open image using PIL
                    image = Image.open(io.BytesIO(img_data))

                    # If a crop box is provided, crop the image to the region of interest
                    if crop_box:
                        width, height = image.size
                        left, top, right, bottom = crop_box

                        # Clamp crop coordinates to valid image boundaries
                        left = max(0, min(left, width))
                        top = max(0, min(top, height))
                        right = max(0, min(right, width))
                        bottom = max(0, min(bottom, height))
                        image = image.crop((left, top, right, bottom))

                    # Convert the image to a PNG byte stream and base64-encode it
                    img_byte_array = io.BytesIO()
                    image.save(img_byte_array, format='PNG')
                    img_byte_array = img_byte_array.getvalue()
                    img_base64 = base64.b64encode(img_byte_array).decode('utf-8')
                    image_list.append({'image_data': img_base64})
    return image_list


if __name__ == '__main__':
    # Start the Flask server on the specified host and port
    app.run(host='', port=8001)

