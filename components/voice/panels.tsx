'use client';

import { useState } from 'react';
import {
  type AgentState as LiveKitAgentState,
  type ReceivedMessage,
} from '@livekit/components-react';
import { AgentChatTranscript } from '@/components/agents-ui/agent-chat-transcript';
import { Button } from '@/components/ui/button';
import { type ToolActivity, type VoiceResult, type VoiceState } from './state';

export function AgentStatus({
  state,
  connected = false,
}: {
  state: VoiceState;
  connected?: boolean;
}) {
  return (
    <div role="status" aria-live="polite" className="text-center">
      <p className="text-3xl font-semibold tracking-tight capitalize">
        {state === 'idle' ? 'Ready when you are' : state.replaceAll('_', ' ')}
      </p>
      <p className="text-muted-foreground mt-3 text-sm">
        {state === 'idle'
          ? connected
            ? 'Send a message, or enable your microphone.'
            : 'Start a voice session, or connect with text.'
          : state === 'error'
            ? 'Check the error above. Retry the connection or end the session.'
            : state === 'connecting'
              ? 'Connecting to LiveKit and waiting for the agent.'
              : state === 'interrupted'
                ? 'Agent speech stopped. You can continue the conversation.'
                : state === 'listening'
                  ? 'Speak naturally. You can interrupt the agent at any time.'
                  : state === 'reconnecting'
                    ? 'Restoring your LiveKit connection…'
                    : 'Your live session, powered by LiveKit.'}
      </p>
    </div>
  );
}
export function ConnectionStatus({ state }: { state: string }) {
  return (
    <span className="bg-muted flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs">
      <span
        aria-hidden
        className={`size-2 rounded-full ${state === 'connected' ? 'bg-teal-500' : 'bg-muted-foreground'}`}
      />
      {state === 'disconnected'
        ? 'Not connected'
        : state === 'signalReconnecting'
          ? 'Reconnecting'
          : state}
    </span>
  );
}
export function LiveTranscript({
  messages,
  agentState,
}: {
  messages: ReceivedMessage[];
  agentState: LiveKitAgentState;
}) {
  return (
    <section
      aria-label="Live transcript"
      className="bg-card flex min-h-96 min-w-0 flex-col rounded-2xl border"
    >
      <div className="border-b p-5">
        <h2 className="font-semibold">Live transcript</h2>
        <p className="text-muted-foreground mt-1 text-xs">
          Speech and text, together. Partial speech is marked live.
        </p>
      </div>
      {messages.length ? (
        <AgentChatTranscript
          messages={messages}
          agentState={agentState}
          className="h-[440px] p-4"
        />
      ) : (
        <p className="text-muted-foreground m-auto p-8 text-center text-sm">
          Your conversation will appear here.
          <br />
          No audio or transcript is simulated.
        </p>
      )}
    </section>
  );
}
export function ToolActivityCard({
  tool,
  onConfirm,
}: {
  tool: ToolActivity;
  onConfirm?: (id: string, approved: boolean) => Promise<void>;
}) {
  const [decision, setDecision] = useState<'idle' | 'submitting' | 'sent' | 'error'>('idle');
  async function decide(approved: boolean) {
    if (!tool.confirmationId || !onConfirm || decision === 'submitting' || decision === 'sent')
      return;
    setDecision('submitting');
    try {
      await onConfirm(tool.confirmationId, approved);
      setDecision('sent');
    } catch {
      setDecision('error');
    }
  }
  return (
    <article className="bg-muted/40 rounded-xl border p-4">
      <div className="flex justify-between gap-3">
        <h3 className="truncate text-sm font-medium">{tool.name}</h3>
        <span role="status" className="text-muted-foreground text-xs">
          {tool.status.replaceAll('_', ' ')}
        </span>
      </div>
      {tool.description && <p className="text-muted-foreground mt-2 text-sm">{tool.description}</p>}
      {tool.phases?.length ? (
        <p className="text-muted-foreground mt-2 text-xs">
          {tool.phases.map((p) => p.replaceAll('_', ' ')).join(' → ')}
        </p>
      ) : null}
      {tool.status === 'confirmation_required' && (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-medium">Review this action before approving.</p>
          <div className="flex flex-wrap gap-2">
            <Button
              className="min-h-11"
              disabled={!onConfirm || decision === 'submitting' || decision === 'sent'}
              onClick={() => void decide(true)}
            >
              Approve action
            </Button>
            <Button
              className="min-h-11"
              variant="outline"
              disabled={!onConfirm || decision === 'submitting' || decision === 'sent'}
              onClick={() => void decide(false)}
            >
              Decline action
            </Button>
          </div>
          {decision === 'sent' && (
            <p role="status" className="text-xs">
              Decision sent. Waiting for worker status.
            </p>
          )}
          {decision === 'error' && (
            <p role="alert" className="text-destructive text-xs">
              Could not confirm this decision. Reconnect and check whether the request is still
              pending before retrying.
            </p>
          )}
        </div>
      )}
    </article>
  );
}
export function ResultCard({ result }: { result: VoiceResult }) {
  return (
    <article className="rounded-xl border p-4">
      <h3 className="text-sm font-semibold">{result.title}</h3>
      <p className="text-muted-foreground mt-2 text-sm whitespace-pre-wrap">{result.text}</p>
    </article>
  );
}
export interface TimelineEntry {
  id: number;
  state: VoiceState;
  at: number;
}
export function ConversationTimeline({
  entries,
  tools,
  results,
  onConfirm,
}: {
  entries: TimelineEntry[];
  tools: ToolActivity[];
  results: VoiceResult[];
  onConfirm?: (id: string, approved: boolean) => Promise<void>;
}) {
  return (
    <section aria-label="Conversation timeline" className="bg-card rounded-2xl border p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-semibold">Session activity</h2>
        <span className="text-muted-foreground text-xs">Live events only</span>
      </div>
      <ol className="flex max-h-36 flex-wrap gap-x-6 gap-y-2 overflow-auto text-xs">
        {entries.map((e) => (
          <li key={e.id}>
            <time className="text-muted-foreground mr-2" dateTime={new Date(e.at).toISOString()}>
              {new Date(e.at).toLocaleTimeString()}
            </time>
            <span className="capitalize">{e.state.replaceAll('_', ' ')}</span>
          </li>
        ))}
      </ol>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {tools.map((t) => (
          <ToolActivityCard key={t.id + (t.confirmationId || '')} tool={t} onConfirm={onConfirm} />
        ))}
        {results.map((r) => (
          <ResultCard key={r.id} result={r} />
        ))}
      </div>
      {!tools.length && !results.length && (
        <p className="text-muted-foreground mt-3 text-xs">
          Tool activity and results appear only when the worker publishes them.
        </p>
      )}
    </section>
  );
}
// A worker may supply a verified language-update callback. Never imply that changing a
// browser dropdown alone can reconfigure remote STT/TTS providers.
export function LanguageSelector({
  value = 'Worker default',
  languages = [],
  onChange,
  disabled,
}: {
  value?: string;
  languages?: string[];
  onChange?: (language: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="text-muted-foreground flex items-center gap-2 text-xs">
      Language
      <select
        aria-label="Session language"
        title={
          onChange
            ? 'Session language'
            : 'Language is configured by the Python worker; live switching is not enabled.'
        }
        value={value}
        disabled={disabled || !onChange}
        onChange={(e) => onChange?.(e.target.value)}
        className="bg-background text-foreground rounded-md border p-2 disabled:opacity-60"
      >
        {[...new Set([value, ...languages])].map((l) => (
          <option key={l}>{l}</option>
        ))}
      </select>
    </label>
  );
}
