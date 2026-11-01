"""
IRCTC AGENT Seat Watchdog & Train Charting Preparation Engine.
Tracks chart preparation timelines (1st Chart @ 4hrs, 2nd Chart @ 30mins)
and manages subscriber seat availability watchdogs.
"""

from datetime import datetime, timedelta
import uuid
from typing import Any, Dict, List, Optional


class WatchdogManager:
    """Manages active seat availability watchdog subscriptions."""

    def __init__(self):
        self._alerts: Dict[str, Dict[str, Any]] = {}

    def subscribe(
        self,
        train_no: str,
        doj: str,
        from_stn: str,
        to_stn: str,
        travel_class: str = "3A",
        quota: str = "GN",
        target_status: str = "AVAILABLE",
        notify_channel: str = "browser_push",
        contact: str = ""
    ) -> Dict[str, Any]:
        alert_id = f"WD-{uuid.uuid4().hex[:8].upper()}"
        alert_record = {
            "id": alert_id,
            "train_no": str(train_no),
            "doj": doj,
            "from_stn": from_stn.upper(),
            "to_stn": to_stn.upper(),
            "travel_class": travel_class.upper(),
            "quota": quota.upper(),
            "target_status": target_status.upper(),
            "notify_channel": notify_channel,
            "contact": contact or "In-App Notification",
            "created_at": datetime.now().isoformat(),
            "status": "ACTIVE",
            "last_checked": None,
            "last_seen_seats": "Checking..."
        }
        self._alerts[alert_id] = alert_record
        return alert_record

    def list_alerts(self) -> List[Dict[str, Any]]:
        return list(self._alerts.values())

    def remove_alert(self, alert_id: str) -> bool:
        if alert_id in self._alerts:
            del self._alerts[alert_id]
            return True
        return False

    async def check_all(self, client) -> List[Dict[str, Any]]:
        """Queries live seat status for all active subscriptions and flags transitions."""
        results = []
        for alert_id, alert in list(self._alerts.items()):
            if alert["status"] != "ACTIVE":
                continue
            try:
                trains = await client.fetch_trains(
                    alert["from_stn"],
                    alert["to_stn"],
                    alert["doj"],
                    alert["quota"]
                )
                target_train = next(
                    (t for t in trains if str(t.get("train_number")) == alert["train_no"]),
                    None
                )
                alert["last_checked"] = datetime.now().isoformat()
                if target_train:
                    avail = target_train.get("availability", {}).get(alert["travel_class"], {})
                    raw_status = avail.get("raw_status") or "WL/REGRET"
                    alert["last_seen_seats"] = raw_status
                    is_target_met = (
                        (alert["target_status"] == "AVAILABLE" and avail.get("is_available")) or
                        (alert["target_status"] == "RAC" and (avail.get("is_available") or avail.get("is_rac")))
                    )
                    if is_target_met:
                        alert["status"] = "TRIGGERED"
                        alert["triggered_at"] = datetime.now().isoformat()
                results.append(alert)
            except Exception as e:
                alert["last_checked"] = datetime.now().isoformat()
                alert["last_seen_seats"] = f"Error: {e}"
                results.append(alert)
        return results


def calculate_charting_status(
    departure_time_str: str,
    journey_date_str: str
) -> Dict[str, Any]:
    """
    Computes Indian Railways charting preparation status.
    - 1st Chart: Generated 4 hours before departure (or previous night for early morning trains).
    - 2nd Chart: Final chart generated 30 minutes before departure.
    - Current Booking: Counter open between 1st & 2nd chart for unsold berths at base fare.
    """
    try:
        dep_dt = datetime.strptime(f"{journey_date_str} {departure_time_str}", "%d-%m-%Y %H:%M")
    except Exception:
        # Fallback to today if format error
        dep_dt = datetime.now() + timedelta(hours=5)

    now = datetime.now()
    first_chart_dt = dep_dt - timedelta(hours=4)
    second_chart_dt = dep_dt - timedelta(minutes=30)

    mins_to_dep = int((dep_dt - now).total_seconds() / 60)
    mins_to_chart1 = int((first_chart_dt - now).total_seconds() / 60)
    mins_to_chart2 = int((second_chart_dt - now).total_seconds() / 60)

    is_first_chart = now >= first_chart_dt
    is_second_chart = now >= second_chart_dt
    is_current_booking = is_first_chart and not is_second_chart

    if is_second_chart:
        status_code = "CHART_FINALIZED"
        status_label = "Final Chart Prepared"
        tip = "Train departure is imminent (within 30 mins). Chart is closed."
    elif is_current_booking:
        status_code = "CURRENT_BOOKING_OPEN"
        status_label = "Current Reservation Open"
        tip = "First chart prepared! Vacant berths are now bookable online at flat base fare."
    else:
        status_code = "CHARTING_PENDING"
        hours_left = max(0, round(mins_to_chart1 / 60, 1))
        status_label = f"Chart 1 in {hours_left} hrs"
        tip = f"First chart will be generated at {first_chart_dt.strftime('%H:%M (%d %b)')}."

    return {
        "scheduled_departure": dep_dt.strftime("%d-%b %H:%M"),
        "first_chart_time": first_chart_dt.strftime("%d-%b %H:%M"),
        "second_chart_time": second_chart_dt.strftime("%d-%b %H:%M"),
        "is_first_chart_prepared": is_first_chart,
        "is_second_chart_prepared": is_second_chart,
        "is_current_booking_open": is_current_booking,
        "minutes_to_departure": mins_to_dep,
        "minutes_to_first_chart": mins_to_chart1,
        "status_code": status_code,
        "status_label": status_label,
        "guidance_tip": tip
    }


# Global watchdog manager singleton
watchdog_manager = WatchdogManager()
