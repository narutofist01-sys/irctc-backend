"""
Dynamic Corridor & Junction Hub Selection Engine for Indian Railways.
Computes geographic detour ratios for ANY Origin and Destination pair in India,
dynamically selecting the most optimal transit junctions along the natural travel corridor.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    from app.stations import (
        CITY_CLUSTERS,
        STATIONS_BY_CODE,
        STATIONS_DATA,
        MAJOR_JUNCTION_CODES,
        haversine_distance,
    )
except ImportError:
    from backend.app.stations import (
        CITY_CLUSTERS,
        STATIONS_BY_CODE,
        STATIONS_DATA,
        MAJOR_JUNCTION_CODES,
        haversine_distance,
    )


@dataclass
class CorridorHub:
    station_code: str
    station_name: str
    city: str
    state: str
    detour_ratio: float
    total_km: float
    corridor_tier: str  # "PRIMARY", "SECONDARY", "DETOUR_FALLBACK"
    is_detour: bool


def select_corridor_hubs(
    origin_code: str,
    destination_code: str,
    max_hubs: int = 8
) -> List[CorridorHub]:
    """
    Dynamically identifies the best candidate transit hubs between ANY two stations in India.

    Args:
        origin_code: Origin railway station code (e.g. 'NDLS', 'JU', 'HWH')
        destination_code: Destination railway station code (e.g. 'SBC', 'MAS', 'CSMT')
        max_hubs: Maximum number of candidate hubs to return

    Returns:
        List of CorridorHub objects sorted by geographic alignment (lowest detour ratio first).
    """
    orig_stn = STATIONS_BY_CODE.get(origin_code.upper())
    dest_stn = STATIONS_BY_CODE.get(destination_code.upper())

    # Fallback default national mega-hubs if coordinates are missing
    default_mega_hubs = ["ADI", "PUNE", "KCG", "BPL", "CNB", "NGP", "BZA", "KOTA"]

    if not orig_stn or not dest_stn:
        return [
            CorridorHub(
                station_code=code,
                station_name=STATIONS_BY_CODE[code].name if code in STATIONS_BY_CODE else code,
                city=STATIONS_BY_CODE[code].city if code in STATIONS_BY_CODE else code,
                state=STATIONS_BY_CODE[code].state if code in STATIONS_BY_CODE else "",
                detour_ratio=1.05,
                total_km=1500.0,
                corridor_tier="PRIMARY",
                is_detour=False
            )
            for code in default_mega_hubs[:max_hubs]
        ]

    direct_km = haversine_distance(orig_stn.lat, orig_stn.lon, dest_stn.lat, dest_stn.lon)
    if direct_km < 80.0:
        # Origin and destination are in the same local region; no transit hubs needed
        return []

    candidates: List[Tuple[int, float, CorridorHub]] = []
    seen_cities = set()

    # Also avoid hubs in origin or destination clusters
    excluded_clusters = set()
    if orig_stn.cluster_id:
        excluded_clusters.add(orig_stn.cluster_id)
    if dest_stn.cluster_id:
        excluded_clusters.add(dest_stn.cluster_id)

    for stn in STATIONS_DATA:
        if not stn.is_major_junction:
            continue
        if stn.code in (orig_stn.code, dest_stn.code):
            continue
        if stn.cluster_id and stn.cluster_id in excluded_clusters:
            continue

        d1 = haversine_distance(orig_stn.lat, orig_stn.lon, stn.lat, stn.lon)
        d2 = haversine_distance(stn.lat, stn.lon, dest_stn.lat, dest_stn.lon)

        # A transfer hub should be at least 70km away from origin and destination
        if d1 < 70.0 or d2 < 70.0:
            continue

        total_km = d1 + d2
        detour_ratio = round(total_km / direct_km, 3)

        # Allow hubs within 50% detour of direct distance
        if detour_ratio <= 1.50:
            if detour_ratio <= 1.15:
                tier = "PRIMARY"
                is_detour = False
            elif detour_ratio <= 1.30:
                tier = "SECONDARY"
                is_detour = False
            else:
                tier = "DETOUR_FALLBACK"
                is_detour = True

            hub_obj = CorridorHub(
                station_code=stn.code,
                station_name=stn.name,
                city=stn.city,
                state=stn.state,
                detour_ratio=detour_ratio,
                total_km=round(total_km, 1),
                corridor_tier=tier,
                is_detour=is_detour
            )
            # Prioritize genuine national hubs and city clusters over small wayside junctions
            is_national_hub = (stn.code in MAJOR_JUNCTION_CODES) or (stn.cluster_id is not None)
            candidates.append((0 if is_national_hub else 1, detour_ratio, hub_obj))

    # Sort by priority (major national junctions first, then lowest detour ratio)
    candidates.sort(key=lambda x: (x[0], x[1]))

    # Deduplicate by city/cluster (e.g. don't pick both KCG and SC, pick the best one!)
    selected: List[CorridorHub] = []
    for _, _, hub in candidates:
        stn = STATIONS_BY_CODE.get(hub.station_code)
        city_key = stn.cluster_id if (stn and stn.cluster_id) else hub.city
        if city_key not in seen_cities:
            seen_cities.add(city_key)
            selected.append(hub)
            if len(selected) >= max_hubs:
                break

    # If too few hubs found, append strategic junctions
    if len(selected) < 3:
        for code in ["BPL", "NGP", "ADI", "PUNE", "CNB", "BZA"]:
            if code not in [s.station_code for s in selected] and code not in (orig_stn.code, dest_stn.code):
                stn = STATIONS_BY_CODE.get(code)
                if stn:
                    d1 = haversine_distance(orig_stn.lat, orig_stn.lon, stn.lat, stn.lon)
                    d2 = haversine_distance(stn.lat, stn.lon, dest_stn.lat, dest_stn.lon)
                    selected.append(
                        CorridorHub(
                            station_code=stn.code,
                            station_name=stn.name,
                            city=stn.city,
                            state=stn.state,
                            detour_ratio=round((d1 + d2) / direct_km, 3),
                            total_km=round(d1 + d2, 1),
                            corridor_tier="SECONDARY",
                            is_detour=True
                        )
                    )
            if len(selected) >= max_hubs:
                break

    return selected
