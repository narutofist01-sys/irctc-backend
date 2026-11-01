"""
Universal Multi-Factor Scoring and Ranking Engine for Train Itineraries.
Prioritizes Confirmed/RAC seats, rewards direct lines, penalizes detours,
optimizes layovers, and assigns clear Recommendation ranks.
"""

from typing import List, Tuple
import re

try:
    from app.dedup import CleanItinerary, NormalizedLeg
except ImportError:
    from backend.app.dedup import CleanItinerary, NormalizedLeg


def extract_waitlist_num(raw_status: str) -> int:
    """Extracts numerical waitlist position from IRCTC status strings like GNWL86/WL42 -> 42."""
    s = str(raw_status).upper().strip()
    if not s or "REGRET" in s:
        return 999999
    if "AVAILABLE" in s or "CURR_AVBL" in s:
        return 0
    if "RAC" in s:
        return 0
    matches = re.findall(r"WL\s*(\d+)", s)
    if matches:
        return int(matches[-1])
    digits = re.findall(r"\d+", s)
    if digits:
        return int(digits[-1])
    return 999999


class ItineraryScorer:

    @staticmethod
    def evaluate_leg(leg: NormalizedLeg, preferred_class: str = None) -> Tuple[float, str, str, int, int]:
        best_score = -100.0
        best_cls = "None"
        best_desc = "No Seats"
        best_prob = 0
        best_wl = 999999

        class_order = ["3A", "2A", "SL", "3E", "1A", "CC", "2S"]
        if preferred_class and preferred_class in leg.availability:
            check_classes = [preferred_class] + [c for c in class_order if c != preferred_class]
        else:
            check_classes = class_order

        for cls in check_classes:
            if cls not in leg.availability:
                continue
            cinfo = leg.availability[cls]
            raw = cinfo.get("raw_status", "")
            pred = cinfo.get("prediction", "")
            fare_str = f" (\u20b9{leg.fares_by_class.get(cls, '')})" if cls in leg.fares_by_class else ""

            chance = 0
            if "%" in pred:
                try:
                    chance = int(pred.split("%")[0].strip())
                except Exception:
                    chance = 0

            cls_score = 0.0
            prob = 0
            wl_num = 999999
            if cinfo.get("is_available"):
                cls_score = 300.0  # Confirmed Seat
                prob = 100
                wl_num = 0
                desc = f"{cls} Confirmed [{raw}]{fare_str}"
            elif cinfo.get("is_rac"):
                cls_score = 220.0  # Guaranteed Boarding & Half-Berth
                prob = chance if chance > 0 else 90
                wl_num = 0
                desc = f"{cls} RAC [{raw}]{fare_str}"
            elif cinfo.get("is_waitlist"):
                prob = chance if chance > 0 else 50
                wl_num = extract_waitlist_num(raw)
                if prob >= 75:
                    cls_score = 120.0 + prob
                    desc = f"{cls} WL [{raw}, {pred}]{fare_str}"
                elif prob >= 50:
                    cls_score = 50.0 + prob
                    desc = f"{cls} WL [{raw}, {pred}]{fare_str}"
                else:
                    cls_score = 10.0
                    desc = f"{cls} Deep WL [{raw}]{fare_str}"
            elif cinfo.get("is_regret"):
                cls_score = -50.0
                prob = 0
                wl_num = 999999
                desc = f"{cls} REGRET"
            else:
                cls_score = 0.0
                prob = 0
                wl_num = 999999
                desc = f"{cls} {raw}{fare_str}"

            if cls_score > best_score:
                best_score = cls_score
                best_cls = cls
                best_desc = desc
                best_prob = prob
                best_wl = wl_num

        return best_score, best_cls, best_desc, best_prob, best_wl

    @classmethod
    def rank_itineraries(
        cls, itineraries: List[CleanItinerary], preferred_class: str = None
    ) -> List[CleanItinerary]:
        """Scores and ranks itineraries in descending order of optimality."""
        for itin in itineraries:
            score = 0.0
            summaries = []
            viable_classes = []

            if itin.route_type == "DIRECT":
                leg = itin.legs[0]
                leg_score, best_cls, desc, prob, wl = cls.evaluate_leg(leg, preferred_class)
                score += leg_score * 2.0
                itin.min_waitlist = wl

                if leg_score >= 300.0:
                    score += 120.0  # Direct train convenience bonus if confirmed seat exists
                    itin.booking_confidence = "CONFIRMED"
                    itin.confirmation_probability = 100
                elif leg_score >= 220.0:
                    score += 50.0
                    itin.booking_confidence = "RAC"
                    itin.confirmation_probability = prob
                elif leg_score > 0:
                    itin.booking_confidence = "WAITLIST"
                    itin.confirmation_probability = prob
                else:
                    itin.booking_confidence = "REGRET"
                    itin.confirmation_probability = 0

                summaries.append(f"Direct: {desc}")
                viable_classes.append(best_cls)

            elif itin.route_type == "POINT_BEYOND":
                leg = itin.legs[0]
                leg_score, best_cls, desc, prob, wl = cls.evaluate_leg(leg, preferred_class)
                score += leg_score * 1.9 + 110.0  # High bonus for unlocking confirmed quota
                itin.min_waitlist = wl

                if leg_score >= 300.0:
                    itin.booking_confidence = "CONFIRMED"
                    itin.confirmation_probability = 100
                elif leg_score >= 220.0:
                    itin.booking_confidence = "RAC"
                    itin.confirmation_probability = prob
                elif leg_score > 0:
                    itin.booking_confidence = "WAITLIST"
                    itin.confirmation_probability = prob
                else:
                    itin.booking_confidence = "REGRET"
                    itin.confirmation_probability = 0

                summaries.append(f"Point-Beyond ({itin.booking_origin} \u2192 {itin.destination}): {desc}")
                viable_classes.append(best_cls)

            elif itin.route_type == "SAME_TRAIN_SPLIT":
                leg1 = itin.legs[0]
                leg2 = itin.legs[1]
                leg1_score, cls1, desc1, prob1, wl1 = cls.evaluate_leg(leg1, preferred_class)
                leg2_score, cls2, desc2, prob2, wl2 = cls.evaluate_leg(leg2, preferred_class)
                itin.min_waitlist = max(wl1, wl2)

                if leg1_score < 0 or leg2_score < 0:
                    score = -80.0
                    itin.booking_confidence = "REGRET"
                    itin.confirmation_probability = 0
                else:
                    score += (leg1_score + leg2_score) + 130.0  # High bonus: no train change needed
                    if leg1_score >= 300.0 and leg2_score >= 300.0:
                        itin.booking_confidence = "CONFIRMED"
                        itin.confirmation_probability = 100
                    elif leg1_score >= 220.0 and leg2_score >= 220.0:
                        itin.booking_confidence = "RAC"
                        itin.confirmation_probability = min(prob1, prob2)
                    elif leg1_score > 0 and leg2_score > 0:
                        itin.booking_confidence = "WAITLIST"
                        itin.confirmation_probability = min(prob1, prob2)
                    else:
                        itin.booking_confidence = "REGRET"
                        itin.confirmation_probability = 0

                summaries.append(f"Part 1 ({itin.origin}\u2192{itin.split_station}): {desc1}")
                summaries.append(f"Part 2 ({itin.split_station}\u2192{itin.destination}): {desc2}")
                viable_classes.extend([cls1, cls2])

            else:  # 1_TRANSFER
                leg1 = itin.legs[0]
                leg2 = itin.legs[1]

                leg1_score, cls1, desc1, prob1, wl1 = cls.evaluate_leg(leg1, preferred_class)
                leg2_score, cls2, desc2, prob2, wl2 = cls.evaluate_leg(leg2, preferred_class)
                itin.min_waitlist = max(wl1, wl2)

                if leg1_score < 0 or leg2_score < 0:
                    score = -100.0
                    itin.booking_confidence = "REGRET"
                    itin.confirmation_probability = 0
                else:
                    score += (leg1_score + leg2_score)

                    # Bonus if 100% Confirmed on BOTH legs
                    if leg1_score >= 300.0 and leg2_score >= 300.0:
                        score += 150.0
                        itin.booking_confidence = "CONFIRMED"
                        itin.confirmation_probability = 100
                    elif leg1_score >= 220.0 and leg2_score >= 220.0:
                        score += 60.0
                        itin.booking_confidence = "RAC"
                        itin.confirmation_probability = min(prob1, prob2)
                    elif leg1_score > 0 and leg2_score > 0:
                        itin.booking_confidence = "WAITLIST"
                        itin.confirmation_probability = min(prob1, prob2)
                    else:
                        itin.booking_confidence = "REGRET"
                        itin.confirmation_probability = 0

                    # Class continuity bonus
                    if cls1 == cls2:
                        score += 25.0

                # Layover duration scoring
                layover_h = itin.layover_minutes / 60.0
                if 2.0 <= layover_h <= 4.5:
                    score += 35.0  # Perfect transfer buffer
                elif layover_h > 7.0:
                    score -= (layover_h - 7.0) * 12.0  # Long wait deduction

                # Cross-city terminal transfer deduction
                if "Cross-City" in itin.transfer_type:
                    score -= 30.0

                # Detour penalty: Keep detours (like Delhi) lower in ranking
                if itin.detour_ratio > 1.15:
                    penalty = (itin.detour_ratio - 1.15) * 350.0
                    score -= min(penalty, 180.0)

                summaries.append(f"Leg 1 ({itin.origin}\u2192{itin.transit_hub}): {desc1}")
                summaries.append(f"Leg 2 ({itin.transit_hub}\u2192{itin.destination}): {desc2}")
                viable_classes.extend([cls1, cls2])

            # Travel duration penalty (deduct 1.2 points per hour of travel)
            duration_hours = itin.total_duration_minutes / 60.0
            score -= (duration_hours * 1.2)

            itin.score = round(score, 1)
            itin.status_summary = " | ".join(summaries)
            itin.viable_classes = list(set(viable_classes))

        def default_ranking_key(itin: CleanItinerary):
            # Tier 0: CONFIRMED (Direct, Transfers, Same-Train Splits, Point-Beyond)
            # Tier 1: RAC (Guaranteed Boarding)
            # Tier 2: WAITLIST (Strictly sorted from LOWEST to HIGHEST waiting list)
            # Tier 3: REGRET / Closed
            if itin.booking_confidence == "CONFIRMED":
                return (0, -itin.score)
            elif itin.booking_confidence == "RAC":
                return (1, -itin.score)
            elif itin.booking_confidence == "WAITLIST":
                wl = itin.min_waitlist if (itin.min_waitlist is not None and itin.min_waitlist > 0) else 999999
                prob = itin.confirmation_probability if itin.confirmation_probability is not None else 0
                return (2, wl, -prob, -itin.score)
            else:
                return (3, -itin.score)

        ranked = sorted(itineraries, key=default_ranking_key)
        for idx, itin in enumerate(ranked, start=1):
            itin.recommendation_rank = idx

        return ranked
