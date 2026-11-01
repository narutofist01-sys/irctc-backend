"""
High-Speed Asynchronous Indian Railways Live API Client.
Features connection pooling, in-memory TTL caching, rate-limit semaphore, and retry logic.
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional
from MultiFeatures.IndianRailway import confirmtkt

logger = logging.getLogger("IrctcAgent.Client")


def safe_int_fare(raw_fare: Any) -> int:
    """Safely converts fare string/int to int, default 0."""
    if not raw_fare:
        return 0
    try:
        clean = re.sub(r"[^\d]", "", str(raw_fare))
        return int(clean) if clean else 0
    except Exception:
        return 0


class AsyncTrainClient:
    """
    Optimized client that interfaces with Indian Railways live reservation engine.
    """

    def __init__(self, max_concurrency: int = 15, cache_ttl_seconds: int = 900):
        self._ct = confirmtkt.Confirmtkt()
        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._cache_ttl = cache_ttl_seconds
        self._lock = asyncio.Lock()

    def _cache_key(self, src: str, dest: str, doj: str, quota: str) -> str:
        return f"{src.upper()}:{dest.upper()}:{doj}:{quota.upper()}"

    async def fetch_trains(
        self,
        src: str,
        dest: str,
        doj: str,
        quota: str = "GN",
        retries: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Fetch all trains and real-time seat availability between two stations.
        """
        src = src.upper().strip()
        dest = dest.upper().strip()
        key = self._cache_key(src, dest, doj, quota)

        # Check Cache
        now = time.time()
        async with self._lock:
            if key in self._cache:
                timestamp, cached_trains = self._cache[key]
                if (now - timestamp) < self._cache_ttl:
                    return cached_trains

        async with self._semaphore:
            last_err = None
            for attempt in range(1, retries + 1):
                try:
                    raw_resp = await self._ct.available_trains(src, dest, doj, quota)
                    if not raw_resp or not isinstance(raw_resp, dict):
                        trains = []
                    else:
                        trains = raw_resp.get("trainBtwnStnsList") or []

                    normalized = self._normalize_trains(trains, src, dest, doj)

                    async with self._lock:
                        self._cache[key] = (now, normalized)
                    return normalized

                except Exception as e:
                    last_err = e
                    if attempt < retries:
                        await asyncio.sleep(0.3 * attempt)

            logger.warning(f"Could not fetch {src}->{dest} on {doj}: {last_err}")
            return []

    def _normalize_trains(
        self,
        trains: List[Dict[str, Any]],
        queried_src: str,
        queried_dest: str,
        doj: str
    ) -> List[Dict[str, Any]]:
        normalized = []
        for t in trains:
            tno = t.get("trainNumber") or t.get("TrainNo")
            tname = t.get("trainName") or t.get("TrainName")
            if not tno:
                continue

            raw_cache = t.get("avaiblitycache") or {}
            class_availability = {}
            fares_by_class = {}

            for cls_code, cinfo in raw_cache.items():
                if not isinstance(cinfo, dict):
                    continue
                raw_status = cinfo.get("Availability") or ""
                prediction = cinfo.get("Prediction") or ""
                fare_int = safe_int_fare(cinfo.get("Fare"))

                if fare_int > 0:
                    fares_by_class[cls_code] = fare_int

                is_avail = False
                is_rac = False
                is_wl = False
                is_regret = False

                upper_status = raw_status.upper().strip()

                if "AVAILABLE" in upper_status or "CURR_AVBL" in upper_status:
                    if not upper_status.startswith("NOT"):
                        is_avail = True
                elif "RAC" in upper_status:
                    is_rac = True
                elif "REGRET" in upper_status or "NOT AVAILABLE" in upper_status:
                    is_regret = True
                elif "WL" in upper_status:
                    is_wl = True

                class_availability[cls_code] = {
                    "raw_status": raw_status,
                    "prediction": prediction,
                    "fare": fare_int,
                    "is_available": is_avail,
                    "is_rac": is_rac,
                    "is_waitlist": is_wl,
                    "is_regret": is_regret
                }

            normalized.append({
                "train_number": str(tno),
                "train_name": str(tname),
                "from_station": t.get("fromStnCode") or queried_src,
                "to_station": t.get("toStnCode") or queried_dest,
                "departure_time": t.get("departureTime", "00:00"),
                "arrival_time": t.get("arrivalTime", "00:00"),
                "duration": t.get("duration", "0h 0m"),
                "distance": t.get("distance", 0),
                "doj": doj,
                "availability": class_availability,
                "fares_by_class": fares_by_class
            })

        return normalized
