import requests
from urllib.parse import quote
from rdkit import Chem


def c_nmr_predict(smiles, solvent="CDCl3"):
    """
    Predict 13C NMR chemical shifts for a given SMILES string via remote API.

    Args:
        smiles: SMILES string of the compound.
        solvent: Solvent name, either 'CDCl3' or 'DMSO-d6'.

    Returns:
        Formatted 13C NMR report string.
    """
    smiles = [smiles]
    if solvent == "CDCl3":
        solvent2 = "Chloroform-D1 (CDCl3)"
    elif solvent == "DMSO-d6":
        solvent2 = "Dimethylsulphoxide-D6 (DMSO-D6, C2D6SO)"
    r1 = requests.post("http://10.72.xx.xx:8000/api/predict/carbon?solvent="+quote(solvent2), json={"smiles": smiles})
    carbon_preds = r1.json()

    smiles_carb = carbon_preds[0]
    carbon_data = smiles_carb['predictions']

    # Extracting the 'mean' values and sorting by mean in descending order
    carbon_sorted_means = sorted(carbon_data, key=lambda x: x['mean'], reverse=True)

    # Preparing the output format
    mean_values = [str(item['mean']) for item in carbon_sorted_means]
    output = f"13C NMR (100.0 MHz, {solvent}) δ " + ", ".join(mean_values)
    return output


def h_nmr_predict(smiles, solvent="CDCl3"):
    """
    Predict 1H NMR chemical shifts for a given SMILES string via remote API.

    Args:
        smiles: SMILES string of the compound.
        solvent: Solvent name, either 'CDCl3' or 'DMSO-d6'.

    Returns:
        Formatted 1H NMR report string with proton counts.
    """
    global solvent1
    smiles = [smiles]
    if solvent == "CDCl3":
        solvent1 = "Chloroform-D1 (CDCl3)"
    elif solvent == "DMSO-d6":
        solvent1 = "Dimethylsulphoxide-D6 (DMSO-D6, C2D6SO)"
    r = requests.post("http://10.72.xx.xx:8000/api/predict/proton?solvent="+quote(solvent1), json={"smiles": smiles})
    proton_preds = r.json()

    smiles_prot = proton_preds[0]
    proton_data = smiles_prot['predictions']

    # Extracting the 'mean' values and sorting by mean in ascending order
    proton_sorted_means = sorted(proton_data, key=lambda x: x['mean'], reverse=False)
    ranges = {}
    for atom in proton_sorted_means:
        mean_val = atom['mean']
        range_key = f"{mean_val:.2f}"
        if range_key in ranges:
            ranges[range_key] += 1
        else:
            ranges[range_key] = 1
    nmr_format = []

    for range_key, count in ranges.items():
        nmr_format.append(f"{range_key} ({count} H)")

    # Output the result
    output = f"1H NMR (100.0 MHz, {solvent}) δ " + ", ".join(nmr_format)
    return output


if __name__ == "__main__":
    print(c_nmr_predict("OC([C@H](CCCCNC(C1C=CC(F)=CC=1)=O)NC(OCC1C2C=CC=CC=2C2C=CC=CC1=2)=O)=O", solvent="DMSO-d6"))
