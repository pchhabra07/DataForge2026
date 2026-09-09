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
  try {
    const rawRoom = req.nextUrl.searchParams.get("room") || "echocoach-dev";
    const room = rawRoom.trim().toLowerCase();
    if (!/^[a-z0-9-]{3,64}$/.test(room)) {
      return NextResponse.json({ error: "Invalid room name" }, { status: 400 });
    }
    const identity = `user-${crypto.randomUUID().slice(0, 8)}`;

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
      ttl: "5m",
    });
    token.addGrant({
      roomJoin: true,
      room,
      canPublish: true,
      canSubscribe: true,
    });

    const jwt = await token.toJwt();

    try {
      const httpHost = livekitUrl.replace(/^wss:/, "https:").replace(/^ws:/, "http:");
      const dispatchClient = new AgentDispatchClient(
        httpHost,
        apiKey,
        apiSecret
      );
      await dispatchClient.createDispatch(room, "echocoach");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      if (!/already|exists|conflict|duplicate/i.test(msg)) {
        console.warn("Agent dispatch failed (non-fatal), agent may not join:", e);
      }
    }

    return NextResponse.json({
      token: jwt,
      room,
      identity,
      url: livekitUrl,
    });
  } catch (e) {
    console.error("[token] Unhandled error:", e);
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Internal server error" },
      { status: 500 }
    );
  }
}
