"""
Token Server for LiveKit
Generates access tokens for clients to connect to LiveKit rooms.
Run this alongside the agent.
"""
import os
from datetime import datetime, timedelta
from typing import Optional, List
from dotenv import load_dotenv
from livekit import api
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db.supabase import Database

load_dotenv()

app = FastAPI(title="LiveKit Token Server")
db = Database()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    room_name: str
    participant_name: str


class TokenResponse(BaseModel):
    token: str
    room_name: str
    participant_name: str


class AppointmentSummary(BaseModel):
    id: str
    action: str
    date: str
    time: str
    rescheduled_time: Optional[str] = None


class CostUsage(BaseModel):
    stt_seconds: float
    tts_characters: int
    llm_input_tokens: int
    llm_output_tokens: int


class CostBreakdown(BaseModel):
    stt_cost: float
    tts_cost: float
    llm_cost: float
    total_cost: float
    usage: Optional[CostUsage] = None


class ConversationSummaryResponse(BaseModel):
    user_name: Optional[str] = None
    user_phone: Optional[str] = None
    summary: Optional[str] = None
    appointments: Optional[List[AppointmentSummary]] = None
    preferences: Optional[List[str]] = None
    costs: Optional[CostBreakdown] = None
    duration_seconds: Optional[int] = None


@app.get("/")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/token", response_model=TokenResponse)
async def get_token(request: TokenRequest):
    """Generate a LiveKit access token for a participant."""
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not api_key or not api_secret:
        raise HTTPException(
            status_code=500,
            detail="LiveKit API credentials not configured"
        )

    # Create access token
    token = api.AccessToken(api_key, api_secret)

    # Set token identity and grants
    token.with_identity(request.participant_name)
    token.with_name(request.participant_name)

    # Grant permissions
    token.with_grants(api.VideoGrants(
        room_join=True,
        room=request.room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    ))

    # Set expiration (1 hour)
    token.with_ttl(timedelta(hours=1))

    jwt_token = token.to_jwt()

    return TokenResponse(
        token=jwt_token,
        room_name=request.room_name,
        participant_name=request.participant_name
    )


@app.get("/summary/{room_name}", response_model=ConversationSummaryResponse)
async def get_summary(room_name: str):
    """Get conversation summary by room name."""
    conversation = db.get_conversation_by_room(room_name)

    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="Summary not found for this room"
        )

    # Transform appointments to match frontend format
    appointments = []
    if conversation.get("appointments_discussed"):
        for apt in conversation["appointments_discussed"]:
            appointments.append(AppointmentSummary(
                id=apt.get("id", ""),
                action=apt.get("action", "booked"),
                date=apt.get("date", apt.get("new_date", "")),
                time=apt.get("time", apt.get("new_time", "")),
                rescheduled_time=f"{apt.get('new_date', '')} at {apt.get('new_time', '')}" if apt.get("action") == "modified" and apt.get("new_time") else None
            ))

    # Transform cost breakdown
    costs = None
    if conversation.get("cost_breakdown"):
        cb = conversation["cost_breakdown"]
        usage = None
        if cb.get("usage"):
            usage = CostUsage(
                stt_seconds=cb["usage"].get("stt_seconds", 0),
                tts_characters=cb["usage"].get("tts_characters", 0),
                llm_input_tokens=cb["usage"].get("llm_input_tokens", 0),
                llm_output_tokens=cb["usage"].get("llm_output_tokens", 0)
            )
        costs = CostBreakdown(
            stt_cost=cb.get("stt_cost", 0),
            tts_cost=cb.get("tts_cost", 0),
            llm_cost=cb.get("llm_cost", 0),
            total_cost=cb.get("total_cost", 0),
            usage=usage
        )

    return ConversationSummaryResponse(
        user_name=conversation.get("user_name"),
        user_phone=conversation.get("user_phone"),
        summary=conversation.get("summary"),
        appointments=appointments if appointments else None,
        preferences=conversation.get("preferences_mentioned"),
        costs=costs,
        duration_seconds=conversation.get("duration_seconds")
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
