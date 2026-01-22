"""
Available appointment slots (hardcoded as per requirements).
"""
from datetime import datetime, timedelta
from typing import List, Dict


def get_available_slots(days_ahead: int = 7) -> List[Dict]:
    """
    Get available appointment slots for the next N days.
    Returns hardcoded slots as specified in requirements.
    """
    slots = []
    today = datetime.now().date()

    # Define available time slots
    time_slots = [
        {"time": "09:00", "name": "Morning - 9:00 AM"},
        {"time": "10:00", "name": "Morning - 10:00 AM"},
        {"time": "11:00", "name": "Morning - 11:00 AM"},
        {"time": "14:00", "name": "Afternoon - 2:00 PM"},
        {"time": "15:00", "name": "Afternoon - 3:00 PM"},
        {"time": "16:00", "name": "Afternoon - 4:00 PM"},
    ]

    for day_offset in range(1, days_ahead + 1):
        slot_date = today + timedelta(days=day_offset)

        # Skip weekends
        if slot_date.weekday() >= 5:
            continue

        for time_slot in time_slots:
            slots.append({
                "date": slot_date.isoformat(),
                "date_formatted": slot_date.strftime("%A, %B %d, %Y"),
                "time": time_slot["time"],
                "slot_name": time_slot["name"],
                "available": True  # In real app, check against DB
            })

    return slots


def format_slots_for_speech(slots: List[Dict], limit: int = 6) -> str:
    """Format slots in a natural way for speech output."""
    if not slots:
        return "I don't have any available slots at the moment."

    available = [s for s in slots if s.get("available", True)][:limit]

    if not available:
        return "All slots are currently booked. Please try again later."

    # Group by date
    by_date = {}
    for slot in available:
        date_key = slot["date_formatted"]
        if date_key not in by_date:
            by_date[date_key] = []
        by_date[date_key].append(slot["slot_name"])

    parts = []
    for date_str, times in by_date.items():
        times_str = ", ".join(times[:-1]) + f" and {times[-1]}" if len(times) > 1 else times[0]
        parts.append(f"On {date_str}, I have {times_str}")

    return ". ".join(parts) + "."


def parse_slot_request(date_str: str, time_str: str, available_slots: List[Dict]) -> Dict:
    """
    Parse a user's slot request and find the best matching slot.
    Returns the matching slot or None.
    """
    # Normalize the time string
    time_normalized = time_str.lower().strip()

    # Map common time expressions to 24h format
    time_mappings = {
        "9": "09:00", "9am": "09:00", "9 am": "09:00", "9:00": "09:00", "9:00am": "09:00",
        "10": "10:00", "10am": "10:00", "10 am": "10:00", "10:00": "10:00", "10:00am": "10:00",
        "11": "11:00", "11am": "11:00", "11 am": "11:00", "11:00": "11:00", "11:00am": "11:00",
        "2": "14:00", "2pm": "14:00", "2 pm": "14:00", "14:00": "14:00", "2:00": "14:00",
        "3": "15:00", "3pm": "15:00", "3 pm": "15:00", "15:00": "15:00", "3:00": "15:00",
        "4": "16:00", "4pm": "16:00", "4 pm": "16:00", "16:00": "16:00", "4:00": "16:00",
    }

    target_time = time_mappings.get(time_normalized, time_normalized)

    for slot in available_slots:
        if slot["date"] == date_str and slot["time"] == target_time:
            return slot

    return None
