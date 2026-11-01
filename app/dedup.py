"""
Canonical Deduplication and Grouping Engine for Train Itineraries.
Eliminates duplicate route cards caused by multi-station clusters, merges seat availability,
and calculates combined fares across classes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class NormalizedLeg:
    train_number: str
    train_name: str
    from_station: str
    to_station: str
    dep_datetime: datetime
    arr_datetime: datetime
    duration_str: str
    availability: Dict[str, Dict[str, Any]]
    fares_by_class: Dict[str, int]
    alt_from_stations: List[str] = field(default_factory=list)
    alt_to_stations: List[str] = field(default_factory=list)

    @property
    def dep_formatted(self) -> str:
        return self.dep_datetime.strftime("%d-%b %H:%M")

    @property
    def arr_formatted(self) -> str:
        return self.arr_datetime.strftime("%d-%b %H:%M")


@dataclass
class CleanItinerary:
    itinerary_id: str
    route_type: str  # "DIRECT" or "1_TRANSFER"
    origin: str
    destination: str
    transit_hub: Optional[str]
    corridor_name: str
    is_detour: bool
    detour_ratio: float
    legs: List[NormalizedLeg]
    layover_minutes: int
    total_duration_minutes: int
    transfer_type: str
    layover_risk: str
    fares_by_class: Dict[str, int]
    best_fare: int
    best_fare_class: str
    score: float = 0.0
    recommendation_rank: int = 0
    viable_classes: List[str] = field(default_factory=list)
    status_summary: str = ""
    booking_confidence: str = "WAITLIST"  # "CONFIRMED", "RAC", "WAITLIST", "REGRET"
    min_waitlist: int = 999999
    inter_station_transfer: bool = False
    hub_distance_km: float = 0.0
    recommended_cab_mins: int = 0
    confirmation_probability: int = 0
    booking_origin: Optional[str] = None
    boarding_station: Optional[str] = None
    split_station: Optional[str] = None
    lifehack_type: Optional[str] = None
    lifehack_tip: Optional[str] = None
    irctc_link: Optional[str] = None

    @property
    def total_duration_str(self) -> str:
        h = self.total_duration_minutes // 60
        m = self.total_duration_minutes % 60
        return f"{h}h {m:02d}m"

    @property
    def layover_str(self) -> str:
        if self.layover_minutes <= 0:
            return "Direct"
        h = self.layover_minutes // 60
        m = self.layover_minutes % 60
        return f"{h}h {m:02d}m"


def deduplicate_direct_routes(raw_direct_itineraries: List[CleanItinerary]) -> List[CleanItinerary]:
    """Deduplicates direct trains that serve multiple satellite stations in the same city."""
    grouped: Dict[Tuple[str, str], CleanItinerary] = {}

    for itin in raw_direct_itineraries:
        leg = itin.legs[0]
        # Key: (train_number, departure_time_formatted)
        key = (leg.train_number, leg.dep_datetime.strftime("%Y-%m-%d %H:%M"))

        if key not in grouped:
            grouped[key] = itin
        else:
            existing = grouped[key]
            # Merge alternative origin / destination
            if leg.from_station not in existing.legs[0].alt_from_stations and leg.from_station != existing.legs[0].from_station:
                existing.legs[0].alt_from_stations.append(leg.from_station)
            if leg.to_station not in existing.legs[0].alt_to_stations and leg.to_station != existing.legs[0].to_station:
                existing.legs[0].alt_to_stations.append(leg.to_station)

            # Merge any extra class seats if available
            for cls, cinfo in leg.availability.items():
                if cls not in existing.legs[0].availability or (
                    not existing.legs[0].availability[cls].get("is_available") and cinfo.get("is_available")
                ):
                    existing.legs[0].availability[cls] = cinfo

    return list(grouped.values())


def deduplicate_transfer_routes(raw_transfer_itineraries: List[CleanItinerary]) -> List[CleanItinerary]:
    """
    Deduplicates 1-transfer routes that share the same underlying train numbers and dates.
    """
    grouped: Dict[Tuple[str, str, str, str, str], CleanItinerary] = {}

    for itin in raw_transfer_itineraries:
        leg1 = itin.legs[0]
        leg2 = itin.legs[1]

        # Key: (Train1, Train1 Dep, Transit Hub, Train2, Train2 Dep)
        key = (
            leg1.train_number,
            leg1.dep_datetime.strftime("%Y-%m-%d %H:%M"),
            itin.transit_hub or leg1.to_station,
            leg2.train_number,
            leg2.dep_datetime.strftime("%Y-%m-%d %H:%M"),
        )

        if key not in grouped:
            grouped[key] = itin
        else:
            existing = grouped[key]

            # Merge alternative satellite terminals
            if leg1.from_station != existing.legs[0].from_station and leg1.from_station not in existing.legs[0].alt_from_stations:
                existing.legs[0].alt_from_stations.append(leg1.from_station)
            if leg2.to_station != existing.legs[1].to_station and leg2.to_station not in existing.legs[1].alt_to_stations:
                existing.legs[1].alt_to_stations.append(leg2.to_station)

            # Prefer the one with better layover or same station transfer
            if "Same Station" in itin.transfer_type and "Same Station" not in existing.transfer_type:
                grouped[key] = itin

    return list(grouped.values())
