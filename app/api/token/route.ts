import { NextResponse } from 'next/server';
import {
  AccessToken,
  type AccessTokenOptions,
  RoomConfiguration,
  type VideoGrant,
} from 'livekit-server-sdk';
import { randomUUID } from 'node:crypto';

type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
};

// NOTE: you are expected to define the following environment variables in `.env.local`:
const API_KEY = process.env.LIVEKIT_API_KEY?.trim();
const API_SECRET = process.env.LIVEKIT_API_SECRET?.trim();
const LIVEKIT_URL = process.env.LIVEKIT_URL?.trim();

// don't cache the results
export const revalidate = 0;

export async function POST(req: Request) {
  // This unauthenticated issuer is for local development ONLY, including previews.
  if (process.env.NODE_ENV !== 'development') {
    return new NextResponse(
      'Token issuance is disabled outside development. Add authentication before production use.',
      { status: 403, headers: { 'Cache-Control': 'no-store' } }
    );
  }

  const missing = [
    ['LIVEKIT_URL', LIVEKIT_URL],
    ['LIVEKIT_API_KEY', API_KEY],
    ['LIVEKIT_API_SECRET', API_SECRET],
  ]
    .filter(([, value]) => !value?.trim())
    .map(([name]) => name);
  if (missing.length) {
    return new NextResponse(
      `Missing server configuration: ${missing.join(', ')}. Set .env.local and restart Next.js.`,
      {
        status: 503,
        headers: { 'Cache-Control': 'no-store' },
      }
    );
  }

  try {
    if (LIVEKIT_URL === undefined) {
      throw new Error('LIVEKIT_URL is not defined');
    }
    if (API_KEY === undefined) {
      throw new Error('LIVEKIT_API_KEY is not defined');
    }
    if (API_SECRET === undefined) {
      throw new Error('LIVEKIT_API_SECRET is not defined');
    }

    // Preserve Session API room settings; dispatch is authoritative on the server.
    let roomConfig: RoomConfiguration;
    try {
      const body = await req.json();
      roomConfig = body?.room_config
        ? RoomConfiguration.fromJson(body.room_config, { ignoreUnknownFields: true })
        : new RoomConfiguration();
    } catch {
      return new NextResponse('Invalid token request.', { status: 400 });
    }
    const agentName = process.env.AGENT_NAME?.trim();
    roomConfig.agents = RoomConfiguration.fromJson({
      agents: agentName ? [{ agentName }] : [],
    }).agents;

    // Generate participant token
    const participantName = 'user';
    const participantIdentity = `voice_assistant_user_${randomUUID()}`;
    const roomName = `voice_assistant_room_${randomUUID()}`;

    const participantToken = await createParticipantToken(
      { identity: participantIdentity, name: participantName },
      roomName,
      roomConfig
    );

    // Return connection details
    const data: ConnectionDetails = {
      serverUrl: LIVEKIT_URL,
      roomName,
      participantName,
      participantToken,
    };
    const headers = new Headers({
      'Cache-Control': 'no-store',
    });
    return NextResponse.json(data, { headers });
  } catch {
    // Never return JWTs, credentials, or raw SDK errors to the browser/logs.
    console.error('LiveKit token generation failed. Check server configuration.');
    return new NextResponse('Unable to create a voice session. Check server configuration.', {
      status: 500,
    });
  }
}

function createParticipantToken(
  userInfo: AccessTokenOptions,
  roomName: string,
  roomConfig: RoomConfiguration | undefined
): Promise<string> {
  const at = new AccessToken(API_KEY, API_SECRET, {
    ...userInfo,
    ttl: '15m',
  });
  const grant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  };
  at.addGrant(grant);

  if (roomConfig) {
    at.roomConfig = roomConfig;
  }

  return at.toJwt();
}
