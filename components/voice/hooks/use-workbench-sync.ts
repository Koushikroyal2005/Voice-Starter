'use client';

import { type Dispatch, useCallback, useLayoutEffect, useRef, useState } from 'react';
import { DisconnectReason, type RemoteParticipant, RoomEvent } from 'livekit-client';
import { type useSessionContext } from '@livekit/components-react';
import { DEFAULT_USE_CASE, parseUseCaseConfig } from '@/lib/usecase-config';
import { WORKBENCH_TOPIC, encodeRpcRequest, parseRpcResponse } from '@/lib/workbench/contracts';
import {
  type ToolActivity,
  type VoiceResult,
  mergeToolActivities,
  parseWorkerEvent,
} from '../state';
import { type ControlAction } from './use-voice-lifecycle';

interface Generation {
  room: Session['room'];
  identity: string | undefined;
  valid: boolean;
  dispose: () => void;
  snapshot: number;
  live: number;
  changed: Map<string, number>;
}
type Session = ReturnType<typeof useSessionContext>;

// Each scope owns one committed room/agent/connection/config binding. LiveKit RPC
// has no cancellation signal: fence both success and failure after every await.
export function useWorkbenchSync(
  session: Session,
  identity: string | undefined,
  useCaseId: string | undefined,
  dispatch: Dispatch<ControlAction>,
  reportError: (error: unknown) => void,
  invalidateInterruption: () => void
) {
  const [tools, setTools] = useState<ToolActivity[]>([]);
  const [results, setResults] = useState<VoiceResult[]>([]);
  const [useCase, setUseCase] = useState(DEFAULT_USE_CASE);
  const [refresh, setRefresh] = useState(0);
  const resynchronize = useCallback(() => setRefresh((value) => value + 1), []);
  const generation = useRef<Generation | null>(null);
  const markUnknown = useCallback(
    () =>
      setTools((old) =>
        old.map((t) =>
          ['running', 'confirmation_required', 'selected'].includes(t.status)
            ? { ...t, status: 'unknown', confirmationId: undefined }
            : t
        )
      ),
    []
  );
  const invalidate = useCallback(() => {
    generation.current?.dispose();
    markUnknown();
  }, [markUnknown]);
  const current = useCallback(
    (scope: Generation) => generation.current === scope && scope.valid,
    []
  );
  const beginSession = useCallback(() => {
    invalidate();
    setTools([]);
    setResults([]);
    setUseCase(DEFAULT_USE_CASE);
  }, [invalidate]);
  const refreshTools = useCallback(
    async (scope: Generation) => {
      if (!identity || session.connectionState !== 'connected' || !current(scope)) return;
      const request = ++scope.snapshot;
      const liveAtRequest = scope.live;
      try {
        const raw = await session.room.localParticipant.performRpc({
          destinationIdentity: identity,
          method: 'voice.tools_state',
          payload: encodeRpcRequest('voice.tools_state', {}),
          responseTimeout: 5000,
        });
        if (!current(scope) || request !== scope.snapshot) return;
        const list = parseRpcResponse('voice.tools_state', raw);
        if (!list) return;
        setTools((old) => {
          if (!current(scope) || request !== scope.snapshot) return old;
          return list.reduce((previous, item) => {
            const event = parseWorkerEvent(JSON.stringify(item));
            if (event?.type !== 'tool') return previous;
            const existing = previous.find((t) => t.id === event.tool.id);
            // Legacy workers may omit revisions. Live events win unless the
            // snapshot has a strictly newer revision than that live event.
            if (
              (scope.changed.get(item.id) ?? 0) > liveAtRequest &&
              existing &&
              (event.tool.revision === undefined ||
                existing.revision === undefined ||
                event.tool.revision <= existing.revision)
            )
              return previous;
            return mergeToolActivities(previous, event.tool);
          }, old);
        });
      } catch {
        /* Optional snapshots: live events remain usable with older workers. */
      }
    },
    [current, identity, session.connectionState, session.room]
  );

  useLayoutEffect(() => {
    const scope: Generation = {
      room: session.room,
      identity,
      valid: true,
      dispose: () => {},
      snapshot: 0,
      live: 0,
      changed: new Map(),
    };
    let disposed = false;
    generation.current = scope;
    const connected = session.connectionState === 'connected' && !!identity;
    const onData = (
      data: Uint8Array,
      participant?: RemoteParticipant,
      _kind?: unknown,
      topic?: string
    ) => {
      if (
        !current(scope) ||
        !connected ||
        topic !== WORKBENCH_TOPIC ||
        participant?.identity !== identity ||
        data.byteLength > 16384
      )
        return;
      const event = parseWorkerEvent(new TextDecoder().decode(data));
      if (event?.type === 'error') dispatch({ type: 'error', message: event.message });
      if (event?.type === 'interrupted') dispatch({ type: 'interrupted' });
      if (event?.type === 'tool') {
        scope.changed.set(event.tool.id, ++scope.live);
        setTools((old) => (current(scope) ? mergeToolActivities(old, event.tool) : old));
      }
      if (event?.type === 'result')
        setResults((old) =>
          current(scope)
            ? [...old.filter((r) => r.id !== event.result.id), event.result].slice(-20)
            : old
        );
    };
    const onMediaError = (error: Error) => {
      if (current(scope)) reportError(error);
    };
    const onDisconnected = (reason?: DisconnectReason) => {
      if (generation.current !== scope || disposed) return;
      scope.dispose();
      markUnknown();
      setUseCase(DEFAULT_USE_CASE);
      if (reason !== DisconnectReason.CLIENT_INITIATED)
        dispatch({
          type: 'error',
          message:
            'Session disconnected. Check your connection and worker, then start a new session.',
        });
    };
    const onConnectionChanged = (state: string) => {
      // LiveKit emits ConnectionStateChanged(disconnected) BEFORE Disconnected.
      // Fence RPC/data now, but keep the lifecycle listener until it has the reason.
      if (state !== session.connectionState) {
        scope.valid = false;
        invalidateInterruption();
      }
    };
    scope.dispose = () => {
      if (disposed) return;
      disposed = true;
      scope.valid = false;
      invalidateInterruption();
      session.room
        .off(RoomEvent.DataReceived, onData)
        .off(RoomEvent.MediaDevicesError, onMediaError)
        .off(RoomEvent.Disconnected, onDisconnected)
        .off(RoomEvent.ConnectionStateChanged, onConnectionChanged);
    };
    session.room
      .on(RoomEvent.DataReceived, onData)
      .on(RoomEvent.MediaDevicesError, onMediaError)
      .on(RoomEvent.Disconnected, onDisconnected)
      .on(RoomEvent.ConnectionStateChanged, onConnectionChanged);
    setUseCase(DEFAULT_USE_CASE);
    if (connected) {
      void refreshTools(scope);
      if (useCaseId) {
        setUseCase({
          ...DEFAULT_USE_CASE,
          notice: 'Loading application details from the connected worker.',
        });
        const unavailable = () => {
          if (current(scope))
            setUseCase({
              ...DEFAULT_USE_CASE,
              notice:
                'Application details could not be verified. Check the worker configuration before using specialized features.',
            });
        };
        void (async () => {
          try {
            const raw = await session.room.localParticipant.performRpc({
              destinationIdentity: identity,
              method: 'voice.usecase_config',
              payload: encodeRpcRequest('voice.usecase_config', {}),
              responseTimeout: 5000,
            });
            if (!current(scope)) return;
            const config = parseUseCaseConfig(raw);
            if (config?.id === useCaseId) setUseCase(config);
            else unavailable();
          } catch {
            unavailable();
          }
        })();
      }
    }
    return scope.dispose;
  }, [
    current,
    dispatch,
    identity,
    invalidateInterruption,
    markUnknown,
    refreshTools,
    refresh,
    reportError,
    session.connectionState,
    session.room,
    useCaseId,
  ]);

  const confirmTool = useCallback(
    async (confirmationId: string, approved: boolean) => {
      const scope = generation.current;
      if (
        !scope ||
        !current(scope) ||
        scope.room !== session.room ||
        scope.identity !== identity ||
        !identity ||
        session.connectionState !== 'connected'
      )
        throw new Error('Reconnect before answering this confirmation.');
      try {
        const raw = await session.room.localParticipant.performRpc({
          destinationIdentity: identity,
          method: 'voice.confirm_tool',
          payload: encodeRpcRequest('voice.confirm_tool', {
            confirmation_id: confirmationId,
            approved,
          }),
          responseTimeout: 5000,
        });
        if (!current(scope)) return;
        if (!parseRpcResponse('voice.confirm_tool', raw))
          throw new Error('The worker returned an invalid confirmation response.');
        await refreshTools(scope);
      } catch (error) {
        if (current(scope)) throw error;
      }
    },
    [current, identity, refreshTools, session.connectionState, session.room]
  );
  const interruptAgent = useCallback(async () => {
    const scope = generation.current;
    if (
      !scope ||
      !current(scope) ||
      scope.room !== session.room ||
      scope.identity !== identity ||
      !identity ||
      session.connectionState !== 'connected'
    )
      return false;
    try {
      const raw = await session.room.localParticipant.performRpc({
        destinationIdentity: identity,
        method: 'voice.interrupt',
        payload: encodeRpcRequest('voice.interrupt', {}),
        responseTimeout: 5000,
      });
      if (!current(scope)) return false;
      if (!parseRpcResponse('voice.interrupt', raw))
        throw new Error('Invalid interruption response.');
      return true;
    } catch (error) {
      if (current(scope)) throw error;
      return false;
    }
  }, [current, identity, session.connectionState, session.room]);
  return {
    tools,
    results,
    useCase,
    beginSession,
    invalidate,
    resynchronize,
    confirmTool,
    interruptAgent,
  };
}
