#!/usr/bin/env python3
"""
LiveKit Token Generator — Local Development

Generates a JWT access token for connecting to a LiveKit room.
Used by the web client during local development.

Usage:
    python scripts/generate_token.py [--room ROOM] [--identity IDENTITY]

Requires LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env.local.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))


def generate_token(room: str, identity: str) -> str:
    """Generate a LiveKit access token."""
    from livekit.api import AccessToken, VideoGrants

    api_key = os.environ.get("LIVEKIT_API_KEY")
    api_secret = os.environ.get("LIVEKIT_API_SECRET")

    if not api_key or not api_secret:
        print("❌ LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env.local")
        sys.exit(1)

    token = AccessToken(api_key, api_secret)
    token.identity = identity
    token.name = identity

    grants = VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
    )
    token.video_grants = grants

    return token.to_jwt()


def main():
    parser = argparse.ArgumentParser(description="Generate LiveKit dev token")
    parser.add_argument("--room", default="echocoach-dev", help="Room name")
    parser.add_argument("--identity", default="user-dev", help="User identity")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    jwt = generate_token(args.room, args.identity)

    if args.json:
        print(json.dumps({
            "token": jwt,
            "room": args.room,
            "identity": args.identity,
            "url": os.environ.get("LIVEKIT_URL", ""),
        }, indent=2))
    else:
        print(f"Room:     {args.room}")
        print(f"Identity: {args.identity}")
        print(f"URL:      {os.environ.get('LIVEKIT_URL', '(not set)')}")
        print(f"Token:    {jwt}")


if __name__ == "__main__":
    main()
