"""
Indian Railways Metadata, Quota Engine, Train Classification & Fare Calculation.
Provides structured definitions for all 8 IRCTC Quotas, high-speed train classifiers
(Vande Bharat, Rajdhani, Shatabdi, Tejas, Duronto, Amrit Bharat), and IRCTC fare breakdown formula.
"""

import math
import re
from typing import Any, Dict, List, Optional


# Comprehensive Indian Railways Quotas
ALL_QUOTAS: Dict[str, Dict[str, Any]] = {
    "GN": {
        "code": "GN",
        "name": "General Quota",
        "short_name": "General",
        "desc": "Standard open allocation for all passengers",
        "eligibility": "All passengers",
        "advance_days": 120,
    },
    "TQ": {
        "code": "TQ",
        "name": "Tatkal Quota",
        "short_name": "Tatkal",
        "desc": "Emergency reservation opening 10:00 AM (AC) and 11:00 AM (Non-AC) 1 day before journey",
        "eligibility": "All passengers (identity proof required)",
        "advance_days": 1,
    },
    "PT": {
        "code": "PT",
        "name": "Premium Tatkal Quota",
        "short_name": "Premium Tatkal",
        "desc": "Dynamic fare quota with immediate confirmed allocation. No waitlist/RAC.",
        "eligibility": "All passengers (dynamic pricing, no refund on cancellation)",
        "advance_days": 1,
    },
    "LD": {
        "code": "LD",
        "name": "Ladies Quota",
        "short_name": "Ladies",
        "desc": "Dedicated coach/berths for female solo travelers or women traveling with children under 12",
        "eligibility": "Female solo travelers or with children < 12 yrs",
        "advance_days": 120,
    },
    "SS": {
        "code": "SS",
        "name": "Senior Citizen / Lower Berth",
        "short_name": "Senior Citizen",
        "desc": "Guaranteed Lower Berths reserved for senior citizens (Men 60+, Women 45+) traveling solo or as pair",
        "eligibility": "Men 60+ / Women 45+ (max 2 passengers)",
        "advance_days": 120,
    },
    "HP": {
        "code": "HP",
        "name": "Divyangjan / Disability Quota",
        "short_name": "Divyangjan",
        "desc": "Concession and dedicated lower berths with escort berth for persons with disabilities",
        "eligibility": "Differently abled passengers holding Railway Unique ID card",
        "advance_days": 120,
    },
    "FT": {
        "code": "FT",
        "name": "Foreign Tourist Quota",
        "short_name": "Foreign Tourist",
        "desc": "Available up to 365 days in advance for international tourists and NRIs",
        "eligibility": "Foreign passport holders and Non-Resident Indians",
        "advance_days": 365,
    },
    "DF": {
        "code": "DF",
        "name": "Defence Quota",
        "short_name": "Defence",
        "desc": "Berths reserved for Indian Army, Navy, Air Force and Paramilitary personnel",
        "eligibility": "Armed forces personnel on official duty or leave warrant",
        "advance_days": 120,
    },
}


# High-Speed & Train Category Definitions
TRAIN_CATEGORIES: List[Dict[str, Any]] = [
    {
        "id": "ALL",
        "label": "All Trains",
        "badge": "ALL",
        "description": "Show all train types"
    },
    {
        "id": "VANDE_BHARAT",
        "label": "Vande Bharat",
        "badge": "VB",
        "description": "Semi-high speed premium express (160 km/h)"
    },
    {
        "id": "RAJDHANI",
        "label": "Rajdhani Express",
        "badge": "RAJ",
        "description": "Fully air-conditioned luxury connecting capital cities"
    },
    {
        "id": "SHATABDI",
        "label": "Shatabdi / Jan Shatabdi",
        "badge": "SHT",
        "description": "Day-time superfast inter-city chair car service"
    },
    {
        "id": "TEJAS",
        "label": "Tejas Express",
        "badge": "TEJAS",
        "description": "Modern high-speed semi-luxury trains"
    },
    {
        "id": "DURONTO",
        "label": "Duronto Express",
        "badge": "DURONTO",
        "description": "Non-stop point-to-point express trains"
    },
    {
        "id": "AMRIT_BHARAT",
        "label": "Amrit Bharat",
        "badge": "AMRIT",
        "description": "Push-pull non-AC superfast express trains"
    },
    {
        "id": "GARIB_RATH",
        "label": "Garib Rath / Humsafar",
        "badge": "GR/HUM",
        "description": "Affordable 3AC economy & all-3AC luxury express"
    },
    {
        "id": "SUPERFAST",
        "label": "Superfast / Mail Express",
        "badge": "SF/EXP",
        "description": "Regular long-distance express and superfast trains"
    }
]


def classify_train(train_no: str, train_name: str) -> Dict[str, str]:
    """
    Classifies an Indian Railways train into its category based on name and number patterns.
    """
    name_upper = str(train_name or "").upper()
    tno_clean = "".join(filter(str.isdigit, str(train_no or "")))

    if "VANDE BHARAT" in name_upper or "VB EXP" in name_upper or "VANDE" in name_upper:
        return {
            "category": "VANDE_BHARAT",
            "label": "Vande Bharat Express",
            "badge": "VB",
            "speed_tier": "Semi High-Speed (160 km/h)",
            "color": "emerald"
        }
    elif "RAJDHANI" in name_upper:
        return {
            "category": "RAJDHANI",
            "label": "Rajdhani Express",
            "badge": "RAJ",
            "speed_tier": "Superfast Priority (130 km/h)",
            "color": "red"
        }
    elif "SHATABDI" in name_upper or "JAN SHATABDI" in name_upper:
        return {
            "category": "SHATABDI",
            "label": "Shatabdi Express",
            "badge": "SHT",
            "speed_tier": "Superfast Day Express (130 km/h)",
            "color": "blue"
        }
    elif "TEJAS" in name_upper:
        return {
            "category": "TEJAS",
            "label": "Tejas Express",
            "badge": "TEJAS",
            "speed_tier": "Semi High-Speed (140 km/h)",
            "color": "amber"
        }
    elif "DURONTO" in name_upper:
        return {
            "category": "DURONTO",
            "label": "Duronto Express",
            "badge": "DURONTO",
            "speed_tier": "Non-Stop Express (130 km/h)",
            "color": "teal"
        }
    elif "AMRIT BHARAT" in name_upper:
        return {
            "category": "AMRIT_BHARAT",
            "label": "Amrit Bharat Express",
            "badge": "AMRIT",
            "speed_tier": "Push-Pull Express (130 km/h)",
            "color": "orange"
        }
    elif "GARIB RATH" in name_upper:
        return {
            "category": "GARIB_RATH",
            "label": "Garib Rath Express",
            "badge": "GR",
            "speed_tier": "Economy AC Superfast",
            "color": "green"
        }
    elif "HUMSAFAR" in name_upper:
        return {
            "category": "GARIB_RATH",
            "label": "Humsafar Express",
            "badge": "HUM",
            "speed_tier": "All-3AC Superfast",
            "color": "indigo"
        }
    else:
        return {
            "category": "SUPERFAST",
            "label": "Superfast / Mail Express",
            "badge": "SF/EXP",
            "speed_tier": "Standard Express (110 km/h)",
            "color": "zinc"
        }


def calculate_fare_breakdown(total_fare: int, travel_class: Optional[str] = "3A") -> Dict[str, Any]:
    """
    Reverse-engineers official IRCTC fare breakdown formula:
    - Base Fare
    - Reservation Charge: SL: ₹20, 3A/3E/CC: ₹40, 2A: ₹50, 1A/EC: ₹60, 2S: ₹15
    - Superfast Surcharge: SL/2S: ₹30, AC: ₹45
    - Dynamic Fare / Tatkal Surge: Remainder
    - GST: 5% on AC classes, 0% on Sleeper/2S
    """
    cls_upper = str(travel_class or "3A").upper().strip()

    # Reservation charges
    res_charges = {
        "1A": 60, "EC": 60,
        "2A": 50,
        "3A": 40, "3E": 40, "CC": 40,
        "SL": 20,
        "2S": 15
    }
    reservation_fee = res_charges.get(cls_upper, 40)

    # Superfast surcharge
    is_ac = cls_upper in ["1A", "2A", "3A", "3E", "CC", "EC", "EA"]
    superfast_charge = 45 if is_ac else 30

    if total_fare <= 0:
        return {
            "total_fare": 0,
            "base_fare": 0,
            "reservation_fee": reservation_fee,
            "superfast_surcharge": superfast_charge,
            "dynamic_surge": 0,
            "gst": 0,
            "gst_rate": "5%" if is_ac else "0%",
            "travel_class": cls_upper
        }

    # GST calculation: AC classes include 5% GST on (Base + Reservation + Superfast + Surge)
    if is_ac:
        net_before_gst = round(total_fare / 1.05)
        gst_amount = total_fare - net_before_gst
    else:
        net_before_gst = total_fare
        gst_amount = 0

    fixed_charges = reservation_fee + superfast_charge
    base_fare = max(50, net_before_gst - fixed_charges)
    dynamic_surge = max(0, net_before_gst - (base_fare + fixed_charges))

    return {
        "total_fare": total_fare,
        "base_fare": base_fare,
        "reservation_fee": reservation_fee,
        "superfast_surcharge": superfast_charge,
        "dynamic_surge": dynamic_surge,
        "gst": gst_amount,
        "gst_rate": "5%" if is_ac else "0%",
        "travel_class": cls_upper,
        "currency": "INR"
    }
