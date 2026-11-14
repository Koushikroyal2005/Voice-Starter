'use client';

import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { DisconnectReason, type RemoteParticipant, RoomEvent } from 'livekit-client';
import { useAgent, useSessionContext, useSessionMessages } from '@livekit/components-react';
import { type TimelineEntry } from './panels';
import {
  type Command,
  type ToolActivity,
  type VoiceResult,
  deriveVoiceState,
  mediaErrorMessage,
  parseWorkerEvent,
} from './state';

interface ControlState {
  command: Command;
  error: string | null;
  interrupted: boolean;
}
type Action =
  | { type: 'command'; command: Command }
  | { type: 'error'; message: string }
  | { type: 'interrupted' }
  | { type: 'progress' }
  | { type: 'reset' };
function reducer(state: ControlState, action: Action): ControlState {
  switch (action.type) {
    case 'command':
      return { ...state, command: action.command, error: null };
    case 'error':
      return { ...state, command: 'idle', error: action.message };
    case 'interrupted':
      return { ...state, interrupted: true };
    case 'progress':
      return { ...state, interrupted: false };
    case 'reset':
      return { command: 'idle', error: null, interrupted: false };
  }
}
export function useVoiceWorkbench() {
  const session = useSessionContext();
  const agent = useAgent();
  const { messages } = useSessionMessages();
  const [control, dispatch] = useReducer(reducer, {
    command: 'idle',
    error: null,
    interrupted: false,
  });
  const commandLock = useRef(false);
  const startAbort = useRef<AbortController | null>(null);
  const [tools, setTools] = useState<ToolActivity[]>([]);
  const [results, setResults] = useState<VoiceResult[]>([]);
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const state = deriveVoiceState({
    connection: session.connectionState,
    agent: agent.state,
    ...control,
    executing: tools.some((t) => t.status === 'running'),
  });
  const identity = agent.isConnected ? agent.identity : undefined;
  const reportError = useCallback(
    (error: unknown) => dispatch({ type: 'error', message: mediaErrorMessage(error) }),
    []
  );
  useEffect(() => {
    dispatch({ type: 'progress' });
  }, [agent.state]);
  useEffect(() => {
    setEntries((previous) =>
      [...previous, { id: (previous.at(-1)?.id ?? 0) + 1, state, at: Date.now() }].slice(-80)
    );
  }, [state]);
  useEffect(() => {
    const onData = (
      data: Uint8Array,
      participant?: RemoteParticipant,
      _kind?: unknown,
      topic?: string
    ) => {
      if (
        topic !== 'voice.workbench.v1' ||
        !identity ||
        participant?.identity !== identity ||
        data.byteLength > 16384
      )
        return;
      const event = parseWorkerEvent(new TextDecoder().decode(data));
      if (event?.type === 'interrupted') dispatch({ type: 'interrupted' });
      if (event?.type === 'tool')
        setTools((old) => [...old.filter((t) => t.id !== event.tool.id), event.tool].slice(-30));
      if (event?.type === 'result')
        setResults((old) =>
          [...old.filter((r) => r.id !== event.result.id), event.result].slice(-20)
        );
    };
    const onDisconnected = (reason?: DisconnectReason) => {
      setTools((old) =>
        old.map((t) => (t.status === 'running' ? { ...t, status: 'cancelled' } : t))
      );
      if (reason !== DisconnectReason.CLIENT_INITIATED)
        dispatch({
          type: 'error',
          message:
            'Session disconnected. Check your connection and worker, then start a new session.',
        });
    };
    session.room
      .on(RoomEvent.DataReceived, onData)
      .on(RoomEvent.MediaDevicesError, reportError)
      .on(RoomEvent.Disconnected, onDisconnected);
    return () => {
      session.room
        .off(RoomEvent.DataReceived, onData)
        .off(RoomEvent.MediaDevicesError, reportError)
        .off(RoomEvent.Disconnected, onDisconnected);
    };
  }, [identity, session.room, reportError]);
  async function start(textOnly = false) {
    if (commandLock.current) return;
    commandLock.current = true;
    const controller = new AbortController();
    startAbort.current = controller;
    dispatch({ type: 'reset' });
    dispatch({ type: 'command', command: 'starting' });
    setTools([]);
    setResults([]);
    setEntries([]);
    try {
      await session.prepareConnection();
      if (controller.signal.aborted) return;
      await session.start({
        tracks: { microphone: { enabled: !textOnly } },
        signal: controller.signal,
      });
      dispatch({ type: 'command', command: 'idle' });
    } catch (error) {
      await session.room.disconnect().catch(() => undefined);
      if (!controller.signal.aborted) reportError(error);
      else dispatch({ type: 'reset' });
    } finally {
      commandLock.current = false;
      startAbort.current = null;
      if (controller.signal.aborted) dispatch({ type: 'reset' });
    }
  }
  function cancelStart() {
    startAbort.current?.abort();
    // Also disconnect if the browser was waiting for a remote agent to join.
    void session.room.disconnect().catch(() => undefined);
  }
  async function end() {
    if (commandLock.current) return;
    commandLock.current = true;
    dispatch({ type: 'command', command: 'ending' });
    try {
      await session.end();
      dispatch({ type: 'reset' });
    } catch (error) {
      reportError(error);
    } finally {
      commandLock.current = false;
    }
  }
  async function interrupt() {
    if (commandLock.current || !identity || !session.isConnected) return;
    commandLock.current = true;
    dispatch({ type: 'command', command: 'interrupting' });
    try {
      await session.room.localParticipant.performRpc({
        destinationIdentity: identity,
        method: 'voice.interrupt',
        payload: '{}',
        responseTimeout: 5000,
      });
      dispatch({ type: 'interrupted' });
      dispatch({ type: 'command', command: 'idle' });
    } catch {
      dispatch({
        type: 'error',
        message:
          'The worker could not confirm interruption. You can end the session to stop playback.',
      });
    } finally {
      commandLock.current = false;
    }
  }
  return {
    session,
    agent,
    messages,
    state,
    control,
    tools,
    results,
    entries,
    start,
    cancelStart,
    end,
    interrupt,
    reportError,
  };
}
