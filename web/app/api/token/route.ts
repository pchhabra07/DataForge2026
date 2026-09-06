/**
 * LiveKit Token API Route
 *
 * Generates a JWT access token for connecting to a LiveKit room.
 * Used by the web client to authenticate with the LiveKit server.
 *
 * GET /api/token?room=<room>&identity=<identity>
 */

import { NextRequest, NextResponse } from "next/server";
import { AccessToken, AgentDispatchClient } from "livekit-server-sdk";

export async function GET(req: NextRequest) {
  const room = req.nextUrl.searchParams.get("room") || "echocoach-dev";
  const identity =
    req.nextUrl.searchParams.get("identity") ||
    `user-${Math.random().toString(36).slice(2, 8)}`;

  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  const livekitUrl = process.env.LIVEKIT_URL;

  if (!apiKey || !apiSecret || !livekitUrl) {
    return NextResponse.json(
      {
        error:
          "Missing LIVEKIT_API_KEY, LIVEKIT_API_SECRET, or LIVEKIT_URL. " +
          "Copy .env.example to .env.local and fill in values.",
      },
      { status: 500 }
    );
  }

  const token = new AccessToken(apiKey, apiSecret, {
    identity,
    name: identity,
  });
  token.addGrant({
    roomJoin: true,
    room,
    canPublish: true,
    canSubscribe: true,
  });

  const jwt = await token.toJwt();

  try {
    const httpHost = livekitUrl.replace(/^wss:/, "https:");
    const dispatchClient = new AgentDispatchClient(
      httpHost,
      apiKey,
      apiSecret
    );
    await dispatchClient.createDispatch(room, "echocoach");
  } catch (e) {
    console.warn("Agent dispatch failed, agent may not join:", e);
  }

  return NextResponse.json({
    token: jwt,
    room,
    identity,
    url: livekitUrl,
  });
}
