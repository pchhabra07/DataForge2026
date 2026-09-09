#!/usr/bin/env python3
"""
LiveKit Token Generator - Local Development

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
        print(
            "[ERROR] LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env.local"
        )
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
    import secrets

    parser = argparse.ArgumentParser(description="Generate LiveKit dev token")
    parser.add_argument("--room", default="echocoach-dev", help="Room name")
    parser.add_argument("--identity", default=None, help="User identity")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--show-token", action="store_true", help="Print raw JWT")
    args = parser.parse_args()

    identity = args.identity or f"user-{secrets.token_hex(4)}"
    jwt = generate_token(args.room, identity)

    if args.json:
        out = {
            "room": args.room,
            "identity": identity,
            "url": os.environ.get("LIVEKIT_URL", ""),
        }
        if args.show_token:
            out["token"] = jwt
        print(json.dumps(out, indent=2))
    else:
        print(f"Room:     {args.room}")
        print(f"Identity: {identity}")
        print(f"URL:      {os.environ.get('LIVEKIT_URL', '(not set)')}")
        if args.show_token:
            print(f"Token:    {jwt}")
        else:
            print("Token hidden. Use --show-token to print it.")


if __name__ == "__main__":
    main()
