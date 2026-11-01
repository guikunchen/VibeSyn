from flask import Flask, request, jsonify
import requests
import json
import base64
import mimetypes
import os
import matplotlib.pyplot as plt
from PIL import Image
import io

# Initialize the Flask application
app = Flask(__name__)
# URL of the downstream LabVIEW purification (separation) execution WebService endpoint
URL = 'http://127.0.0.1:8001/AutoExecution_WebService/Purification_HTTP'


# Health-check endpoint to verify the server is running
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "online"})


# Main endpoint: receives device input JSON, forwards it to the target server,
# processes the returned curve data into a chromatography chart,
# and returns the chart image as base64-encoded data
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

            # If the task has completed, process curve data and return the generated chart image
            elif task_status == "completed":
                curve = response_from_target.get("curve")
                print(curve)

                if curve:
                    # Process curve data into a chromatography chart and get the saved image path
                    save_path = process_curve_data(curve)
                    # Encode the generated chart image from the directory where it was saved
                    folder_path = os.path.dirname(save_path)
                    images = encode_images_from_folder(folder_path)
                    response = {"status": "success", "images": images}
                else:
                    response = {"status": "success", "message": "Task completed"}

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
# crop_box: (left, top, right, bottom) pixel coordinates; defaults to None (no cropping)
def encode_images_from_folder(folder_path, crop_box=None):
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


# Parse curve data (JSON array of 6-element arrays) into separate column lists,
# generate a flash chromatography chart with dual y-axes (UV absorbance + gradient),
# and save the chart as an image file.
# Returns the save_path of the generated chart image.
def process_curve_data(response_data):
    curve_data = json.loads(response_data)
    # Initialize empty lists for the five columns
    time = []
    UV_value1 = []
    UV_value2 = []
    Gradient = []
    CV = []

    # Loop through each curve in the curve_data and extract the values
    for curve in curve_data:
        print(f"Processing curve: {curve}")
        if len(curve) == 6:
            time.append(curve[0])
            UV_value1.append(curve[1])
            UV_value2.append(curve[2])
            # Gradient is calculated as (100 - curve[4]) to represent the complementary percentage
            Gradient.append(100 - curve[4])
            CV.append(curve[5])

    # Create the plot with a primary y-axis for UV absorbance values
    fig, ax1 = plt.subplots()

    # Plot UV_value1 and UV_value2 on the primary y-axis
    ax1.plot(CV, UV_value1, color='tab:blue', label='UV value1 (254 nm)')
    ax1.plot(CV, UV_value2, color='tab:orange', label='UV value2 (280 nm)')

    ax1.set_xlabel('Chromatography column volume')
    ax1.set_ylabel('UV value1 (254 nm)  & UV value2 (280 nm)', color='black')
    ax1.tick_params(axis='y', labelcolor='black')
    ax1.set_ylim(0, 2800)

    # Create a secondary y-axis for the eluent gradient percentage
    ax2 = ax1.twinx()
    ax2.plot(CV, Gradient, color='tab:green', label='EA Gradient (0-100%)', linestyle='--')
    ax2.set_ylabel('EA Gradient (0-100%)', color='black')
    ax2.tick_params(axis='y', labelcolor='black')
    ax2.set_ylim(0, 50)
    ax2.set_yticks(range(0, 51, 5))

    # Add legends to both axes
    ax1.legend(loc='upper left')
    ax2.legend(loc='upper right')

    plt.title('Flash chromatography curve')

    # Ensure the output directory exists
    os.makedirs('image', exist_ok=True)

    # Save the plot to image/1.jpg
    save_path = 'image/1.jpg'
    plt.savefig(save_path, format='jpg', dpi=300, bbox_inches='tight')

    # Show the plot
    plt.show()

    # Return the save path so the caller knows where the chart image was saved
    return save_path


if __name__ == '__main__':
    # Start the Flask server on the specified host and port
    app.run(host='', port=8001)
