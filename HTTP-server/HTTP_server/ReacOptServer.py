from flask import Flask, request, jsonify
import requests
import json
import base64
import mimetypes
import os

# Initialize the Flask application
app = Flask(__name__)
# URL of the downstream LabVIEW reaction optimization WebService endpoint
URL = 'http://127.0.0.1:8001/AutoExecution_WebService/ReactionOpt_HTTP'


# Health-check endpoint to verify the server is running
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "online"})


# Main endpoint: receives device input JSON, forwards it to the target server,
# and returns the task status or the reaction yield upon completion
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

            # If the task has completed, extract the reaction yield from the response
            elif task_status == "completed":
                yield_value = response_from_target.get("yield", "N/A")
                response = {"status": "success", "yield": yield_value}
                print(response)

            else:
                response = {"status": "error", "message": "Unknown task status"}
        else:
            response = {"status": "error", "message": "Failed to get response from target server"}

        return jsonify(response)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# Forward the input data to the downstream target server via HTTP POST
# A 60-second timeout is set to prevent indefinite blocking
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


if __name__ == '__main__':
    # Start the Flask server on the specified host and port
    app.run(host='', port=8004)

