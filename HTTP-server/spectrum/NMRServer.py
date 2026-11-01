"""
NMR Server - Flask-based HTTP service for NMR data analysis.

Receives NMR dataset parameters (file path, SMILES, solvent, prediction flags)
from client requests, generates experimental 1H/13C NMR reports, and optionally
appends predicted NMR results via remote API.
"""

from flask import Flask, request, jsonify
import requests
import json
import base64
import mimetypes
import os
from h_nmr import generate_h_nmr_report
from c_nmr import generate_c_nmr_report
from nmr_predict import c_nmr_predict
from nmr_predict import h_nmr_predict


app = Flask(__name__)

# Default NMR dataset name (used to construct the data path on server)
NMR_file = "mym-lw-step9"
# Default SMILES string for the compound under analysis
input_smiles = "C1CC=C(CC)CN1C(OC)=O"
# Flags controlling whether predicted NMR is appended to the report
h_nmr_predict_mode = "False"
c_nmr_predict_mode = "False"
# NMR solvent used for solvent peak exclusion and report formatting
solvent = "CDCl3"


@app.route('/ping', methods=['GET'])
def ping():
    """
    Health check endpoint.

    Returns:
        JSON response with server online status.
    """
    return jsonify({"status": "online"})


@app.route('/receive_data', methods=['POST'])
def receive_data():
    """
    Main endpoint that receives NMR analysis parameters or triggers report generation.

    When the request data is not "query", it stores the submitted parameters
    (NMR file, SMILES, prediction flags, solvent) into global variables.
    When the request data is "query", it generates the experimental NMR report
    and optionally appends predicted 1H/13C NMR results.

    Returns:
        JSON response with status and NMR report (on query),
        or error message on failure.
    """
    global NMR_file
    global input_smiles
    global h_nmr_predict_mode
    global c_nmr_predict_mode
    global solvent
    try:
        request_data = request.get_json()
        data = request_data.get('data')
        print(data)

        if data != "query":
            # Parse and store client-submitted analysis parameters
            NMR_file = json.loads(data).get('NMR_file')
            input_smiles = json.loads(data).get('SMILES')
            h_nmr_predict_mode = json.loads(data).get('h_nmr_predict_mode')
            c_nmr_predict_mode = json.loads(data).get('c_nmr_predict_mode')
            solvent = json.loads(data).get('solvent')

            return jsonify({"status": "running"})
        else:
            # Generate experimental 1H and 13C NMR reports from stored parameters
            h_nmr = generate_h_nmr_report(data_path="/data/" + NMR_file + "/1/pdata/1/", smiles=input_smiles, solvent=solvent)
            c_nmr = generate_c_nmr_report(data_path="/data/" + NMR_file + "/2/pdata/1/", solvent=solvent)
            nmr_report = "Experimental NMR report is: " + h_nmr + ". " + c_nmr + "."

            # Optionally append predicted 1H NMR
            if h_nmr_predict_mode == "True":
                predicted_h_nmr = h_nmr_predict(input_smiles, solvent=solvent)
                nmr_report = nmr_report + " Predicted 1H NMR is: " + predicted_h_nmr + "."

            # Optionally append predicted 13C NMR
            if c_nmr_predict_mode == "True":
                predicted_c_nmr = c_nmr_predict(input_smiles, solvent=solvent)
                nmr_report = nmr_report + " Predicted 13C NMR is: " + predicted_c_nmr + "."

            return jsonify({"status": "success", "NMR result": nmr_report})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == '__main__':
    app.run(host='', port=8003)
