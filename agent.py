"""
LiveKit Voice Agent for Appointment Booking.
Main entry point for the voice agent backend.
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice import AgentSession, Agent
from livekit.agents.metrics import UsageCollector
from livekit.plugins import deepgram, cartesia, openai, silero, bey

from db.supabase import Database
from tools.appointments import AppointmentContext, create_appointment_tools
from prompts.system import get_system_prompt, get_summary_prompt

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-agent")


class ConversationManager:
    """Manages conversation state and summary generation."""

    def __init__(self, db: Database, room: rtc.Room, room_name: str):
        self.db = db
        self.room = room
        self.room_name = room_name
        self.transcript: list = []
        self.start_time = datetime.utcnow()
        self.usage_collector = UsageCollector()  # Automatic metrics aggregation
        self.summary_generated = False  # Prevent duplicate summaries

    def add_message(self, role: str, content: str):
        """Add a message to the transcript."""
        self.transcript.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })

    async def send_tool_call_event(self, tool_name: str, params: dict, result: dict):
        """Send tool call event to frontend via data channel."""
        event = {
            "type": "tool_call",
            "data": {
                "id": str(uuid.uuid4()),
                "tool": tool_name,
                "params": params,
                "result": result,
                "timestamp": int(datetime.utcnow().timestamp() * 1000)  # JS timestamp in ms
            }
        }
        await self._send_data_event(event)

    async def send_summary_event(self, summary: dict):
        """Send conversation summary to frontend."""
        event = {
            "type": "summary",
            "data": summary,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._send_data_event(event)

    async def send_end_event(self):
        """Signal to frontend that conversation is ending."""
        event = {
            "type": "conversation_end",
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._send_data_event(event)

    async def send_agent_ready_event(self, has_avatar: bool = False):
        """Signal to frontend that agent is fully initialized and ready."""
        event = {
            "type": "agent_ready",
            "data": {
                "has_avatar": has_avatar
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._send_data_event(event)

    async def _send_data_event(self, event: dict):
        """Send data to all participants via data channel."""
        try:
            data = json.dumps(event).encode("utf-8")
            await self.room.local_participant.publish_data(
                data,
                reliable=True,
                topic="agent_events"
            )
            logger.info(f"Sent event: {event['type']}")
        except Exception as e:
            logger.error(f"Error sending data event: {e}")

    def estimate_cost(self) -> dict:
        """Calculate cost from actual collected metrics."""
        summary = self.usage_collector.get_summary()

        # Deepgram Nova-2: $0.0058/min
        stt_cost = summary.stt_audio_duration * 0.0058 / 60

        # Cartesia Sonic-2: ~$0.0000099/char (based on $99/10M credits prepaid)
        tts_cost = summary.tts_characters_count * 0.0000099

        # OpenAI GPT-4o-mini: $0.15/1M input, $0.60/1M output
        llm_input_cost = summary.llm_prompt_tokens * 0.00015 / 1000
        llm_output_cost = summary.llm_completion_tokens * 0.0006 / 1000
        llm_cost = llm_input_cost + llm_output_cost

        total_cost = stt_cost + tts_cost + llm_cost

        return {
            "stt_cost": round(stt_cost, 6),
            "tts_cost": round(tts_cost, 6),
            "llm_cost": round(llm_cost, 6),
            "total_cost": round(total_cost, 6),
            # Include raw usage for transparency
            "usage": {
                "stt_seconds": round(summary.stt_audio_duration, 2),
                "tts_characters": summary.tts_characters_count,
                "llm_input_tokens": summary.llm_prompt_tokens,
                "llm_output_tokens": summary.llm_completion_tokens,
            }
        }

    def setup_metrics_handler(self, session: AgentSession):
        """Register callback to collect metrics from AgentSession."""
        @session.on("metrics_collected")
        def on_metrics(event):
            self.usage_collector.collect(event.metrics)
            logger.debug(f"Collected metrics: {type(event.metrics).__name__}")

    def setup_data_handler(self, appointment_ctx, session):
        """Set up handler for receiving data events from frontend."""
        self.appointment_ctx = appointment_ctx
        self.session = session

        @self.room.on("data_received")
        def on_data_received(packet: rtc.DataPacket):
            """Handle data received from frontend."""
            try:
                logger.info(f"Data received from frontend, topic: {packet.topic}")

                # Filter for agent_events topic
                if packet.topic and packet.topic != "agent_events":
                    return

                message = json.loads(packet.data.decode("utf-8"))
                logger.info(f"Parsed message: {message}")

                if message.get("type") == "request_summary":
                    logger.info("Processing summary request from frontend")
                    asyncio.create_task(self._handle_summary_request())
            except Exception as e:
                logger.error(f"Error handling data event: {e}", exc_info=True)

    async def _handle_summary_request(self):
        """Handle summary request from frontend."""
        logger.info("_handle_summary_request called")
        if self.summary_generated:
            logger.info("Summary already generated, skipping")
            return

        self.summary_generated = True
        logger.info("Generating summary...")
        try:
            await handle_conversation_end(
                self, self.appointment_ctx, self.db, self.session
            )
            logger.info("Summary generation completed")
        except Exception as e:
            logger.error(f"Error in _handle_summary_request: {e}", exc_info=True)


async def entrypoint(ctx: JobContext):
    """Main entry point for the voice agent."""
    logger.info(f"Connecting to room: {ctx.room.name}")

    # Initialize database
    db = Database()

    # Initialize conversation manager with room name for later lookup
    conv_manager = ConversationManager(db, ctx.room, ctx.room.name)

    # Tool call callback
    def on_tool_call(tool_name: str, params: dict, result: dict):
        asyncio.create_task(conv_manager.send_tool_call_event(tool_name, params, result))

    # Initialize appointment context and tools
    appointment_ctx = AppointmentContext(db, on_tool_call=on_tool_call)
    tools = create_appointment_tools(appointment_ctx)

    # Connect to room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for a participant to join
    participant = await ctx.wait_for_participant()
    logger.info(f"Participant joined: {participant.identity}")

    # Create the agent session with all components
    session = AgentSession(
        vad=silero.VAD.load(
            min_silence_duration=0.5,
            min_speech_duration=0.1,
        ),
        stt=deepgram.STT(
            model="nova-2",
            language="en-US",
            smart_format=True,
            punctuate=True,
        ),
        llm=openai.LLM(
            model="gpt-4o-mini",
            temperature=0.7,
        ),
        tts=cartesia.TTS(
            model="sonic-2",
            voice="829ccd10-f8b3-43cd-b8a0-4aeaa81f3b30",
            speed=0.4,
        ),
        tools=tools,
        allow_interruptions=True,
        min_endpointing_delay=0.5,
        max_endpointing_delay=3.0,
    )

    # Create agent with instructions
    agent = Agent(instructions=get_system_prompt())

    # Track conversation events
    @session.on("user_input_transcribed")
    def on_user_speech(event):
        if hasattr(event, 'transcript') and event.transcript:
            conv_manager.add_message("user", event.transcript)
            logger.info(f"User: {event.transcript}")

    @session.on("agent_speech_committed")
    def on_agent_speech(event):
        if hasattr(event, 'content') and event.content:
            conv_manager.add_message("assistant", event.content)
            logger.info(f"Agent: {event.content}")

            # Check if conversation should end
            if "END_CONVERSATION" in str(event.content) and not conv_manager.summary_generated:
                conv_manager.summary_generated = True
                asyncio.create_task(handle_conversation_end(
                    conv_manager, appointment_ctx, db, session
                ))

    # Set up handler for frontend data events (e.g., summary request)
    conv_manager.setup_data_handler(appointment_ctx, session)

    # Set up metrics collection for cost tracking
    conv_manager.setup_metrics_handler(session)

    # Use shutdown callback to generate summary when job ends (participant disconnects)
    # This is AWAITED by the framework, ensuring summary completes before job terminates
    async def on_shutdown():
        logger.info("=== SHUTDOWN CALLBACK TRIGGERED ===")
        if not conv_manager.summary_generated:
            conv_manager.summary_generated = True
            logger.info("Generating summary on shutdown...")
            try:
                await handle_conversation_end(
                    conv_manager, appointment_ctx, db, session
                )
                logger.info("=== SUMMARY SAVED SUCCESSFULLY ===")
            except Exception as e:
                logger.error(f"=== SUMMARY GENERATION FAILED: {e} ===", exc_info=True)
        else:
            logger.info("Summary already generated, skipping in shutdown")

    ctx.add_shutdown_callback(on_shutdown)

    # Start the session
    await session.start(
        room=ctx.room,
        agent=agent,
    )

    # Initialize Beyond Presence Avatar (if configured)
    has_avatar = False
    bey_avatar_id = os.getenv("BEY_AVATAR_ID")
    if bey_avatar_id:
        try:
            logger.info(f"Starting Beyond Presence avatar: {bey_avatar_id}")
            avatar_session = bey.AvatarSession(avatar_id=bey_avatar_id)
            await avatar_session.start(session, room=ctx.room)
            has_avatar = True
            logger.info("Beyond Presence avatar started successfully")
        except Exception as e:
            logger.warning(f"Failed to start Beyond Presence avatar: {e}")
            logger.info("Continuing without avatar...")
    else:
        logger.info("No BEY_AVATAR_ID configured, running without avatar")

    # Signal to frontend that agent is ready (avatar loaded or fallback ready)
    await conv_manager.send_agent_ready_event(has_avatar=has_avatar)

    # Small delay to ensure frontend has subscribed to audio track
    await asyncio.sleep(0.5)

    # Initial greeting - now frontend knows to show the avatar/bot icon
    await session.say(
        "Hello! I'm Alex, your appointment booking assistant. How can I help you today?",
        allow_interruptions=True
    )

    logger.info("Voice assistant started")


async def handle_conversation_end(
    conv_manager: ConversationManager,
    appointment_ctx: AppointmentContext,
    db: Database,
    session: AgentSession
):
    """Handle end of conversation - generate and send summary."""
    logger.info("=== STARTING CONVERSATION END HANDLER ===")
    logger.info(f"Room name: {conv_manager.room_name}")
    logger.info(f"Transcript length: {len(conv_manager.transcript)}")

    try:
        # Generate summary using LLM
        logger.info("Generating summary prompt...")
        summary_prompt = get_summary_prompt(
            conv_manager.transcript,
            appointment_ctx.appointments_discussed,
            appointment_ctx.preferences_mentioned
        )

        # Use OpenAI to generate summary
        logger.info("Calling OpenAI for summary generation...")
        client = openai.LLM(model="gpt-4o-mini")
        chat_ctx = llm.ChatContext()
        chat_ctx.add_message(role="user", content=summary_prompt)
        summary_response = client.chat(chat_ctx=chat_ctx)

        summary_text = ""
        async for chunk in summary_response:
            if chunk.delta and chunk.delta.content:
                summary_text += chunk.delta.content

        logger.info(f"Summary generated: {summary_text[:100]}...")

        # Transform appointments to match frontend AppointmentSummary interface
        appointments = []
        for apt in appointment_ctx.appointments_discussed:
            apt_summary = {
                "id": apt.get("id", ""),
                "action": apt.get("action", "booked"),
                "date": apt.get("date", apt.get("new_date", "")),
                "time": apt.get("time", apt.get("new_time", "")),
            }
            # Add rescheduled_time for modified appointments
            if apt.get("action") == "modified" and apt.get("new_time"):
                apt_summary["rescheduled_time"] = f"{apt.get('new_date', '')} at {apt.get('new_time', '')}"
            appointments.append(apt_summary)

        # Prepare summary data matching frontend ConversationSummaryData interface
        summary_data = {
            "summary": summary_text,
            "appointments": appointments,
            "preferences": appointment_ctx.preferences_mentioned,
            "user_phone": appointment_ctx.current_user_phone,
            "user_name": appointment_ctx.current_user_name,
            "duration_seconds": int((datetime.utcnow() - conv_manager.start_time).total_seconds()),
            "costs": conv_manager.estimate_cost()
        }

        # Save to database
        logger.info(f"Saving to database with room_name: {conv_manager.room_name}")
        saved = db.save_conversation(
            user_id=appointment_ctx.current_user_id,
            summary=summary_text,
            appointments_discussed=appointment_ctx.appointments_discussed,
            preferences_mentioned=appointment_ctx.preferences_mentioned,
            transcript=conv_manager.transcript,
            cost_breakdown=summary_data["costs"],
            room_name=conv_manager.room_name,
            duration_seconds=summary_data["duration_seconds"]
        )
        logger.info(f"=== DATABASE SAVE RESULT: {saved.get('id') if saved else 'FAILED'} ===")

        # Try to send to frontend (may fail if already disconnected, that's OK)
        try:
            await conv_manager.send_summary_event(summary_data)
            logger.info("Summary event sent to frontend")
        except Exception as send_err:
            logger.warning(f"Could not send summary to frontend (client may have disconnected): {send_err}")

        logger.info("=== CONVERSATION END HANDLER COMPLETED SUCCESSFULLY ===")

    except Exception as e:
        logger.error(f"=== ERROR IN CONVERSATION END HANDLER: {e} ===", exc_info=True)
        raise  # Re-raise so shutdown callback sees the error


def prewarm(proc: JobProcess):
    """Prewarm function to load models before job starts."""
    proc.userdata["vad"] = silero.VAD.load()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
