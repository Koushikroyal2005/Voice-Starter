'use client';

import { type Dispatch, useCallback, useLayoutEffect, useRef } from 'react';
import { type useSessionContext } from '@livekit/components-react';
import { type Command } from '../state';

export interface ControlState {
  command: Command;
  error: string | null;
  interrupted: boolean;
}
export type ControlAction =
  | { type: 'command'; command: Command }
  | { type: 'error'; message: string }
  | { type: 'interrupted' }
  | { type: 'progress' }
  | { type: 'recovered' }
  | { type: 'settled' }
  | { type: 'reset' };
export function controlReducer(state: ControlState, action: ControlAction): ControlState {
  switch (action.type) {
    case 'command':
      return { ...state, command: action.command, error: null };
    case 'error':
      return { ...state, command: 'idle', error: action.message };
    case 'interrupted':
      return { ...state, interrupted: true };
    case 'progress':
      return { ...state, interrupted: false };
    case 'recovered':
      return { ...state, error: null };
    case 'settled':
      return { ...state, command: 'idle' };
    case 'reset':
      return { command: 'idle', error: null, interrupted: false };
  }
}
type Session = ReturnType<typeof useSessionContext>;
interface Operation {
  controller: AbortController;
  kind: 'start' | 'end' | 'interrupt';
}

// Owns commands, not a second connection state machine. LiveKit owns the room.
export function useVoiceLifecycle(
  session: Session,
  dispatch: Dispatch<ControlAction>,
  reportError: (error: unknown) => void
) {
  const operation = useRef<Operation | null>(null);
  const mounted = useRef(false);
  const boundRoom = useRef(session.room);
  useLayoutEffect(() => {
    mounted.current = true;
    boundRoom.current = session.room;
    return () => {
      mounted.current = false;
      const pending = operation.current;
      operation.current = null;
      pending?.controller.abort();
      // Preserve established sessions; cancel only our unfinished startup.
      if (pending?.kind === 'start') void session.room.disconnect().catch(() => undefined);
    };
  }, [session.room]);
  // Command generations survive native connecting -> connected transitions.
  const claim = useCallback(
    (kind: Operation['kind']) => {
      if (!mounted.current || boundRoom.current !== session.room || operation.current) return null;
      const next = { controller: new AbortController(), kind };
      operation.current = next;
      return next;
    },
    [session.room]
  );
  const owns = useCallback(
    (value: Operation) => mounted.current && operation.current === value,
    []
  );
  const invalidateInterruption = useCallback(() => {
    if (mounted.current && operation.current?.kind === 'interrupt') {
      operation.current = null;
      dispatch({ type: 'settled' });
    }
  }, [dispatch]);

  const start = useCallback(
    async (textOnly: boolean, beginSession: () => void) => {
      const pending = claim('start');
      if (!pending) return;
      const { signal } = pending.controller;
      beginSession();
      dispatch({ type: 'reset' });
      dispatch({ type: 'command', command: 'starting' });
      try {
        await session.prepareConnection(); // SDK preparation has no AbortSignal option.
        if (!owns(pending) || signal.aborted) return;
        await session.start({ tracks: { microphone: { enabled: !textOnly } }, signal });
        if (owns(pending) && !signal.aborted) dispatch({ type: 'command', command: 'idle' });
      } catch (error) {
        if (!owns(pending)) return;
        await session.room.disconnect().catch(() => undefined);
        if (owns(pending) && !signal.aborted) reportError(error);
      } finally {
        if (owns(pending)) {
          operation.current = null;
          if (signal.aborted) dispatch({ type: 'reset' });
        }
      }
    },
    [claim, owns, dispatch, reportError, session]
  );
  const cancelStart = useCallback(
    (invalidate: () => void) => {
      if (
        !mounted.current ||
        boundRoom.current !== session.room ||
        operation.current?.kind !== 'start'
      )
        return;
      operation.current.controller.abort();
      invalidate();
      // Keep the lock until the old SDK startup settles, avoiding overlapping connects.
      void session.room.disconnect().catch(() => undefined);
    },
    [session.room]
  );
  const end = useCallback(
    async (invalidate: () => void, resynchronize: () => void) => {
      const pending = claim('end');
      if (!pending) return;
      invalidate();
      dispatch({ type: 'command', command: 'ending' });
      try {
        await session.end();
        if (owns(pending)) dispatch({ type: 'reset' });
      } catch (error) {
        if (owns(pending)) {
          reportError(error);
          // A rejected native end may leave the room connected. Restore a new
          // synchronization generation, never reactivate the invalidated one.
          resynchronize();
        }
      } finally {
        if (owns(pending)) operation.current = null;
      }
    },
    [claim, owns, dispatch, reportError, session]
  );
  const interrupt = useCallback(
    async (interruptAgent: () => Promise<boolean>) => {
      if (!session.isConnected) return;
      const pending = claim('interrupt');
      if (!pending) return;
      dispatch({ type: 'command', command: 'interrupting' });
      try {
        const acknowledged = await interruptAgent();
        if (owns(pending)) {
          if (acknowledged) dispatch({ type: 'interrupted' });
          dispatch({ type: 'command', command: 'idle' });
        }
      } catch {
        if (owns(pending))
          dispatch({
            type: 'error',
            message:
              'The worker could not confirm interruption. You can end the session to stop playback.',
          });
      } finally {
        if (owns(pending)) operation.current = null;
      }
    },
    [claim, owns, session.isConnected, dispatch]
  );
  return { start, cancelStart, end, interrupt, invalidateInterruption };
}
