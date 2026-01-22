"""
Supabase database client for appointment management.
"""
import os
from datetime import datetime, date, time
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


def get_supabase_client() -> Client:
    """Get Supabase client instance."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


class Database:
    """Database operations for the voice agent."""

    def __init__(self):
        self.client = get_supabase_client()

    # User operations
    def get_user_by_phone(self, phone: str) -> Optional[dict]:
        """Get user by phone number."""
        result = self.client.table("users").select("*").eq("contact_number", phone).execute()
        return result.data[0] if result.data else None

    def create_user(self, phone: str, name: Optional[str] = None) -> dict:
        """Create a new user."""
        data = {"contact_number": phone}
        if name:
            data["name"] = name
        result = self.client.table("users").insert(data).execute()
        return result.data[0]

    def get_or_create_user(self, phone: str, name: Optional[str] = None) -> dict:
        """Get existing user or create new one."""
        user = self.get_user_by_phone(phone)
        if user:
            return user
        return self.create_user(phone, name)

    def update_user_name(self, user_id: str, name: str) -> dict:
        """Update user's name."""
        result = self.client.table("users").update({"name": name}).eq("id", user_id).execute()
        return result.data[0] if result.data else None

    # Appointment operations
    def get_appointments_by_user(self, user_id: str, include_cancelled: bool = False) -> list:
        """Get all appointments for a user."""
        query = self.client.table("appointments").select("*").eq("user_id", user_id)
        if not include_cancelled:
            query = query.neq("status", "cancelled")
        result = query.order("date", desc=False).order("time", desc=False).execute()
        return result.data

    def get_appointment_by_id(self, appointment_id: str, user_id: str = None) -> Optional[dict]:
        """Get appointment by ID (supports partial ID matching for 8-char confirmation codes)."""
        # Clean the input - remove any whitespace
        appointment_id = appointment_id.strip().lower()

        # UUID format is 36 characters (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
        # Only try exact match if it looks like a full UUID to avoid PostgreSQL cast errors
        if len(appointment_id) == 36 and '-' in appointment_id:
            result = self.client.table("appointments").select("*").eq("id", appointment_id).execute()
            if result.data:
                return result.data[0]

        # For partial IDs (like 8-char confirmation codes), fetch and filter in Python
        # This avoids PostgreSQL UUID casting issues
        if user_id:
            # If we know the user, only fetch their appointments (more efficient)
            result = self.client.table("appointments").select("*").eq("user_id", user_id).execute()
        else:
            # Otherwise fetch recent appointments (limit to avoid performance issues)
            result = self.client.table("appointments").select("*").order("created_at", desc=True).limit(100).execute()

        # Find appointment where ID starts with the partial ID
        for apt in result.data:
            if apt["id"].lower().startswith(appointment_id):
                return apt

        return None

    def check_slot_available(self, slot_date: str, slot_time: str) -> bool:
        """Check if a time slot is available (not already booked)."""
        result = self.client.table("appointments").select("id").eq("date", slot_date).eq("time", slot_time).eq("status", "booked").execute()
        return len(result.data) == 0

    def book_appointment(self, user_id: str, slot_date: str, slot_time: str, slot_name: str) -> dict:
        """Book a new appointment."""
        # Check for double booking
        if not self.check_slot_available(slot_date, slot_time):
            raise ValueError(f"Slot {slot_date} at {slot_time} is already booked")

        data = {
            "user_id": user_id,
            "date": slot_date,
            "time": slot_time,
            "slot": slot_name,
            "status": "booked"
        }
        result = self.client.table("appointments").insert(data).execute()
        return result.data[0]

    def cancel_appointment(self, appointment_id: str) -> dict:
        """Cancel an appointment."""
        result = self.client.table("appointments").update({
            "status": "cancelled",
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", appointment_id).execute()
        return result.data[0] if result.data else None

    def modify_appointment(self, appointment_id: str, new_date: str, new_time: str, new_slot: str) -> dict:
        """Modify an appointment's date/time."""
        # Check if new slot is available
        if not self.check_slot_available(new_date, new_time):
            raise ValueError(f"Slot {new_date} at {new_time} is already booked")

        result = self.client.table("appointments").update({
            "date": new_date,
            "time": new_time,
            "slot": new_slot,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", appointment_id).execute()
        return result.data[0] if result.data else None

    # Conversation operations
    def save_conversation(
        self,
        user_id: Optional[str],
        summary: str,
        appointments_discussed: list,
        preferences_mentioned: list,
        transcript: list,
        cost_breakdown: Optional[dict] = None,
        room_name: Optional[str] = None,
        duration_seconds: Optional[int] = None
    ) -> dict:
        """Save conversation summary."""
        data = {
            "user_id": user_id,
            "summary": summary,
            "appointments_discussed": appointments_discussed,
            "preferences_mentioned": preferences_mentioned,
            "transcript": transcript,
            "cost_breakdown": cost_breakdown,
            "room_name": room_name,
            "duration_seconds": duration_seconds
        }
        result = self.client.table("conversations").insert(data).execute()
        return result.data[0]

    def get_conversation_by_room(self, room_name: str) -> Optional[dict]:
        """Get conversation by room name."""
        result = self.client.table("conversations").select("*").eq("room_name", room_name).order("created_at", desc=True).limit(1).execute()
        return result.data[0] if result.data else None


# SQL schema for reference (run in Supabase SQL editor):
SCHEMA_SQL = """
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_number VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Appointments table
CREATE TABLE IF NOT EXISTS appointments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    time TIME NOT NULL,
    slot VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled', 'completed')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Conversations table (matches Supabase table definition)
CREATE TABLE IF NOT EXISTS public.conversations (
    id UUID NOT NULL DEFAULT extensions.uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    summary TEXT NULL,
    appointments_discussed JSONB NULL DEFAULT '[]'::jsonb,
    preferences_mentioned JSONB NULL DEFAULT '[]'::jsonb,
    transcript JSONB NULL DEFAULT '[]'::jsonb,
    cost_breakdown JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NULL DEFAULT NOW(),
    room_name VARCHAR(255) NULL,
    duration_seconds INTEGER NULL,
    CONSTRAINT conversations_pkey PRIMARY KEY (id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_contact ON users(contact_number);
CREATE INDEX IF NOT EXISTS idx_appointments_user ON appointments(user_id);
CREATE INDEX IF NOT EXISTS idx_appointments_date_time ON appointments(date, time);
CREATE INDEX IF NOT EXISTS idx_conversations_room ON public.conversations USING btree (room_name);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON public.conversations(user_id);
"""
