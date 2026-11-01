"""
RetroDesServer.py
-----------------
Flask HTTP service that wraps the ChemLex retrosynthesis planning API
(https://ai-cn.chemlex.com/retroplanning) so that client can drive it
with a simple submit/query protocol.

Protocol (POST /receive_data, JSON body {"data": ...}):
    {"data": "<json with a SMILES field>"}  -> submit (or reuse) a retrosynthesis task
    {"data": "query"}                       -> poll the current task, or fetch its routes

A completed task is returned as a Step-based dict produced by
extract_reaction_tree_dict(), where every compound is enriched with its
chemical name (ChemScript), price and molecular weight (RDKit).
"""
import os
import sys
import json
import subprocess

import pandas as pd
import requests
from flask import Flask, request, jsonify
from rdkit import Chem
from rdkit.Chem import Descriptors

# ChemScript installation layout. Only the child process spawned by
# extract_reaction_tree_dict() actually loads this library, because its native
# extension (_ChemScript20forPy25/26/31/32.pyd) cannot run under Python 3.12.
CS_LIB = r"C:\Program Files\PerkinElmerInformatics\ChemOffice2020\ChemScript\Lib"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_PATH = os.path.join(BASE_DIR, 'smiles_taskId.xlsx')

URL = "https://ai-cn.chemlex.com/retroplanning"
HEADERS = {
    "X-SECRET-API-KEY": "",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# Id of the task currently owned by this service. 1 means "no active task":
# the client submits first and queries afterwards, so a single slot is enough.
NO_TASK = 1
current_task_id = NO_TASK

# Maximum number of buyable routes returned per task.
MAX_ROUTES = 10

app = Flask(__name__)


@app.route('/ping', methods=['GET'])
def ping():
    """Liveness probe, used by the client to verify the service is up."""
    return jsonify({"status": "online"})


@app.route('/receive_data', methods=['POST'])
def receive_data():
    """Single entry point implementing the submit/query state machine.

    Body {"data": "query"} asks for the result of the active task; any other
    payload must contain a SMILES and (re)submits a planning task.
    """
    global current_task_id

    try:
        request_data = request.get_json()
        data = request_data.get('data')

        if data == "query":
            if current_task_id == NO_TASK:
                return jsonify({"status": "error", "message": "No valid taskId available"})

            result = get_result(current_task_id)
            if result.get("status") == "completed":
                # Task finished: release the slot so the next submit starts clean.
                result["status"] = "success"
                current_task_id = NO_TASK
            return jsonify(result)

        # Submit branch: reuse the recorded taskId when this SMILES was already
        # submitted before, otherwise create a new task and remember it.
        smiles = json.loads(data).get('SMILES')
        df = load_excel()
        task_row = df[df['smiles'] == smiles]

        if not task_row.empty:
            current_task_id = int(task_row.iloc[0]['taskId'])
            return jsonify({"status": "running"})

        new_task_id = submit_task(smiles)
        if not isinstance(new_task_id, int):
            current_task_id = NO_TASK
            return jsonify({"status": "error", "message": "Submit task failed"})

        current_task_id = new_task_id
        save_task_to_excel(smiles, new_task_id)
        return jsonify({"status": "running"})

    except Exception as e:
        current_task_id = NO_TASK
        return jsonify({"status": "error", "message": str(e)})


def submit_task(smiles):
    """Submit a retrosynthesis planning job, return the taskId or None on failure.

    Search is configured for model-based, fast mode with a maximum tree depth
    of 3 and a 60 second simulation budget.
    """
    payload = {
        "method": "submit_task",
        "param": {
            "param": {
                "smiles": smiles,
                "param": {
                    "search_mode": {
                        "use_expert_rules": False,
                        "use_model": True,
                        "creative_mode": False,
                        "fast_mode": True
                    },
                    "max_depth": 3,
                    "disliked_reactions": [],
                    "disliked_compounds": [],
                    "max_simulation_time": 60
                }
            }
        }
    }

    try:
        response = requests.post(URL, headers=HEADERS, json=payload)
        if response.status_code != 200:
            return None
        return response.json().get("data")
    except Exception as e:
        print(f"submit_task failed: {e}")
        return None


def get_result(task_id):
    """Poll one task and always return a dict with a 'status' key.

    Statuses returned to the client:
        running   - task still pending/started, 'message' carries the progress
        completed - 'pathN' / 'pathN_info' pairs for up to MAX_ROUTES routes
        failed    - the remote task reported a failure
        error     - transport or parsing problem
    """
    payload = {
        "method": "get_result",
        "param": {"taskId": task_id}
    }

    try:
        response = requests.post(URL, headers=HEADERS, json=payload)
        if response.status_code != 200:
            return {"status": "error", "message": f"HTTP {response.status_code}"}

        res_json = json.loads(response.text)
        task = res_json.get("data") or {}
        status = task.get("status", "")
        process = task.get("process", 0)

        if status in ("pending", "start"):
            return {"status": "running", "message": f"Task is {status}. Current process: {process}%"}

        if status == "fail":
            return {"status": "failed", "message": "Task failed during execution"}

        if status != "completed":
            return {"status": "error", "message": f"Unknown status: {status}"}

        result_raw = task.get("result")
        if not result_raw:
            return {"status": "error", "message": "Result field is empty"}

        try:
            list_of_paths = json.loads(result_raw)
        except (json.JSONDecodeError, TypeError) as e:
            return {"status": "error", "message": f"Failed to parse result: {e}"}

        result_dict = {"status": "completed"}
        route_index = 1
        for route in list_of_paths:
            if route_index > MAX_ROUTES:
                break
            if not route.get('is_buyable_route'):
                continue

            # Keep the trimmed raw tree for auditing and the Step view for display.
            simplified_path_info = extract_relevant_fields(route['path'])
            reaction_tree = extract_reaction_tree_dict(simplified_path_info)
            print(reaction_tree)
            result_dict[f"path{route_index}_info"] = simplified_path_info
            result_dict[f"path{route_index}"] = reaction_tree
            route_index += 1

        return result_dict

    except Exception as e:
        print(f"get_result failed: {e}")
        return {"status": "error", "message": str(e)}


def save_task_to_excel(smiles, task_id):
    """Append a (smiles, taskId) pair to the task cache workbook."""
    df = load_excel()
    new_row = pd.DataFrame([[smiles, task_id]], columns=['smiles', 'taskId'])
    pd.concat([df, new_row], ignore_index=True).to_excel(EXCEL_PATH, index=False)


def load_excel():
    """Load the task cache, returning an empty frame when it does not exist yet."""
    if os.path.exists(EXCEL_PATH):
        return pd.read_excel(EXCEL_PATH)
    return pd.DataFrame(columns=['smiles', 'taskId'])


def extract_relevant_fields(node: dict) -> dict:
    """Recursively keep only the fields needed downstream.

    Kept per node: smiles, id, terminal, price, the single best-matching
    reaction condition and (recursively) children. Keys are omitted rather
    than defaulted, so callers must use .get().
    """
    def flatten_entries(source):
        """Flatten either [[entry, ...], ...] or [entry, ...] into one entry list."""
        entries = []
        for item in source or []:
            if isinstance(item, list):
                entries.extend(item)
            elif isinstance(item, dict):
                entries.append(item)
        return entries

    def extract_valid_condition(cond: dict) -> dict:
        """Pick the entry with the highest yield among patents and expert rules.

        Only entries carrying a preparation procedure are considered. A missing
        or unparseable yield counts as the 30% baseline, so an entry must beat
        that baseline to be selected at all.
        """
        BASELINE_YIELD = 30.0

        experts_raw = cond.get("from_experts", [])
        if not isinstance(experts_raw, list):
            experts_raw = [experts_raw]
        experts = [
            e.get("expert_recommended", e) if isinstance(e, dict) else e
            for e in experts_raw
        ]

        candidates = flatten_entries(cond.get("from_patents", [])) + flatten_entries(experts)

        best_entry = {}
        best_yield = BASELINE_YIELD
        for entry in candidates:
            if entry.get("preparation", "N/A") == "N/A":
                continue

            raw_yield = entry.get("yield", "N/A")
            try:
                entry_yield = float(str(raw_yield).rstrip('%'))
            except (ValueError, TypeError):
                entry_yield = BASELINE_YIELD

            if entry_yield > best_yield:
                best_yield = entry_yield
                best_entry = entry

        return best_entry

    result = {}

    for key in ('smiles', 'id', 'terminal'):
        if key in node:
            result[key] = node[key]

    price = (node.get('compound_attributes') or {}).get('price')
    if price is not None:
        result['price'] = price

    if 'reaction_conditions' in node:
        result['reaction_conditions'] = extract_valid_condition(node['reaction_conditions'])

    result['children'] = [extract_relevant_fields(child) for child in node.get('children', [])]

    return result


def extract_reaction_tree_dict(data_dict: dict) -> dict:
    """Convert a trimmed reaction tree into a retrosynthesis-ordered Step dict.

    The search tree is written product -> reactants, i.e. root first, while a
    chemist reads a route bottom-up. Levels are therefore remapped so that the
    last level becomes "Step 1" and the root becomes the highest step.

    Each compound is described by its SMILES, chemical name, price and molecular
    weight. The name comes from ChemScript, resolved through a child process.
    """
    level_info = {}
    compound_cache = {}

    # ChemScript's native module only supports Python 2.5/2.6/3.1/3.2, so it is
    # driven from a separate interpreter via pythonnet (.NET Framework) and the
    # managed assembly. Keeping it in a child process also means a pythonnet
    # failure degrades only the "Name" field instead of breaking the service.
    chem_name_code = r'''
import os
import sys

lib = sys.argv[1]
net = os.path.join(lib, "Net")
smiles = sys.argv[2]

# These handles must stay alive, otherwise the added DLL directories are dropped.
handles = [
    os.add_dll_directory(lib),
    os.add_dll_directory(net)
]

load_ns = {}
exec("from pythonnet import load", load_ns)
load_ns["load"]("netfx")

import clr
clr.AddReference(os.path.join(net, "CambridgeSoft.ChemScript20.dll"))
from CambridgeSoft.ChemScript20 import StructureData

mol = StructureData.LoadData(smiles, "smiles")
print("__RESULT__" + str(mol.ChemicalName()).strip(), flush=True)
'''

    def resolve_chemical_name(smiles_str: str) -> str:
        """Return the ChemScript chemical name of a SMILES, or 'N.A.' on any failure."""
        if not smiles_str:
            return 'N.A.'

        try:
            completed = subprocess.run(
                [sys.executable, "-c", chem_name_code, CS_LIB, smiles_str],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30
            )
        except subprocess.TimeoutExpired:
            print(f"Chemical name lookup timed out: {smiles_str}")
            return 'N.A.'
        except Exception as e:
            print(f"Chemical name lookup failed for {smiles_str}: {e}")
            return 'N.A.'

        # Read backwards because ChemScript may print its own output first.
        for line in reversed(completed.stdout.splitlines()):
            if line.startswith("__RESULT__"):
                name = line[len("__RESULT__"):].strip()
                if name and name.lower() not in ('none', 'nan'):
                    return name
                break

        print(f"Chemical name not resolved for {smiles_str}: "
              f"{(completed.stderr or '').strip()[:300]}")
        return 'N.A.'

    def get_molecular_weight(smiles_str: str) -> float | str:
        """Molecular weight from RDKit, or 'N.A.' when the SMILES is invalid."""
        try:
            mol = Chem.MolFromSmiles(smiles_str)
            return round(Descriptors.MolWt(mol), 1) if mol is not None else 'N.A.'
        except Exception:
            return 'N.A.'

    def describe_compound(smiles_str: str, price) -> dict:
        """Build the compound description, memoised because SMILES repeat across steps."""
        if smiles_str not in compound_cache:
            compound_cache[smiles_str] = {
                "Reagent SMILES": smiles_str,
                "Name": resolve_chemical_name(smiles_str),
                "Molecular Weight": get_molecular_weight(smiles_str)
            }
        # Copy so that a per-step price does not leak into the cached entry.
        return {**compound_cache[smiles_str], "Price": price}

    def traverse(node, level=0):
        """Record the first reaction seen at each depth, then descend."""
        if node.get("terminal", True):
            return

        children = node.get("children") or []

        # Only the first reaction found at a given depth is reported.
        if level not in level_info:
            level_info[level] = {
                "Product": describe_compound(node.get("smiles", ""), node.get("price")),
                "Reactant": [
                    describe_compound(child.get("smiles", ""), child.get("price"))
                    for child in children
                ],
                "Synthetic description for reference":
                    (node.get("reaction_conditions") or {}).get('preparation', 'N.A.'),
            }

        for child in children:
            traverse(child, level + 1)

    traverse(data_dict)

    if not level_info:
        return {}

    # Deepest level is the first synthetic step; the root is the final step.
    max_level = max(level_info)
    return {
        f"Step {max_level - level + 1}": level_info[level]
        for level in sorted(level_info)
    }


if __name__ == '__main__':
    app.run(host='', port=8002)
