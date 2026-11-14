'use client';

import { useCallback, useEffect, useReducer, useState } from 'react';
import { useAgent, useSessionContext, useSessionMessages } from '@livekit/components-react';
import { controlReducer, useVoiceLifecycle } from './hooks/use-voice-lifecycle';
import { useWorkbenchSync } from './hooks/use-workbench-sync';
import { type TimelineEntry } from './panels';
import { deriveVoiceState, mediaErrorMessage } from './state';

// Public presentation facade. Native LiveKit hooks remain the source of truth.
export function useVoiceWorkbench() {
  const session = useSessionContext();
  const agent = useAgent();
  const { messages } = useSessionMessages();
  const [control, dispatch] = useReducer(controlReducer, {
    command: 'idle',
    error: null,
    interrupted: false,
  });
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const reportError = useCallback(
    (error: unknown) => dispatch({ type: 'error', message: mediaErrorMessage(error) }),
    []
  );
  const lifecycle = useVoiceLifecycle(session, dispatch, reportError);
  const synchronization = useWorkbenchSync(
    session,
    agent.isConnected ? agent.identity : undefined,
    agent.attributes['voice.usecase'],
    dispatch,
    reportError,
    lifecycle.invalidateInterruption
  );
  const { tools, results, useCase, confirmTool, beginSession } = synchronization;
  const resetConversation = useCallback(() => {
    beginSession();
    setEntries([]);
  }, [beginSession]);
  const {
    start: startSession,
    cancelStart: cancelSessionStart,
    end: endSession,
    interrupt: interruptSession,
  } = lifecycle;
  const { invalidate, resynchronize, interruptAgent } = synchronization;
  const start = useCallback(
    (textOnly = false) => startSession(textOnly, resetConversation),
    [startSession, resetConversation]
  );
  const cancelStart = useCallback(
    () => cancelSessionStart(invalidate),
    [cancelSessionStart, invalidate]
  );
  const end = useCallback(
    () => endSession(invalidate, resynchronize),
    [endSession, invalidate, resynchronize]
  );
  const interrupt = useCallback(
    () => interruptSession(interruptAgent),
    [interruptSession, interruptAgent]
  );
  const state = deriveVoiceState({
    connection: session.connectionState,
    agent: agent.state,
    ...control,
    executing: tools.some((t) => t.status === 'running'),
    awaitingConfirmation: tools.some((t) => t.status === 'confirmation_required'),
  });
  useEffect(() => {
    dispatch({ type: 'progress' });
    if (agent.state === 'speaking') dispatch({ type: 'recovered' });
  }, [agent.state]);
  useEffect(() => {
    setEntries((previous) =>
      [...previous, { id: (previous.at(-1)?.id ?? 0) + 1, state, at: Date.now() }].slice(-80)
    );
  }, [state]);
  return {
    session,
    agent,
    messages,
    state,
    control,
    tools,
    results,
    entries,
    useCase,
    start,
    cancelStart,
    end,
    interrupt,
    reportError,
    confirmTool,
  };
}
