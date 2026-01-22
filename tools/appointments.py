"""
Appointment management tool functions for the voice agent.
These functions are called by the LLM via function calling.
"""
import logging
from datetime import datetime
from typing import Optional, Callable, Any, Annotated
from livekit.agents import llm
from db.supabase import Database
from tools.slots import get_available_slots, format_slots_for_speech

logger = logging.getLogger("appointment-tools")


class AppointmentContext:
    """Shared context for appointment tools."""

    def __init__(self, db: Database, on_tool_call: Optional[Callable[[str, dict, Any], None]] = None):
        self.db = db
        self.current_user_id: Optional[str] = None
        self.current_user_phone: Optional[str] = None
        self.current_user_name: Optional[str] = None
        self.conversation_transcript: list = []
        self.appointments_discussed: list = []
        self.preferences_mentioned: list = []
        self.on_tool_call = on_tool_call

    def notify_tool_call(self, tool_name: str, params: dict, result: Any):
        """Notify frontend about tool call."""
        if self.on_tool_call:
            self.on_tool_call(tool_name, params, result)


def create_appointment_tools(ctx: AppointmentContext) -> list:
    """Create appointment tools with shared context."""

    @llm.function_tool(
        name="identify_user",
        description="Identify the user by asking for their phone number. Call this when you need to know who the user is before booking or retrieving appointments."
    )
    async def identify_user(
        phone_number: Annotated[str, "The user's phone number (10 digits)"],
        name: Annotated[str | None, "The user's name if provided"] = None
    ) -> str:
        """Identify or create a user by phone number."""
        logger.info(f"identify_user called: phone={phone_number}, name={name}")

        # Clean phone number
        phone_clean = "".join(filter(str.isdigit, phone_number))

        if len(phone_clean) < 10:
            result = "The phone number seems invalid. Please ask for a valid 10-digit phone number."
            ctx.notify_tool_call("identify_user", {"phone": phone_number}, {"error": result})
            return result

        try:
            user = ctx.db.get_or_create_user(phone_clean, name)
            ctx.current_user_id = user["id"]
            ctx.current_user_phone = phone_clean
            ctx.current_user_name = user.get("name") or name

            if name and not user.get("name"):
                ctx.db.update_user_name(user["id"], name)
                ctx.current_user_name = name

            result_data = {
                "user_id": ctx.current_user_id,
                "phone": ctx.current_user_phone,
                "name": ctx.current_user_name,
                "is_new": user.get("name") is None
            }

            greeting = f"Welcome back, {ctx.current_user_name}!" if ctx.current_user_name else "I've identified you by your phone number."
            ctx.notify_tool_call("identify_user", {"phone": phone_clean, "name": name}, result_data)

            return f"User identified successfully. {greeting} User ID: {ctx.current_user_id}"

        except Exception as e:
            logger.error(f"Error identifying user: {e}")
            result = f"Error identifying user: {str(e)}"
            ctx.notify_tool_call("identify_user", {"phone": phone_number}, {"error": str(e)})
            return result

    @llm.function_tool(
        name="fetch_slots",
        description="Fetch available appointment slots. Call this when the user wants to know what times are available for booking."
    )
    async def fetch_slots(
        days_ahead: Annotated[int, "Number of days to look ahead (default 7)"] = 7
    ) -> str:
        """Get available appointment slots."""
        logger.info(f"fetch_slots called: days_ahead={days_ahead}")

        slots = get_available_slots(days_ahead)

        # Filter out already booked slots from DB
        available_slots = []
        for slot in slots:
            if ctx.db.check_slot_available(slot["date"], slot["time"]):
                available_slots.append(slot)

        result_data = {"slots": available_slots[:12], "total": len(available_slots)}
        ctx.notify_tool_call("fetch_slots", {"days_ahead": days_ahead}, result_data)

        speech_output = format_slots_for_speech(available_slots)
        return speech_output

    @llm.function_tool(
        name="book_appointment",
        description="Book an appointment for the user. Requires user to be identified first. Call this when the user wants to book a specific slot."
    )
    async def book_appointment(
        date: Annotated[str, "Appointment date in YYYY-MM-DD format"],
        time: Annotated[str, "Appointment time in HH:MM format (24-hour)"],
        slot_name: Annotated[str, "Human-readable slot name like 'Morning - 9:00 AM'"]
    ) -> str:
        """Book an appointment for the identified user."""
        logger.info(f"book_appointment called: date={date}, time={time}, slot={slot_name}")

        if not ctx.current_user_id:
            result = "I need to identify you first. Please provide your phone number."
            ctx.notify_tool_call("book_appointment", {"date": date, "time": time}, {"error": "User not identified"})
            return result

        try:
            appointment = ctx.db.book_appointment(
                user_id=ctx.current_user_id,
                slot_date=date,
                slot_time=time,
                slot_name=slot_name
            )

            ctx.appointments_discussed.append({
                "id": appointment["id"],
                "action": "booked",
                "date": date,
                "time": time,
                "slot": slot_name
            })

            result_data = {
                "appointment_id": appointment["id"],
                "date": date,
                "time": time,
                "slot": slot_name,
                "status": "booked"
            }
            ctx.notify_tool_call("book_appointment", {"date": date, "time": time, "slot": slot_name}, result_data)

            # Format date nicely for speech
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                date_formatted = date_obj.strftime("%A, %B %d")
            except:
                date_formatted = date

            return f"Appointment booked successfully for {date_formatted} at {slot_name}. Your confirmation ID is {appointment['id'][:8]}."

        except ValueError as e:
            result = str(e)
            ctx.notify_tool_call("book_appointment", {"date": date, "time": time}, {"error": result})
            return f"Could not book appointment: {result}. Please choose a different time slot."

        except Exception as e:
            logger.error(f"Error booking appointment: {e}")
            result = f"Error booking appointment: {str(e)}"
            ctx.notify_tool_call("book_appointment", {"date": date, "time": time}, {"error": str(e)})
            return result

    @llm.function_tool(
        name="retrieve_appointments",
        description="Retrieve the user's existing appointments. Call this when the user wants to see their scheduled appointments."
    )
    async def retrieve_appointments(
        include_cancelled: Annotated[bool, "Whether to include cancelled appointments"] = False
    ) -> str:
        """Get user's appointments."""
        logger.info(f"retrieve_appointments called: include_cancelled={include_cancelled}")

        if not ctx.current_user_id:
            result = "I need to identify you first. Please provide your phone number."
            ctx.notify_tool_call("retrieve_appointments", {}, {"error": "User not identified"})
            return result

        try:
            appointments = ctx.db.get_appointments_by_user(ctx.current_user_id, include_cancelled)

            result_data = {"appointments": appointments, "count": len(appointments)}
            ctx.notify_tool_call("retrieve_appointments", {"include_cancelled": include_cancelled}, result_data)

            if not appointments:
                return "You don't have any upcoming appointments scheduled."

            # Format for speech - include IDs so LLM can use them for cancel/modify
            parts = []
            for apt in appointments:
                try:
                    date_obj = datetime.strptime(apt["date"], "%Y-%m-%d")
                    date_formatted = date_obj.strftime("%A, %B %d")
                except:
                    date_formatted = apt["date"]

                status_text = f" (cancelled)" if apt["status"] == "cancelled" else ""
                # Include the 8-char appointment ID so LLM can reference it for cancel/modify
                apt_id_short = apt["id"][:8]
                parts.append(f"{apt['slot']} on {date_formatted}{status_text}, ID: {apt_id_short}")

            if len(parts) == 1:
                return f"You have one appointment: {parts[0]}."
            else:
                return f"You have {len(parts)} appointments: " + ", ".join(parts[:-1]) + f", and {parts[-1]}."

        except Exception as e:
            logger.error(f"Error retrieving appointments: {e}")
            result = f"Error retrieving appointments: {str(e)}"
            ctx.notify_tool_call("retrieve_appointments", {}, {"error": str(e)})
            return result

    @llm.function_tool(
        name="cancel_appointment",
        description="Cancel an existing appointment. Call this when the user wants to cancel a scheduled appointment."
    )
    async def cancel_appointment(
        appointment_id: Annotated[str, "The appointment ID to cancel"]
    ) -> str:
        """Cancel an appointment."""
        logger.info(f"cancel_appointment called: appointment_id={appointment_id}")

        if not ctx.current_user_id:
            result = "I need to identify you first. Please provide your phone number."
            ctx.notify_tool_call("cancel_appointment", {"appointment_id": appointment_id}, {"error": "User not identified"})
            return result

        try:
            # Verify appointment belongs to user - pass user_id for efficient partial ID matching
            appointment = ctx.db.get_appointment_by_id(appointment_id, user_id=ctx.current_user_id)
            if not appointment:
                result = "I couldn't find that appointment. Please check the ID and try again."
                ctx.notify_tool_call("cancel_appointment", {"appointment_id": appointment_id}, {"error": "Not found"})
                return result

            if appointment["user_id"] != ctx.current_user_id:
                result = "That appointment doesn't belong to your account."
                ctx.notify_tool_call("cancel_appointment", {"appointment_id": appointment_id}, {"error": "Unauthorized"})
                return result

            if appointment["status"] == "cancelled":
                result = "That appointment is already cancelled."
                ctx.notify_tool_call("cancel_appointment", {"appointment_id": appointment_id}, {"error": "Already cancelled"})
                return result

            # Use the full UUID from the retrieved appointment, not the partial ID
            full_appointment_id = appointment["id"]
            cancelled = ctx.db.cancel_appointment(full_appointment_id)

            ctx.appointments_discussed.append({
                "id": full_appointment_id,
                "action": "cancelled",
                "date": appointment["date"],
                "time": appointment["time"]
            })

            result_data = {"appointment_id": full_appointment_id, "status": "cancelled"}
            ctx.notify_tool_call("cancel_appointment", {"appointment_id": full_appointment_id}, result_data)

            return f"Your appointment on {appointment['date']} at {appointment['slot']} has been cancelled."

        except Exception as e:
            logger.error(f"Error cancelling appointment: {e}")
            result = f"Error cancelling appointment: {str(e)}"
            ctx.notify_tool_call("cancel_appointment", {"appointment_id": appointment_id}, {"error": str(e)})
            return result

    @llm.function_tool(
        name="modify_appointment",
        description="Modify an existing appointment's date or time. Call this when the user wants to reschedule."
    )
    async def modify_appointment(
        appointment_id: Annotated[str, "The appointment ID to modify"],
        new_date: Annotated[str, "New date in YYYY-MM-DD format"],
        new_time: Annotated[str, "New time in HH:MM format (24-hour)"],
        new_slot_name: Annotated[str, "New human-readable slot name"]
    ) -> str:
        """Modify an appointment's date/time."""
        logger.info(f"modify_appointment called: id={appointment_id}, new_date={new_date}, new_time={new_time}")

        if not ctx.current_user_id:
            result = "I need to identify you first. Please provide your phone number."
            ctx.notify_tool_call("modify_appointment", {"appointment_id": appointment_id}, {"error": "User not identified"})
            return result

        try:
            # Verify appointment belongs to user - pass user_id for efficient partial ID matching
            appointment = ctx.db.get_appointment_by_id(appointment_id, user_id=ctx.current_user_id)
            if not appointment:
                result = "I couldn't find that appointment."
                ctx.notify_tool_call("modify_appointment", {"appointment_id": appointment_id}, {"error": "Not found"})
                return result

            if appointment["user_id"] != ctx.current_user_id:
                result = "That appointment doesn't belong to your account."
                ctx.notify_tool_call("modify_appointment", {"appointment_id": appointment_id}, {"error": "Unauthorized"})
                return result

            if appointment["status"] == "cancelled":
                result = "Cannot modify a cancelled appointment. Please book a new one."
                ctx.notify_tool_call("modify_appointment", {"appointment_id": appointment_id}, {"error": "Cancelled"})
                return result

            # Use the full UUID from the retrieved appointment, not the partial ID
            full_appointment_id = appointment["id"]
            modified = ctx.db.modify_appointment(full_appointment_id, new_date, new_time, new_slot_name)

            ctx.appointments_discussed.append({
                "id": full_appointment_id,
                "action": "modified",
                "old_date": appointment["date"],
                "old_time": appointment["time"],
                "new_date": new_date,
                "new_time": new_time
            })

            result_data = {
                "appointment_id": full_appointment_id,
                "new_date": new_date,
                "new_time": new_time,
                "new_slot": new_slot_name,
                "status": "modified"
            }
            ctx.notify_tool_call("modify_appointment", {"appointment_id": full_appointment_id, "new_date": new_date, "new_time": new_time}, result_data)

            # Format dates nicely
            try:
                new_date_obj = datetime.strptime(new_date, "%Y-%m-%d")
                new_date_formatted = new_date_obj.strftime("%A, %B %d")
            except:
                new_date_formatted = new_date

            return f"Your appointment has been rescheduled to {new_date_formatted} at {new_slot_name}."

        except ValueError as e:
            result = str(e)
            ctx.notify_tool_call("modify_appointment", {"appointment_id": appointment_id}, {"error": result})
            return f"Could not modify appointment: {result}. The new slot may be unavailable."

        except Exception as e:
            logger.error(f"Error modifying appointment: {e}")
            result = f"Error modifying appointment: {str(e)}"
            ctx.notify_tool_call("modify_appointment", {"appointment_id": appointment_id}, {"error": str(e)})
            return result

    @llm.function_tool(
        name="end_conversation",
        description="End the conversation. Call this when the user says goodbye, wants to end the call, or the conversation is complete. This will generate a summary."
    )
    async def end_conversation(
        reason: Annotated[str, "Reason for ending (e.g., 'user requested', 'task complete')"] = "user requested"
    ) -> str:
        """End the conversation and generate summary."""
        logger.info(f"end_conversation called: reason={reason}")

        # Generate summary data
        summary_data = {
            "user_id": ctx.current_user_id,
            "user_phone": ctx.current_user_phone,
            "user_name": ctx.current_user_name,
            "appointments_discussed": ctx.appointments_discussed,
            "preferences_mentioned": ctx.preferences_mentioned,
            "reason": reason,
            "should_end": True
        }

        ctx.notify_tool_call("end_conversation", {"reason": reason}, summary_data)

        return f"END_CONVERSATION: Conversation ended. Reason: {reason}. Please say goodbye to the user."

    return [
        identify_user,
        fetch_slots,
        book_appointment,
        retrieve_appointments,
        cancel_appointment,
        modify_appointment,
        end_conversation
    ]
