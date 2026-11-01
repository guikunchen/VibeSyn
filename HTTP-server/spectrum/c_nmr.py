from typing import List, Tuple, Optional
from bruker.api.topspin import Topspin
from bruker.data.nmr import *
import math


def _safe_peak_position_intensity(pk):
    """Returns (ppm, intensity) from a TopSpin peak entry if possible."""
    ppm = None
    inten = None
    # Try to extract ppm (position)
    try:
        ppm = float(pk['position'][0])
    except Exception:
        try:
            ppm = float(pk.position[0])
        except Exception:
            try:
                ppm = float(pk)
            except Exception:
                ppm = None
    # Try to extract intensity
    try:
        inten = float(pk['intensity'])
    except Exception:
        try:
            inten = float(pk.intensity)
        except Exception:
            inten = None
    return ppm, inten


def _collect_peaks(proton_like_dataset, merge_tolerance=0.02):
    """Reads peaks from current dataset and returns sorted, merged ppm list and map of ppm -> intensity."""
    peak_list_raw = proton_like_dataset.getPeakList() or []
    pts = []
    # Collect ppm and intensity values
    for p in peak_list_raw:
        ppm, inten = _safe_peak_position_intensity(p)
        if ppm is not None:
            pts.append((ppm, inten))

    # Sort peaks by ppm in ascending order
    pts.sort(key=lambda x: x[0])

    # Merge close peaks within the tolerance and calculate weighted average of intensities
    merged = []
    for ppm, inten in pts:
        if not merged:
            merged.append([ppm, inten, 1])
        else:
            last_ppm, last_int, cnt = merged[-1]
            if abs(ppm - last_ppm) <= merge_tolerance:
                # Merge peaks within the tolerance
                if last_int is None or inten is None:
                    new_ppm = (last_ppm * cnt + ppm) / (cnt + 1)
                    new_int = last_int if last_int is not None else inten
                else:
                    w1 = abs(last_int)
                    w2 = abs(inten)
                    new_ppm = (last_ppm * w1 + ppm * w2) / (w1 + w2) if (w1 + w2) > 0 else (last_ppm + ppm) / 2
                    new_int = last_int + inten
                merged[-1] = [new_ppm, new_int, cnt + 1]
            else:
                merged.append([ppm, inten, 1])

    # Final merged list of ppm values
    merged_ppms = [m[0] for m in merged]
    ppm_to_int = {round(m[0], 6): m[1] for m in merged}
    return merged_ppms, ppm_to_int


def _ppm_in_ranges(ppm: float, ranges: List[Tuple[float, float]]) -> bool:
    """Checks if a ppm value is within any given range."""
    for a, b in ranges:
        lo, hi = (a, b) if a <= b else (b, a)
        if lo <= ppm <= hi:
            return True
    return False


def generate_c_nmr_report(
        data_path: str,
        carbon_mhz: float = 151.0,
        solvent_ranges: Optional[List[Tuple[float, float]]] = None,
        merge_tolerance: float = 0.02,
        solvent: str = "CDCl3",
        rel_intensity_min: Optional[float] = 0.01815,
        abs_intensity_min: Optional[float] = 1,
        drop_if_no_intensity: bool = False
):
    """
    Generates a 13C NMR report with small-peak suppression and intensity display.

    Args:
        data_path: Relative path to the C13 spectrum data.
        carbon_mhz: 13C spectrometer frequency in MHz.
        solvent_ranges: List of (lo, hi) ppm ranges to exclude as solvent peaks.
        merge_tolerance: Tolerance (ppm) for merging nearby peaks.
        solvent: Solvent name used in the report header.
        rel_intensity_min: Relative intensity threshold; peaks below this fraction
            of the max peak are ignored. Set to None to disable.
        abs_intensity_min: Absolute intensity threshold; peaks below this value
            are ignored. Set to None to disable.
        drop_if_no_intensity: Whether to drop peaks that lack intensity values.
    """

    top = Topspin()
    dp = top.getDataProvider()

    # Define the data path for the C13 spectrum
    C13 = top.getInstallationDirectory() + data_path
    c13 = dp.getNMRData(C13)

    # Get the spectrum data
    res = c13.getSpecDataPoints()
    if res.get(EXCEPTION):
        print('Error (13C):', res.get(EXCEPTION).details())
        return

    # Collect and merge peaks from the dataset
    ppms, ppm_to_int = _collect_peaks(c13, merge_tolerance=merge_tolerance)
    if not ppms:
        print("No 13C peaks found. Did you run peak picking or set the right dataset?")
        return

    # Default solvent (CDCl3) center range
    if solvent_ranges is None and solvent == 'CDCl3':
        solvent_ranges = [(76.76, 77.46), (0.05, -0.1)]

    elif solvent_ranges is None and solvent == 'DMSO-d6':
        solvent_ranges = [(39.50, 40.50), (0.05, -0.1)]

    # (1) Solvent filtering
    peaks = [p for p in ppms if not _ppm_in_ranges(p, solvent_ranges)]
    if not peaks:
        print("All 13C peaks were removed by solvent filtering.")
        return

    # Prepare intensity dictionary (may be empty or None)
    # _collect_peaks has already returned ppm_to_int: dictionary with ppm rounded to 6 decimal places
    def get_intensity(p):
        key = round(p, 6)
        val = ppm_to_int.get(key, None)
        return None if val is None else float(val)

    # (2) Intensity filtering: relative/absolute
    if rel_intensity_min is not None or abs_intensity_min is not None or drop_if_no_intensity:
        intensities = [abs(get_intensity(p)) for p in peaks if get_intensity(p) is not None]
        max_int = max(intensities) if intensities else None

        def pass_intensity_rules(p):
            inten = get_intensity(p)
            if inten is None:
                return (not drop_if_no_intensity)
            ainten = abs(inten)
            if abs_intensity_min is not None and ainten < abs_intensity_min:
                return False
            if rel_intensity_min is not None and max_int is not None and ainten < (max_int * rel_intensity_min):
                return False
            return True

        peaks = [p for p in peaks if pass_intensity_rules(p)]
        if not peaks:
            print("All 13C peaks were removed by intensity thresholds.")
            return

    # Sort peaks by ppm value (descending)
    peaks_sorted = sorted(peaks, reverse=True)
    parts = []
    for p in peaks_sorted:
        shift = round(p, 2)
        tag = ''
        rkey = round(p, 3)
        parts.append(f"{shift:.2f}{tag}")

    # Generate and display the final report
    result = f"13C NMR ({carbon_mhz} MHz, {solvent}) δ {', '.join(parts)}"
    return result


if __name__ == "__main__":
    a = generate_c_nmr_report(data_path="/data/Peptide_library_product2/3/pdata/1/", solvent="DMSO-d6")
    print(a)
