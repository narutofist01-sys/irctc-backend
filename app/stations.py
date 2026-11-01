"""
Indian Railways Stations Database with 8,566 stations across all states and zones.
Provides instant in-memory lookup, prefix/fuzzy search, and city cluster resolution.
"""

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set


@dataclass
class Station:
    code: str
    name: str
    city: str
    state: str
    lat: float
    lon: float
    cluster_id: Optional[str] = None
    is_major_junction: bool = False


# Multi-station metropolitan city clusters in Indian Railways
CITY_CLUSTERS: Dict[str, Dict[str, any]] = {
    "DELHI": {
        "name": "Delhi NCR",
        "stations": ["NDLS", "DLI", "NZM", "ANVT", "DEE", "DEC"],
        "primary": "NDLS"
    },
    "MUMBAI": {
        "name": "Mumbai Metropolitan",
        "stations": ["CSMT", "BDTS", "LTT", "MMCT", "BSR", "PNVL", "KYN", "DR"],
        "primary": "CSMT"
    },
    "BENGALURU": {
        "name": "Bengaluru",
        "stations": ["SBC", "YPR", "SMVB", "BNC", "BAND", "KGI"],
        "primary": "SBC"
    },
    "KOLKATA": {
        "name": "Kolkata",
        "stations": ["HWH", "SDAH", "KOAA", "SHM", "SRC"],
        "primary": "HWH"
    },
    "CHENNAI": {
        "name": "Chennai",
        "stations": ["MAS", "MS", "TBM", "PER"],
        "primary": "MAS"
    },
    "HYDERABAD": {
        "name": "Hyderabad / Secunderabad",
        "stations": ["SC", "KCG", "HYB", "LPI"],
        "primary": "SC"
    },
    "AHMEDABAD": {
        "name": "Ahmedabad / Sabarmati",
        "stations": ["ADI", "SBT", "GER"],
        "primary": "ADI"
    },
    "PUNE": {
        "name": "Pune",
        "stations": ["PUNE", "HDP", "SVJR"],
        "primary": "PUNE"
    },
    "JAIPUR": {
        "name": "Jaipur",
        "stations": ["JP", "GADJ", "DPA"],
        "primary": "JP"
    },
    "LUCKNOW": {
        "name": "Lucknow",
        "stations": ["LKO", "LJN", "ASH"],
        "primary": "LKO"
    },
    "KANPUR": {
        "name": "Kanpur",
        "stations": ["CNB", "CPA"],
        "primary": "CNB"
    },
    "PATNA": {
        "name": "Patna",
        "stations": ["PNBE", "PPTA", "DNR", "RJPB"],
        "primary": "PNBE"
    },
    "VARANASI": {
        "name": "Varanasi / Banaras / DDU",
        "stations": ["BSB", "BSBS", "DDU", "MUV"],
        "primary": "BSB"
    },
    "BAREILLY": {
        "name": "Bareilly",
        "stations": ["BE", "BC", "BRY"],
        "primary": "BE"
    },
    "PRAYAGRAJ": {
        "name": "Prayagraj",
        "stations": ["PRYJ", "PRRB", "NYN", "ACOI"],
        "primary": "PRYJ"
    },
    "CHHAPRA": {
        "name": "Chhapra",
        "stations": ["CPR", "CI"],
        "primary": "CPR"
    },
    "GORAKHPUR": {
        "name": "Gorakhpur",
        "stations": ["GKP", "DMG"],
        "primary": "GKP"
    },
    "MORADABAD": {
        "name": "Moradabad",
        "stations": ["MB", "KNT"],
        "primary": "MB"
    },
    "JODHPUR": {
        "name": "Jodhpur",
        "stations": ["JU", "BGKT"],
        "primary": "JU"
    },
    "BHOPAL": {
        "name": "Bhopal",
        "stations": ["BPL", "RKMP", "HBJ"],
        "primary": "BPL"
    }
}

# Major junction codes for fast corridor filtering
MAJOR_JUNCTION_CODES: Set[str] = {
    "NDLS", "DLI", "NZM", "CSMT", "BDTS", "LTT", "BSR", "PNVL", "KYN", "SBC", "YPR", "SMVB",
    "HWH", "SDAH", "MAS", "MS", "SC", "KCG", "ADI", "BRC", "ST", "PUNE", "JU", "JP", "KOTA",
    "BPL", "RKMP", "ET", "NGP", "CNB", "LKO", "PRYJ", "BSB", "BSBS", "DDU", "PNBE", "GKP", "ASR",
    "UMB", "JAT", "BBS", "PURI", "R", "BSP", "GHY", "BZA", "VSKP", "WL", "GTL", "UBL", "SUR",
    "BSL", "MMR", "RTM", "UJN", "INDB", "GWL", "AGC", "MTJ", "JBP", "CBE", "MDU", "TPJ", "ED",
    "ERS", "TVC", "MAO", "BGM", "MAQ", "MYS", "AII", "ABR", "BKN", "BE", "MB", "CPR", "BXR",
    "GAYA", "DHN", "ASN", "BJU", "KIR", "RBL", "SLN", "STA", "KTE", "BAP", "ANG", "ETW", "ALJN"
}

# In-memory station registry
STATIONS_DATA: List[Station] = []
STATIONS_BY_CODE: Dict[str, Station] = {}
_CODE_PREFIX_INDEX: Dict[str, List[Station]] = {}


def _load_stations_data():
    global STATIONS_DATA, STATIONS_BY_CODE, _CODE_PREFIX_INDEX
    if STATIONS_DATA:
        return

    json_path = os.path.join(os.path.dirname(__file__), "data", "stations_full.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
            for item in raw_list:
                code = item["code"].upper()
                name = item["name"]
                city = item["city"] or name
                state = item["state"] or ""
                lat = float(item.get("lat") or 0.0)
                lon = float(item.get("lon") or 0.0)

                # Check cluster
                cluster_id = None
                for c_id, c_data in CITY_CLUSTERS.items():
                    if code in c_data["stations"]:
                        cluster_id = c_id
                        break

                is_junc = code in MAJOR_JUNCTION_CODES or "JN" in name.upper() or "JUNCTION" in name.upper()
                stn = Station(code, name, city, state, lat, lon, cluster_id, is_junc)
                STATIONS_DATA.append(stn)
                STATIONS_BY_CODE[code] = stn
        except Exception as e:
            print(f"Error loading full stations: {e}")

    # Build prefix index for fast typing lookup
    for s in STATIONS_DATA:
        p2 = s.code[:2]
        if p2 not in _CODE_PREFIX_INDEX:
            _CODE_PREFIX_INDEX[p2] = []
        _CODE_PREFIX_INDEX[p2].append(s)


# Load on import
_load_stations_data()


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS coordinates in kilometers."""
    if lat1 == 0.0 or lat2 == 0.0 or lon1 == 0.0 or lon2 == 0.0:
        return 1200.0  # Safe default if coordinates are missing

    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    return 2.0 * R * math.asin(math.sqrt(a))


def search_stations(query: str, limit: int = 12) -> List[Dict[str, any]]:
    """
    Lightning-fast autocomplete search across all 8,566 stations.
    Prioritizes exact station codes, major junction hubs, and metro clusters.
    """
    q = query.strip().upper()
    if not q:
        return []

    exact_matches: List[Station] = []
    prefix_code_matches: List[Station] = []
    name_matches: List[Station] = []
    city_matches: List[Station] = []

    # Check exact code first
    if q in STATIONS_BY_CODE:
        exact_matches.append(STATIONS_BY_CODE[q])

    # Search in dataset
    for s in STATIONS_DATA:
        if s.code == q:
            continue
        code_upper = s.code
        name_upper = s.name.upper()
        city_upper = s.city.upper()

        if code_upper.startswith(q):
            prefix_code_matches.append(s)
        elif q in name_upper:
            name_matches.append(s)
        elif q in city_upper:
            city_matches.append(s)

        if len(exact_matches) + len(prefix_code_matches) + len(name_matches) + len(city_matches) >= limit * 4:
            break

    # Prioritize major junction hubs and clusters within each group
    prefix_code_matches.sort(key=lambda s: (not s.is_major_junction, not bool(s.cluster_id), s.code))
    name_matches.sort(key=lambda s: (not s.is_major_junction, not bool(s.cluster_id), len(s.name)))
    city_matches.sort(key=lambda s: (not s.is_major_junction, not bool(s.cluster_id), len(s.city)))

    combined = exact_matches + prefix_code_matches + name_matches + city_matches
    seen = set()
    results = []
    for s in combined:
        if s.code not in seen:
            seen.add(s.code)
            results.append({
                "code": s.code,
                "name": s.name,
                "city": s.city,
                "state": s.state,
                "cluster": s.cluster_id,
                "is_junction": s.is_major_junction
            })
            if len(results) >= limit:
                break
    return results


def get_cluster_station_codes(stn_code: str) -> List[str]:
    """
    Returns all station codes in city cluster, or [stn_code] if standalone.
    """
    stn_code = stn_code.upper().strip()
    stn = STATIONS_BY_CODE.get(stn_code)
    if not stn or not stn.cluster_id:
        return [stn_code]

    cluster = CITY_CLUSTERS.get(stn.cluster_id)
    if not cluster:
        return [stn_code]

    stations = cluster["stations"]
    return [stn_code] + [s for s in stations if s != stn_code]
