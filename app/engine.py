"""
Universal Asynchronous Search Pipeline for Indian Railways.
Provides both direct execution and real-time streaming (SSE) search with dynamic hub discovery.
"""

import asyncio
import datetime
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple

try:
    from app.client import AsyncTrainClient
    from app.corridor import CorridorHub, select_corridor_hubs
    from app.dedup import (
        CleanItinerary,
        NormalizedLeg,
        deduplicate_direct_routes,
        deduplicate_transfer_routes,
    )
    from app.scorer import ItineraryScorer
    from app.stations import (
        CITY_CLUSTERS,
        STATIONS_BY_CODE,
        get_cluster_station_codes,
        haversine_distance,
    )
    from app.rail_metadata import classify_train
except ImportError:
    from backend.app.client import AsyncTrainClient
    from backend.app.corridor import CorridorHub, select_corridor_hubs
    from backend.app.dedup import (
        CleanItinerary,
        NormalizedLeg,
        deduplicate_direct_routes,
        deduplicate_transfer_routes,
    )
    from backend.app.scorer import ItineraryScorer
    from backend.app.stations import (
        CITY_CLUSTERS,
        STATIONS_BY_CODE,
        get_cluster_station_codes,
        haversine_distance,
    )
    from backend.app.rail_metadata import classify_train

logger = logging.getLogger("IrctcAgent.Engine")


def parse_duration_to_minutes(dur_str: str) -> int:
    """Parse duration strings like '18h 45m', '8h', '45m' into integer minutes."""
    if not dur_str:
        return 0
    hours = 0
    minutes = 0
    h_match = re.search(r"(\d+)\s*h", dur_str, re.IGNORECASE)
    m_match = re.search(r"(\d+)\s*m", dur_str, re.IGNORECASE)
    if h_match:
        hours = int(h_match.group(1))
    if m_match:
        minutes = int(m_match.group(1))
    if not h_match and not m_match:
        colon_match = re.match(r"^(\d{1,2}):(\d{2})$", dur_str.strip())
        if colon_match:
            hours = int(colon_match.group(1))
            minutes = int(colon_match.group(2))
    return hours * 60 + minutes


def normalize_date_ddmmyyyy(date_str: str) -> str:
    """Normalizes any date string (YYYY-MM-DD, DD-MM-YYYY, YYYY/MM/DD, DD/MM/YYYY) into DD-MM-YYYY."""
    if not date_str:
        return datetime.datetime.now().strftime("%d-%m-%Y")
    clean = str(date_str).strip().replace("/", "-")
    parts = clean.split("-")
    if len(parts) == 3:
        if len(parts[0]) == 4:  # YYYY-MM-DD
            return f"{parts[2].zfill(2)}-{parts[1].zfill(2)}-{parts[0]}"
        elif len(parts[2]) == 4:  # DD-MM-YYYY
            return f"{parts[0].zfill(2)}-{parts[1].zfill(2)}-{parts[2]}"
    return clean


def generate_irctc_link(
    train_no: str,
    doj: str,
    src: str,
    dest: str,
    cls: str = "3A",
    quota: str = "GN",
    boarding_stn: Optional[str] = None
) -> str:
    """Constructs official direct IRCTC e-ticketing URL with pre-filled journey details."""
    clean_doj = normalize_date_ddmmyyyy(doj)
    parts = clean_doj.split("-")
    dt_compact = f"{parts[2]}{parts[1]}{parts[0]}" if len(parts) == 3 else clean_doj
    clean_no = "".join(filter(str.isdigit, str(train_no))) or str(train_no)
    url = f"https://www.irctc.co.in/nget/booking?trainNo={clean_no}&date={dt_compact}&from={src}&to={dest}&class={cls}&quota={quota}"
    if boarding_stn and boarding_stn != src:
        url += f"&boardingStn={boarding_stn}"
    return url


class PublicSearchEngine:
    """
    Universal search engine for any origin and destination pair across India.
    """

    def __init__(self, client: Optional[AsyncTrainClient] = None):
        self.client = client or AsyncTrainClient()

    async def search_direct_trains(
        self,
        origin_code: str,
        dest_code: str,
        doj: str,
        quota: str = "GN"
    ) -> List[CleanItinerary]:
        """Searches direct trains between origin and destination clusters."""
        doj = normalize_date_ddmmyyyy(doj)
        origin_stations = get_cluster_station_codes(origin_code)
        dest_stations = get_cluster_station_codes(dest_code)

        tasks = []
        for src in origin_stations:
            for dst in dest_stations:
                tasks.append(self.client.fetch_trains(src, dst, doj, quota))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        raw_directs: List[CleanItinerary] = []
        for res in results:
            if isinstance(res, Exception) or not res:
                continue
            for t in res:
                dur_min = parse_duration_to_minutes(t["duration"])
                try:
                    dep_dt = datetime.datetime.strptime(f"{doj} {t['departure_time']}", "%d-%m-%Y %H:%M")
                except Exception:
                    continue
                arr_dt = dep_dt + datetime.timedelta(minutes=dur_min)

                leg = NormalizedLeg(
                    train_number=t["train_number"],
                    train_name=t["train_name"],
                    from_station=t["from_station"],
                    to_station=t["to_station"],
                    dep_datetime=dep_dt,
                    arr_datetime=arr_dt,
                    duration_str=t["duration"],
                    availability=t["availability"],
                    fares_by_class=t["fares_by_class"],
                )

                best_fare = min(t["fares_by_class"].values()) if t["fares_by_class"] else 0
                best_cls = min(t["fares_by_class"], key=t["fares_by_class"].get) if t["fares_by_class"] else "None"
                link = generate_irctc_link(t["train_number"], doj, leg.from_station, leg.to_station, best_cls, quota)

                itin = CleanItinerary(
                    itinerary_id=f"DIR-{t['train_number']}-{doj}",
                    route_type="DIRECT",
                    origin=leg.from_station,
                    destination=leg.to_station,
                    transit_hub=None,
                    corridor_name="Direct Line",
                    is_detour=False,
                    detour_ratio=1.0,
                    legs=[leg],
                    layover_minutes=0,
                    total_duration_minutes=dur_min,
                    transfer_type="Direct Journey",
                    layover_risk="None",
                    fares_by_class=t["fares_by_class"],
                    best_fare=best_fare,
                    best_fare_class=best_cls,
                    irctc_link=link,
                )
                raw_directs.append(itin)

        return deduplicate_direct_routes(raw_directs)

    async def search_transfer_trains(
        self,
        origin_code: str,
        dest_code: str,
        doj: str,
        quota: str = "GN",
        corridor_hubs: Optional[List[CorridorHub]] = None
    ) -> List[CleanItinerary]:
        """Searches 1-transfer routes through dynamically selected junction hubs."""
        doj = normalize_date_ddmmyyyy(doj)
        if corridor_hubs is None:
            corridor_hubs = select_corridor_hubs(origin_code, dest_code, max_hubs=10)

        if not corridor_hubs:
            return []

        origin_stations = get_cluster_station_codes(origin_code)
        dest_stations = get_cluster_station_codes(dest_code)

        raw_transfers: List[CleanItinerary] = []

        # Step A: Query Leg 1 (Origin Cluster -> Hubs) concurrently
        leg1_tasks = []
        for hub in corridor_hubs:
            hub_stations = get_cluster_station_codes(hub.station_code)
            for src in origin_stations:
                for hstn in hub_stations:
                    leg1_tasks.append((hub, self.client.fetch_trains(src, hstn, doj, quota)))

        leg1_results = await asyncio.gather(*(task for _, task in leg1_tasks), return_exceptions=True)

        # Map viable Leg 1 trains per hub
        hub_viable_leg1: Dict[str, List[Tuple[CorridorHub, Dict[str, Any], datetime.datetime, datetime.datetime, int]]] = {}
        for (hub, _), res in zip(leg1_tasks, leg1_results):
            if isinstance(res, Exception) or not res:
                continue
            for t1 in res:
                has_viable = any(
                    c.get("is_available") or c.get("is_rac") or c.get("is_waitlist")
                    for c in t1.get("availability", {}).values()
                )
                if not has_viable:
                    continue

                dur1 = parse_duration_to_minutes(t1["duration"])
                try:
                    dep1_dt = datetime.datetime.strptime(f"{doj} {t1['departure_time']}", "%d-%m-%Y %H:%M")
                except Exception:
                    continue
                arr1_dt = dep1_dt + datetime.timedelta(minutes=dur1)

                hub_key = hub.station_code
                if hub_key not in hub_viable_leg1:
                    hub_viable_leg1[hub_key] = []
                hub_viable_leg1[hub_key].append((hub, t1, dep1_dt, arr1_dt, dur1))

        # Step B: Concurrently query Leg 2 (Hubs -> Destination Cluster)
        leg2_queries = set()
        for hub_key, items in hub_viable_leg1.items():
            for hub, t1, _, arr1_dt, _ in items:
                hub_stations = get_cluster_station_codes(hub.station_code)
                l2_dates = [arr1_dt.strftime("%d-%m-%Y"), (arr1_dt + datetime.timedelta(days=1)).strftime("%d-%m-%Y")]
                for hstn in hub_stations:
                    for dst in dest_stations:
                        for l2_d in l2_dates:
                            leg2_queries.add((hstn, dst, l2_d))

        leg2_tasks = [
            (q, self.client.fetch_trains(q[0], q[1], q[2], quota))
            for q in leg2_queries
        ]
        leg2_results = await asyncio.gather(*(task for _, task in leg2_tasks), return_exceptions=True)

        leg2_cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        for (q, _), res in zip(leg2_tasks, leg2_results):
            if not isinstance(res, Exception) and res:
                leg2_cache[q] = res

        # Step C: Match connections
        for hub_key, items in hub_viable_leg1.items():
            for hub, t1, dep1_dt, arr1_dt, dur1 in items:
                hub_stations = get_cluster_station_codes(hub.station_code)
                l2_dates = [arr1_dt.strftime("%d-%m-%Y"), (arr1_dt + datetime.timedelta(days=1)).strftime("%d-%m-%Y")]

                for hstn in hub_stations:
                    for dst in dest_stations:
                        for l2_d in l2_dates:
                            t2_list = leg2_cache.get((hstn, dst, l2_d), [])
                            for t2 in t2_list:
                                has_viable_t2 = any(
                                    c.get("is_available") or c.get("is_rac") or c.get("is_waitlist")
                                    for c in t2.get("availability", {}).values()
                                )
                                if not has_viable_t2:
                                    continue

                                dur2 = parse_duration_to_minutes(t2["duration"])
                                try:
                                    dep2_dt = datetime.datetime.strptime(f"{t2['doj']} {t2['departure_time']}", "%d-%m-%Y %H:%M")
                                except Exception:
                                    continue
                                arr2_dt = dep2_dt + datetime.timedelta(minutes=dur2)

                                layover_min = int((dep2_dt - arr1_dt).total_seconds() / 60)

                                same_station = (t1["to_station"] == t2["from_station"])
                                inter_station = not same_station
                                hub_distance_km = 0.0
                                recommended_cab_mins = 0

                                if same_station:
                                    if not (60 <= layover_min <= 600):
                                        continue
                                    transfer_type = f"Same Station Transfer ({t1['to_station']})"
                                else:
                                    if not (150 <= layover_min <= 720):
                                        continue
                                    transfer_type = f"Cross-City Transfer ({t1['to_station']} \u2192 {t2['from_station']})"
                                    stn_a = STATIONS_BY_CODE.get(t1["to_station"])
                                    stn_b = STATIONS_BY_CODE.get(t2["from_station"])
                                    if stn_a and stn_b:
                                        hub_distance_km = round(haversine_distance(stn_a.lat, stn_a.lon, stn_b.lat, stn_b.lon), 1)
                                    recommended_cab_mins = max(20, int(hub_distance_km * 2.5 + 15)) if hub_distance_km > 0 else 30

                                if layover_min < 120:
                                    layover_risk = "Tight Layover (<2 hrs)"
                                elif layover_min > 420:
                                    layover_risk = "Long Layover (>7 hrs)"
                                else:
                                    layover_risk = "Comfortable Layover"

                                # Fares
                                combined_fares = {}
                                for cls in ["3A", "2A", "SL", "3E", "1A", "CC"]:
                                    f1 = t1["fares_by_class"].get(cls, 0)
                                    f2 = t2["fares_by_class"].get(cls, 0)
                                    if f1 > 0 and f2 > 0:
                                        combined_fares[cls] = f1 + f2

                                best_fare = min(combined_fares.values()) if combined_fares else (
                                    (min(t1["fares_by_class"].values()) if t1["fares_by_class"] else 0) +
                                    (min(t2["fares_by_class"].values()) if t2["fares_by_class"] else 0)
                                )
                                best_fare_class = min(combined_fares, key=combined_fares.get) if combined_fares else "Mixed"

                                leg1 = NormalizedLeg(
                                    train_number=t1["train_number"],
                                    train_name=t1["train_name"],
                                    from_station=t1["from_station"],
                                    to_station=t1["to_station"],
                                    dep_datetime=dep1_dt,
                                    arr_datetime=arr1_dt,
                                    duration_str=t1["duration"],
                                    availability=t1["availability"],
                                    fares_by_class=t1["fares_by_class"],
                                )
                                leg2 = NormalizedLeg(
                                    train_number=t2["train_number"],
                                    train_name=t2["train_name"],
                                    from_station=t2["from_station"],
                                    to_station=t2["to_station"],
                                    dep_datetime=dep2_dt,
                                    arr_datetime=arr2_dt,
                                    duration_str=t2["duration"],
                                    availability=t2["availability"],
                                    fares_by_class=t2["fares_by_class"],
                                )

                                link1 = generate_irctc_link(t1["train_number"], doj, leg1.from_station, leg2.to_station, best_fare_class, quota)
                                itin = CleanItinerary(
                                    itinerary_id=f"CONN-{hub.station_code}-{t1['train_number']}-{t2['train_number']}",
                                    route_type="1_TRANSFER",
                                    origin=leg1.from_station,
                                    destination=leg2.to_station,
                                    transit_hub=hub.station_code,
                                    corridor_name=f"{hub.city} ({hub.station_code}) Corridor",
                                    is_detour=hub.is_detour,
                                    detour_ratio=hub.detour_ratio,
                                    legs=[leg1, leg2],
                                    layover_minutes=layover_min,
                                    total_duration_minutes=dur1 + layover_min + dur2,
                                    transfer_type=transfer_type,
                                    layover_risk=layover_risk,
                                    fares_by_class=combined_fares,
                                    best_fare=best_fare,
                                    best_fare_class=best_fare_class,
                                    inter_station_transfer=inter_station,
                                    hub_distance_km=hub_distance_km,
                                    recommended_cab_mins=recommended_cab_mins,
                                    irctc_link=link1,
                                )
                                raw_transfers.append(itin)

        return deduplicate_transfer_routes(raw_transfers)

    async def search_lifehack_routes(
        self,
        origin_code: str,
        dest_code: str,
        doj: str,
        quota: str = "GN",
        direct_itins: Optional[List[CleanItinerary]] = None,
        corridor_hubs: Optional[List[CorridorHub]] = None
    ) -> List[CleanItinerary]:
        """
        Discovers IRCTC lifehacks:
        1. Same-Train Split Ticketing: Breaks journey on intermediate station on the SAME physical train
           when direct ticket is waitlisted.
        2. Point-Beyond Boarding: Books from originating station where General Quota has confirmed seats,
           and sets user's station as the official boarding point.
        """
        doj = normalize_date_ddmmyyyy(doj)
        lifehacks: List[CleanItinerary] = []
        if not direct_itins:
            return lifehacks

        if corridor_hubs is None:
            corridor_hubs = select_corridor_hubs(origin_code, dest_code, max_hubs=4)

        # 1. Same-Train Split Ticketing:
        for dir_itin in direct_itins:
            leg = dir_itin.legs[0]
            tno = leg.train_number
            tname = leg.train_name

            for hub in corridor_hubs[:3]:
                if hub.station_code == origin_code or hub.station_code == dest_code:
                    continue

                r1_task = self.client.fetch_trains(origin_code, hub.station_code, doj, quota)
                r2_task = self.client.fetch_trains(hub.station_code, dest_code, doj, quota)
                r1, r2 = await asyncio.gather(r1_task, r2_task, return_exceptions=True)

                if isinstance(r1, Exception) or not r1 or isinstance(r2, Exception) or not r2:
                    continue

                m1 = next((t for t in r1 if t["train_number"] == tno), None)
                m2 = next((t for t in r2 if t["train_number"] == tno), None)

                if m1 and m2:
                    common_classes = set(m1["availability"].keys()).intersection(set(m2["availability"].keys()))
                    viable_cls = None
                    for c in ["3A", "2A", "SL", "3E", "1A", "CC"]:
                        if c in common_classes:
                            a1 = m1["availability"][c]
                            a2 = m2["availability"][c]
                            if (a1.get("is_available") or a1.get("is_rac")) and (a2.get("is_available") or a2.get("is_rac")):
                                viable_cls = c
                                break

                    if viable_cls:
                        dur1 = parse_duration_to_minutes(m1["duration"])
                        dur2 = parse_duration_to_minutes(m2["duration"])
                        try:
                            dep1_dt = datetime.datetime.strptime(f"{doj} {m1['departure_time']}", "%d-%m-%Y %H:%M")
                        except Exception:
                            continue
                        arr1_dt = dep1_dt + datetime.timedelta(minutes=dur1)

                        try:
                            dep2_dt = datetime.datetime.strptime(f"{m2['doj']} {m2['departure_time']}", "%d-%m-%Y %H:%M")
                        except Exception:
                            dep2_dt = arr1_dt
                        arr2_dt = dep2_dt + datetime.timedelta(minutes=dur2)

                        combined_fares = {}
                        for c in ["3A", "2A", "SL", "3E", "1A", "CC"]:
                            f1 = m1["fares_by_class"].get(c, 0)
                            f2 = m2["fares_by_class"].get(c, 0)
                            if f1 > 0 and f2 > 0:
                                combined_fares[c] = f1 + f2

                        best_fare = min(combined_fares.values()) if combined_fares else 0
                        best_cls = min(combined_fares, key=combined_fares.get) if combined_fares else viable_cls

                        nleg1 = NormalizedLeg(
                            train_number=tno,
                            train_name=tname,
                            from_station=m1["from_station"],
                            to_station=m1["to_station"],
                            dep_datetime=dep1_dt,
                            arr_datetime=arr1_dt,
                            duration_str=m1["duration"],
                            availability=m1["availability"],
                            fares_by_class=m1["fares_by_class"],
                        )
                        nleg2 = NormalizedLeg(
                            train_number=tno,
                            train_name=tname,
                            from_station=m2["from_station"],
                            to_station=m2["to_station"],
                            dep_datetime=dep2_dt,
                            arr_datetime=arr2_dt,
                            duration_str=m2["duration"],
                            availability=m2["availability"],
                            fares_by_class=m2["fares_by_class"],
                        )

                        link = generate_irctc_link(tno, doj, m1["from_station"], m2["to_station"], best_cls, quota)

                        split_itin = CleanItinerary(
                            itinerary_id=f"SPLIT-{tno}-{hub.station_code}-{doj}",
                            route_type="SAME_TRAIN_SPLIT",
                            origin=m1["from_station"],
                            destination=m2["to_station"],
                            transit_hub=hub.station_code,
                            corridor_name=f"Same Train #{tno} Split via {hub.station_code}",
                            is_detour=False,
                            detour_ratio=1.0,
                            legs=[nleg1, nleg2],
                            layover_minutes=0,
                            total_duration_minutes=dur1 + dur2,
                            transfer_type=f"Stay in Same Train (Split at {hub.station_code})",
                            layover_risk="Zero Risk (Same Coach/Train)",
                            fares_by_class=combined_fares,
                            best_fare=best_fare,
                            best_fare_class=best_cls,
                            split_station=hub.station_code,
                            lifehack_type="SAME_TRAIN_SPLIT",
                            lifehack_tip=f"Same-Train Secret: Direct ticket is waitlisted, but booking Leg 1 to {hub.station_code} and Leg 2 to {dest_code} on the same train unlocks 100% confirmed berths in {viable_cls} without changing seats!",
                            irctc_link=link
                        )
                        lifehacks.append(split_itin)
                        break

        # 2. Point-Beyond Discovery:
        cluster_stations = get_cluster_station_codes(origin_code)
        for alt_src in cluster_stations:
            if alt_src == origin_code:
                continue
            alt_res = await self.client.fetch_trains(alt_src, dest_code, doj, quota)
            for at in alt_res:
                avail = at.get("availability", {})
                for cls_name, cinfo in avail.items():
                    if cinfo.get("is_available"):
                        dur = parse_duration_to_minutes(at["duration"])
                        try:
                            dep_dt = datetime.datetime.strptime(f"{doj} {at['departure_time']}", "%d-%m-%Y %H:%M")
                        except Exception:
                            continue
                        arr_dt = dep_dt + datetime.timedelta(minutes=dur)

                        nleg = NormalizedLeg(
                            train_number=at["train_number"],
                            train_name=at["train_name"],
                            from_station=at["from_station"],
                            to_station=at["to_station"],
                            dep_datetime=dep_dt,
                            arr_datetime=arr_dt,
                            duration_str=at["duration"],
                            availability=avail,
                            fares_by_class=at["fares_by_class"],
                        )
                        link = generate_irctc_link(
                            at["train_number"], doj, alt_src, dest_code, cls_name, quota, boarding_stn=origin_code
                        )
                        best_fare = at["fares_by_class"].get(cls_name, 0)
                        pt_itin = CleanItinerary(
                            itinerary_id=f"PTBEYOND-{at['train_number']}-{alt_src}-{doj}",
                            route_type="POINT_BEYOND",
                            origin=origin_code,
                            destination=dest_code,
                            transit_hub=None,
                            corridor_name=f"Point-Beyond from {alt_src}",
                            is_detour=False,
                            detour_ratio=1.0,
                            legs=[nleg],
                            layover_minutes=0,
                            total_duration_minutes=dur,
                            transfer_type="Direct Travel (Origin Quota Hack)",
                            layover_risk="None",
                            fares_by_class=at["fares_by_class"],
                            best_fare=best_fare,
                            best_fare_class=cls_name,
                            booking_origin=alt_src,
                            boarding_station=origin_code,
                            lifehack_type="POINT_BEYOND",
                            lifehack_tip=f"Point-Beyond Lifehack: Book from originating station {alt_src} to tap into confirmed General Quota, and set your Boarding Station as {origin_code} on IRCTC with zero penalty!",
                            irctc_link=link
                        )
                        lifehacks.append(pt_itin)
                        break

        return lifehacks

    async def search_all(
        self,
        origin_code: str,
        dest_code: str,
        doj: str,
        quota: str = "GN",
        preferred_class: Optional[str] = None,
        include_splits: bool = False
    ) -> List[CleanItinerary]:
        """
        Executes search and returns scored, deduplicated itineraries.
        If include_splits is False (default), only direct trains are queried and returned.
        If include_splits is True, intermediate corridor transfer hubs and lifehacks are evaluated.
        """
        doj = normalize_date_ddmmyyyy(doj)
        directs = await self.search_direct_trains(origin_code, dest_code, doj, quota)

        if not include_splits:
            return ItineraryScorer.rank_itineraries(directs, preferred_class)

        corridor_hubs = select_corridor_hubs(origin_code, dest_code, max_hubs=10)
        transfer_task = self.search_transfer_trains(origin_code, dest_code, doj, quota, corridor_hubs)
        lifehacks_task = self.search_lifehack_routes(origin_code, dest_code, doj, quota, directs, corridor_hubs)

        transfers, lifehacks = await asyncio.gather(transfer_task, lifehacks_task)

        combined = directs + lifehacks + transfers
        return ItineraryScorer.rank_itineraries(combined, preferred_class)

    async def stream_search(
        self,
        origin_code: str,
        dest_code: str,
        doj: str,
        quota: str = "GN",
        include_splits: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Progressive streaming generator emitting Server-Sent Events (SSE).
        Yields direct trains immediately, then corridor updates as they are found if include_splits is True.
        """
        doj = normalize_date_ddmmyyyy(doj)
        corridor_hubs = select_corridor_hubs(origin_code, dest_code, max_hubs=10) if include_splits else []

        yield {
            "type": "init",
            "origin": origin_code.upper(),
            "destination": dest_code.upper(),
            "date": doj,
            "corridor_hubs": [
                {"code": h.station_code, "name": h.station_name, "city": h.city, "detour": h.detour_ratio}
                for h in corridor_hubs
            ]
        }

        # Step 1: Direct Trains Immediate Emission (<0.5s)
        directs = await self.search_direct_trains(origin_code, dest_code, doj, quota)
        scored_directs = ItineraryScorer.rank_itineraries(directs)
        yield {
            "type": "direct_trains",
            "count": len(scored_directs),
            "routes": [self._serialize_itin(it, quota=quota) for it in scored_directs]
        }

        if not include_splits:
            confirmed_count = sum(1 for it in scored_directs if it.booking_confidence == "CONFIRMED")
            lowest_fare = min((it.best_fare for it in scored_directs if it.best_fare > 0), default=0)
            yield {
                "type": "complete",
                "total_evaluated": len(scored_directs),
                "confirmed_count": confirmed_count,
                "lowest_fare": lowest_fare,
                "routes": [self._serialize_itin(it, quota=quota) for it in scored_directs[:80]]
            }
            return

        # Step 2: Search connecting hubs and lifehacks
        transfers_task = self.search_transfer_trains(origin_code, dest_code, doj, quota, corridor_hubs)
        lifehacks_task = self.search_lifehack_routes(origin_code, dest_code, doj, quota, directs, corridor_hubs)
        transfers, lifehacks = await asyncio.gather(transfers_task, lifehacks_task)

        all_itins = directs + lifehacks + transfers
        ranked = ItineraryScorer.rank_itineraries(all_itins)

        confirmed_count = sum(1 for it in ranked if it.booking_confidence == "CONFIRMED")
        lowest_fare = min((it.best_fare for it in ranked if it.best_fare > 0), default=0)

        yield {
            "type": "complete",
            "total_evaluated": len(ranked),
            "confirmed_count": confirmed_count,
            "lowest_fare": lowest_fare,
            "routes": [self._serialize_itin(it, quota=quota) for it in ranked[:80]]
        }

    def _serialize_itin(self, it: CleanItinerary, quota: str = "GN") -> Dict[str, Any]:
        first_leg = it.legs[0] if it.legs else None
        last_leg = it.legs[-1] if it.legs else None

        primary_cat = "SUPERFAST"
        if first_leg:
            primary_cat = classify_train(first_leg.train_number, first_leg.train_name).get("category", "SUPERFAST")

        irctc_link = it.irctc_link
        if not irctc_link and first_leg and last_leg:
            irctc_link = generate_irctc_link(
                train_no=first_leg.train_number,
                doj=first_leg.dep_datetime.strftime("%d-%m-%Y"),
                src=first_leg.from_station,
                dest=last_leg.to_station,
                cls=it.best_fare_class if it.best_fare_class and it.best_fare_class != "None" else "3A",
                quota=quota
            )

        return {
            "id": it.itinerary_id,
            "rank": it.recommendation_rank,
            "score": it.score,
            "type": it.route_type,
            "origin": it.origin,
            "destination": it.destination,
            "hub": it.transit_hub or "Direct",
            "corridor": it.corridor_name,
            "is_detour": it.is_detour,
            "detour_ratio": it.detour_ratio,
            "transfer_type": it.transfer_type,
            "inter_station_transfer": it.inter_station_transfer,
            "hub_distance_km": it.hub_distance_km,
            "recommended_cab_mins": it.recommended_cab_mins,
            "confirmation_probability": it.confirmation_probability,
            "min_waitlist": it.min_waitlist,
            "layover_risk": it.layover_risk,
            "layover_minutes": it.layover_minutes,
            "layover_str": it.layover_str,
            "total_duration_minutes": it.total_duration_minutes,
            "total_duration_str": it.total_duration_str,
            "best_fare": it.best_fare,
            "best_fare_class": it.best_fare_class,
            "fares_by_class": it.fares_by_class,
            "booking_confidence": it.booking_confidence,
            "summary": it.status_summary,
            "primary_category": primary_cat,
            "lifehack_type": it.lifehack_type,
            "lifehack_tip": it.lifehack_tip,
            "booking_origin": it.booking_origin,
            "boarding_station": it.boarding_station,
            "split_station": it.split_station,
            "irctc_link": irctc_link,
            "legs": [
                {
                    "train_no": l.train_number,
                    "train_name": l.train_name,
                    "category": classify_train(l.train_number, l.train_name),
                    "from": l.from_station,
                    "to": l.to_station,
                    "departure": l.dep_formatted,
                    "arrival": l.arr_formatted,
                    "dep_time_only": l.dep_datetime.strftime("%H:%M"),
                    "arr_time_only": l.arr_datetime.strftime("%H:%M"),
                    "day_of_journey": l.dep_datetime.strftime("%a, %d %b"),
                    "duration": l.duration_str,
                    "alt_from": l.alt_from_stations,
                    "alt_to": l.alt_to_stations,
                    "seats": {
                        cls: cinfo["raw_status"]
                        for cls, cinfo in l.availability.items()
                        if cinfo.get("raw_status")
                    },
                    "fares": l.fares_by_class
                }
                for l in it.legs
            ]
        }
