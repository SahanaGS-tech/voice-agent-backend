"""
Seed script to populate Supabase with mock data for testing.
Run: python -m db.seed_data
"""
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()


def seed_database():
    """Populate database with mock data."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("Error: SUPABASE_URL and SUPABASE_KEY must be set in .env")
        return

    client = create_client(url, key)

    print("Seeding database...")

    # Clear existing data (optional - comment out if you want to keep existing data)
    print("Clearing existing data...")
    client.table("conversations").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    client.table("appointments").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    client.table("users").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    # Create mock users
    print("Creating users...")
    users_data = [
        {"contact_number": "5551234567", "name": "John Smith"},
        {"contact_number": "5559876543", "name": "Sarah Johnson"},
        {"contact_number": "5555551212", "name": "Mike Wilson"},
        {"contact_number": "5550001111", "name": "Emily Davis"},
        {"contact_number": "5552223333", "name": None},  # User without name
    ]

    created_users = []
    for user in users_data:
        result = client.table("users").insert(user).execute()
        created_users.append(result.data[0])
        print(f"  Created user: {user['contact_number']} - {user.get('name', 'No name')}")

    # Create mock appointments
    print("\nCreating appointments...")
    today = datetime.now().date()

    appointments_data = [
        # John Smith - has 2 upcoming appointments
        {
            "user_id": created_users[0]["id"],
            "date": (today + timedelta(days=2)).isoformat(),
            "time": "09:00",
            "slot": "Morning - 9:00 AM",
            "status": "booked"
        },
        {
            "user_id": created_users[0]["id"],
            "date": (today + timedelta(days=5)).isoformat(),
            "time": "14:00",
            "slot": "Afternoon - 2:00 PM",
            "status": "booked"
        },
        # Sarah Johnson - has 1 appointment and 1 cancelled
        {
            "user_id": created_users[1]["id"],
            "date": (today + timedelta(days=3)).isoformat(),
            "time": "10:00",
            "slot": "Morning - 10:00 AM",
            "status": "booked"
        },
        {
            "user_id": created_users[1]["id"],
            "date": (today + timedelta(days=1)).isoformat(),
            "time": "15:00",
            "slot": "Afternoon - 3:00 PM",
            "status": "cancelled"
        },
        # Mike Wilson - has 1 appointment
        {
            "user_id": created_users[2]["id"],
            "date": (today + timedelta(days=4)).isoformat(),
            "time": "11:00",
            "slot": "Morning - 11:00 AM",
            "status": "booked"
        },
        # Some slots that are booked (to test double-booking prevention)
        {
            "user_id": created_users[3]["id"],
            "date": (today + timedelta(days=2)).isoformat(),
            "time": "10:00",
            "slot": "Morning - 10:00 AM",
            "status": "booked"
        },
    ]

    for apt in appointments_data:
        result = client.table("appointments").insert(apt).execute()
        print(f"  Created appointment: {apt['date']} at {apt['slot']} - {apt['status']}")

    # Create a sample past conversation
    print("\nCreating sample conversation...")
    conversation_data = {
        "user_id": created_users[0]["id"],
        "summary": "User John Smith called to book an appointment. Successfully booked for Morning - 9:00 AM. User mentioned preference for morning slots.",
        "appointments_discussed": [
            {
                "action": "booked",
                "date": (today + timedelta(days=2)).isoformat(),
                "time": "09:00",
                "slot": "Morning - 9:00 AM"
            }
        ],
        "preferences_mentioned": ["morning appointments", "weekday preferred"],
        "transcript": [
            {"role": "assistant", "content": "Hello! I'm Alex, your appointment booking assistant. How can I help you today?"},
            {"role": "user", "content": "Hi, I'd like to book an appointment"},
            {"role": "assistant", "content": "I'd be happy to help you book an appointment. May I have your phone number please?"},
            {"role": "user", "content": "Sure, it's 555-123-4567"},
            {"role": "assistant", "content": "Thank you John! I see you're a returning customer. When would you like to schedule your appointment?"},
            {"role": "user", "content": "Do you have anything in the morning?"},
            {"role": "assistant", "content": "Yes! I have Morning - 9:00 AM and Morning - 10:00 AM available. Which works better for you?"},
            {"role": "user", "content": "9 AM works great"},
            {"role": "assistant", "content": "I've booked your appointment for Morning - 9:00 AM. Is there anything else I can help you with?"},
            {"role": "user", "content": "No, that's all. Thank you!"},
            {"role": "assistant", "content": "You're welcome! Have a great day. Goodbye!"}
        ],
        "cost_breakdown": {
            "deepgram_stt": 0.0021,
            "cartesia_tts": 0.0015,
            "openai_llm": 0.0012,
            "total": 0.0048
        }
    }

    client.table("conversations").insert(conversation_data).execute()
    print("  Created sample conversation")

    # Print summary
    print("\n" + "="*50)
    print("SEED DATA SUMMARY")
    print("="*50)
    print("\nTest Users (use these phone numbers):")
    print("-" * 40)
    for user in created_users:
        name = user.get('name') or 'No name set'
        print(f"  Phone: {user['contact_number']} | Name: {name}")

    print("\nTest Scenarios:")
    print("-" * 40)
    print("  1. Call with 5551234567 (John Smith)")
    print("     - Has 2 existing appointments")
    print("     - Test: retrieve_appointments, modify, cancel")
    print()
    print("  2. Call with 5559876543 (Sarah Johnson)")
    print("     - Has 1 active + 1 cancelled appointment")
    print("     - Test: retrieve with include_cancelled=True")
    print()
    print("  3. Call with 5555551212 (Mike Wilson)")
    print("     - Has 1 appointment")
    print("     - Test: basic flow")
    print()
    print("  4. Call with 5552223333 (Unknown name)")
    print("     - User exists but no name")
    print("     - Test: name collection flow")
    print()
    print("  5. Call with a new number (e.g., 5559999999)")
    print("     - New user creation flow")
    print("     - Test: full booking journey")
    print()
    print("Blocked Slots (already booked):")
    print("-" * 40)
    print(f"  - {(today + timedelta(days=2)).isoformat()} at 09:00 (John)")
    print(f"  - {(today + timedelta(days=2)).isoformat()} at 10:00 (Emily)")
    print(f"  - {(today + timedelta(days=3)).isoformat()} at 10:00 (Sarah)")
    print(f"  - {(today + timedelta(days=4)).isoformat()} at 11:00 (Mike)")
    print(f"  - {(today + timedelta(days=5)).isoformat()} at 14:00 (John)")

    print("\n" + "="*50)
    print("Database seeded successfully!")
    print("="*50)


if __name__ == "__main__":
    seed_database()
