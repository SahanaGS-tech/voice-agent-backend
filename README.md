# Voice Agent Backend

Python-based voice agent backend using LiveKit Agents framework for appointment booking.

## Features

- Real-time voice conversations using LiveKit
- Speech-to-Text via Deepgram (Nova-2)
- Text-to-Speech via Cartesia
- LLM integration with OpenAI GPT-4o-mini
- Tool calling for appointment management
- Conversation summaries

## Tech Stack

- **LiveKit Agents** - Voice pipeline framework
- **Deepgram** - Speech recognition (STT)
- **Cartesia** - Voice synthesis (TTS)
- **OpenAI** - Language model (LLM)
- **Supabase** - Database
- **FastAPI** - Token server

## Setup

### 1. Install Dependencies

```bash
cd voice-agent-backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required environment variables:
- `LIVEKIT_URL` - Your LiveKit Cloud URL
- `LIVEKIT_API_KEY` - LiveKit API key
- `LIVEKIT_API_SECRET` - LiveKit API secret
- `DEEPGRAM_API_KEY` - Deepgram API key
- `CARTESIA_API_KEY` - Cartesia API key
- `OPENAI_API_KEY` - OpenAI API key
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase anon key

### 3. Set Up Database

Run the SQL schema in your Supabase SQL editor:

```sql
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

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    summary TEXT,
    appointments_discussed JSONB DEFAULT '[]',
    preferences_mentioned JSONB DEFAULT '[]',
    transcript JSONB DEFAULT '[]',
    cost_breakdown JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_contact ON users(contact_number);
CREATE INDEX IF NOT EXISTS idx_appointments_user ON appointments(user_id);
CREATE INDEX IF NOT EXISTS idx_appointments_date_time ON appointments(date, time);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
```

### 4. Run the Services

You need to run two services:

**Terminal 1 - Token Server:**
```bash
python token_server.py
```

**Terminal 2 - Voice Agent:**
```bash
python agent.py dev
```

The token server runs on `http://localhost:8081` (to avoid conflict with frontend dev server on port 8080).

## Project Structure

```
voice-agent-backend/
├── agent.py              # Main LiveKit agent
├── token_server.py       # FastAPI token server
├── tools/
│   ├── __init__.py
│   ├── appointments.py   # Appointment tool functions
│   └── slots.py          # Available slots logic
├── db/
│   ├── __init__.py
│   └── supabase.py       # Database client
├── prompts/
│   ├── __init__.py
│   └── system.py         # System prompts
├── requirements.txt
├── .env.example
└── README.md
```

## Tool Functions

The agent has access to these tools:

| Tool | Description |
|------|-------------|
| `identify_user` | Identify user by phone number |
| `fetch_slots` | Get available appointment slots |
| `book_appointment` | Book a new appointment |
| `retrieve_appointments` | Get user's appointments |
| `cancel_appointment` | Cancel an appointment |
| `modify_appointment` | Reschedule an appointment |
| `end_conversation` | End call and generate summary |

## Latency Optimization

The agent is configured for low latency:

- Uses GPT-4o-mini (fast model)
- Streaming enabled for all components
- Silero VAD for quick speech detection
- Interruption handling enabled

Expected latency:
- Normal responses: 1.5-3 seconds
- With tool calls: 3-5 seconds

## Known Limitations

1. Avatar integration is placeholder (needs Beyond Presence/Tavus SDK)
2. Cost tracking is estimated (actual costs may vary)
3. Slots are hardcoded (9 AM - 4 PM, weekdays only)

## License

MIT
# voice-agent-backend
