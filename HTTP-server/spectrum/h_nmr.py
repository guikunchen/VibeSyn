from bruker.api.topspin import Topspin
from bruker.data.nmr import *
import math
from rdkit import Chem


def _safe_peak_position(pk):
    """Try several ways to extract ppm position from a TopSpin peak entry."""
    try:
        return float(pk['position'][0])
    except Exception:
        pass
    try:
        return float(pk.position[0])
    except Exception:
        pass
    try:
        return float(pk)
    except Exception:
        return None


def within(ppm, start, end):
    """Check if a given ppm value is within the specified range."""
    lo, hi = min(start, end), max(start, end)
    return lo <= ppm <= hi


def _multiplicity_from_count(n):
    """Return the multiplicity based on the number of peaks in the cluster."""
    multiplicities = {0: None, 1: 's', 2: 'd', 3: 't', 4: 'q'}
    return multiplicities.get(n, 'm')


def _format_j_list(js):
    """Format J-coupling constants into a readable string."""
    if not js:
        return ''
    return f"J = {', '.join(str(j) for j in js)}" if len(js) > 1 else f"J = {js[0]}"


def _get_data_points(top, data_path):
    """Retrieve spectral data points."""
    proton = top.getDataProvider().getNMRData(top.getInstallationDirectory() + data_path)
    res = proton.getSpecDataPoints()
    if res.get(EXCEPTION):
        print('Error:', res.get(EXCEPTION).details())
        return None
    proton.launch("sigreg")
    return proton, res.get(DATA_POINTS)


def _calculate_integrals(proton, intRegions, data, peak_ppms, area_threshold):
    """Calculate the integrals for the specified regions."""
    integrals = []
    for region in intRegions:
        start = float(region['start'])
        end = float(region['end'])
        startIndex, endIndex = max(0, int(proton.getIndexFromPhysical(start, 0))), min(len(data) - 1,
                                                                                       int(proton.getIndexFromPhysical(
                                                                                           end, 0)))

        integral = sum(float(data[i]) for i in range(startIndex, endIndex + 1))
        center = (start + end) / 2.0
        peaks_in_region = [p for p in peak_ppms if within(p, start, end)]

        if integral >= area_threshold:
            integrals.append({
                'raw_area': float(integral),
                'start': start,
                'end': end,
                'center': center,
                'peaks': peaks_in_region
            })

    return integrals


def _is_solvent_region(item, solvent_ranges):
    """Check if the center of a region is within the solvent range."""
    c = item['center']
    for (a, b) in solvent_ranges:
        lo, hi = min(a, b), max(a, b)
        if lo <= c <= hi:
            return True
    return False


def _normalize_integrals(filtered, smiles, area_threshold=2020000000000.0):
    """Normalize the integrals based on the minimum integral and adjust hydrogen count if necessary."""
    mol = Chem.MolFromSmiles(smiles)
    mol_with_h = Chem.AddHs(mol)
    input_hydrogens = sum(1 for atom in mol_with_h.GetAtoms() if atom.GetSymbol() == "H")
    min_area = min(it['raw_area'] for it in filtered if it['raw_area'] > 0)
    total_hydrogens = 0

    for it in filtered:
        if it['raw_area'] <= 0:
            it['norm_int'] = 0
        else:
            it['norm_int'] = int(round(it['raw_area'] / min_area))

        total_hydrogens += it['norm_int']

    if input_hydrogens:
        print(total_hydrogens, input_hydrogens)
        if total_hydrogens < (input_hydrogens - 2):
            return False
        elif (input_hydrogens * 1.3) < total_hydrogens < (input_hydrogens * 1.7):
            for it in filtered:
                it['norm_int'] = round(round(it['norm_int']) / 1.38)
        elif (input_hydrogens * 1.7) < total_hydrogens < (input_hydrogens * 2):
            for it in filtered:
                it['norm_int'] = round(round(it['norm_int']) / 1.6)
        elif (input_hydrogens * 2) < total_hydrogens < (input_hydrogens * 3):
            for it in filtered:
                it['norm_int'] = round(it['norm_int']) / 2
        elif (input_hydrogens * 3) < total_hydrogens < (input_hydrogens * 8):
            for it in filtered:
                it['norm_int'] = round(round(it['norm_int']) / 3)
        elif (input_hydrogens * 8) < total_hydrogens:
            for it in filtered:
                it['norm_int'] = round(round(it['norm_int']) / 8)

    return filtered, total_hydrogens


def _compute_j_coupling_and_multiplicity(filtered, spectrometer_mhz=600.0):
    """Compute J-coupling constants and multiplicity for each region."""
    for it in filtered:
        peaks = sorted(it['peaks'])
        n = len(peaks)
        it['multiplicity'] = _multiplicity_from_count(n)

        j_list = []
        if n == 2:
            delta_ppm = abs(peaks[1] - peaks[0])
            j_list = [round(delta_ppm * spectrometer_mhz, 1)]
        elif n > 2:
            diffs = [abs(peaks[i + 1] - peaks[i]) for i in range(n - 1)]
            j_hz = sorted([round(d * spectrometer_mhz, 1) for d in diffs if d > 0], reverse=True)
            j_list = j_hz[:2] if j_hz else []

        it['j_list'] = j_list

    return filtered


def generate_h_nmr_report(data_path, spectrometer_mhz=600.0, solvent_ranges=None, area_threshold=2020000000000.0,
                          smiles="cc", solvent='CDCl3'):
    """
    Generate a 1H NMR report with integration, multiplicity, and J-coupling analysis.

    Args:
        data_path: Relative path to the 1H spectrum data.
        spectrometer_mhz: Spectrometer frequency in MHz for J-coupling calculation.
        solvent_ranges: List of (lo, hi) ppm ranges to exclude as solvent peaks.
        area_threshold: Minimum integral area threshold for region filtering.
        smiles: SMILES string of the compound, used for hydrogen count validation.
        solvent: Solvent name used for default solvent ranges and report header.
    """
    if solvent_ranges is None and solvent == 'CDCl3':
        # Default solvent ranges for CDCl3: CHCl3 (7.235–7.265), residual CHD2Cl2 (1.54–1.685), CH2Cl2 (1.71–1.73)
        solvent_ranges = [(7.235, 7.265), (1.54, 1.685), (1.71, 1.73),
                          (0.05, -0.1)]
    elif solvent_ranges is None and solvent == 'DMSO-d6':
        # Default solvent ranges for DMSO-d6: residual CHD2SOCHD2 (3.35–3.45), (CHD3)2SO (2.42–2.6)
        solvent_ranges = [(3.35, 3.45), (2.42, 2.6),
                          (0.05, -0.1)]

    top = Topspin()
    proton, data = _get_data_points(top, data_path)
    if proton is None:
        return

    # Read available peak list and sort ppm values
    peak_list_raw = proton.getPeakList() or []
    peak_ppms = sorted([_safe_peak_position(p) for p in peak_list_raw if _safe_peak_position(p) is not None])

    # Integration regions
    intRegions = proton.getIntegrationRegions()
    intRegions2 = proton.getIntegrationRegions()
    if intRegions is None:
        print('Cannot read the integration region file')
        return
    if intRegions2 is None:
        print('Cannot read the integration region file')
        return

    # Calculate integrals
    integrals = _calculate_integrals(proton, intRegions, data, peak_ppms, area_threshold)
    integrals2 = _calculate_integrals(proton, intRegions2, data, peak_ppms, area_threshold=760000000000.0)

    # Filter out solvent regions
    filtered = [it for it in integrals if not _is_solvent_region(it, solvent_ranges)]
    if not filtered:
        print("No integration regions remain after solvent removal.")
        return
    # Filter out solvent regions (second pass with lower area threshold)
    filtered2 = [it for it in integrals2 if not _is_solvent_region(it, solvent_ranges)]
    if not filtered2:
        print("No integration regions remain after solvent removal.")
        return

    # Normalize integrals and adjust hydrogen counts
    if _normalize_integrals(filtered, smiles, area_threshold) is False:
        filtered, total_hydrogens = _normalize_integrals(filtered2, smiles, area_threshold)
    else:
        filtered, total_hydrogens = _normalize_integrals(filtered, smiles, area_threshold)

    # Compute J-coupling constants and multiplicity
    filtered = _compute_j_coupling_and_multiplicity(filtered, spectrometer_mhz)

    # Prepare the formatted output sorted by ppm
    filtered_sorted = sorted(filtered, key=lambda x: x['center'], reverse=True)

    formatted_parts = []

    # Format the final report
    for it in filtered_sorted:
        shift = round(it['center'], 2)
        mult = it['multiplicity'] or 's'
        nh = it['norm_int']

        # Adjust hydrogen count based on solvent regions
        if 7.23 <= shift <= 7.3 and solvent == 'CDCl3':
            nh -= 1  # Remove 1H from this region's hydrogen count
        if 3.3 <= shift <= 3.45 and solvent == 'DMSO-d6':
            nh -= 1
        if mult == 's':
            formatted_parts.append(f"{shift:.2f} (s, {nh}H)")
        elif mult == 'd':
            formatted_parts.append(f"{shift:.2f} (d, {nh}H)")
        elif mult == 't':
            formatted_parts.append(f"{shift:.2f} (t, {nh}H)")
        elif mult == 'q':
            formatted_parts.append(f"{shift:.2f} (q, {nh}H)")
        else:
            start_val = it['start']
            end_val = it['end']
            formatted_parts.append(f"{end_val:.2f}-{start_val:.2f} (m, {nh}H)")

    result_str = f"1H NMR ({spectrometer_mhz} MHz, {solvent}) δ = " + ", ".join(formatted_parts)
    return result_str


if __name__ == "__main__":
    a = generate_h_nmr_report("/data/Peptide_library_product2/1/pdata/1/", smiles="OC([C@H](CCCCNC(C1C=CC(F)=CC=1)=O)NC(OCC1C2C=CC=CC=2C2C=CC=CC1=2)=O)=O", solvent="DMSO-d6")
    print(a)
