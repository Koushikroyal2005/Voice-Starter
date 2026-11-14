import { type ResultEvent, type ToolEvent, parseWireEvent } from '@/lib/workbench/contracts';

export type VoiceState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'executing'
  | 'confirmation_required'
  | 'speaking'
  | 'interrupted'
  | 'reconnecting'
  | 'error'
  | 'disconnecting';
export type Command = 'idle' | 'starting' | 'ending' | 'interrupting';
export interface Snapshot {
  connection: string;
  agent: string;
  command: Command;
  error: string | null;
  interrupted: boolean;
  executing: boolean;
  awaitingConfirmation?: boolean;
}
export function deriveVoiceState(s: Snapshot): VoiceState {
  if (s.command === 'ending') return 'disconnecting';
  if (s.connection === 'reconnecting' || s.connection === 'signalReconnecting')
    return 'reconnecting';
  if (s.error || s.agent === 'failed') return 'error';
  if (s.command === 'starting' || s.connection === 'connecting') return 'connecting';
  if (s.connection !== 'connected') return 'idle';
  if (s.interrupted) return 'interrupted';
  if (s.awaitingConfirmation) return 'confirmation_required';
  if (s.executing) return 'executing';
  if (s.agent === 'idle') return 'idle';
  if (s.agent === 'speaking' || s.agent === 'thinking' || s.agent === 'listening') return s.agent;
  return 'connecting';
}
// UI view models derive wire fields; camelCase/history are local presentation.
export type ToolActivity = Pick<
  ToolEvent,
  'id' | 'name' | 'status' | 'description' | 'revision'
> & {
  confirmationId?: ToolEvent['confirmation_id'];
  phases?: string[];
};
export type VoiceResult = Pick<ResultEvent, 'id' | 'title' | 'text' | 'data'> & {
  cardType?: ResultEvent['card_type'];
};
export function mergeToolActivities(
  previous: ToolActivity[],
  incoming: ToolActivity
): ToolActivity[] {
  const old = previous.find((t) => t.id === incoming.id);
  if (
    old?.revision !== undefined &&
    (incoming.revision === undefined || incoming.revision < old.revision)
  )
    return previous;
  const phases = old?.phases ?? [];
  const next = {
    ...incoming,
    phases: phases.at(-1) === incoming.status ? phases : [...phases, incoming.status].slice(-8),
  };
  return [...previous.filter((t) => t.id !== next.id), next].slice(-30);
}
export type WorkerEvent =
  | { type: 'error'; message: string }
  | { type: 'interrupted' }
  | { type: 'tool'; tool: ToolActivity }
  | { type: 'result'; result: VoiceResult };
// Caller must also authenticate the packet's participant against the connected agent.
export function parseWorkerEvent(raw: string): WorkerEvent | null {
  const v = parseWireEvent(raw);
  if (!v) return null;
  if (v.type === 'interrupted') return { type: 'interrupted' };
  if (v.type === 'error' && v.code === 'provider_unavailable')
    return {
      type: 'error',
      message:
        'A voice service is unavailable. Try again shortly, or reconnect if the session has ended.',
    };
  if (v.type === 'error' && v.code === 'transcription_timeout')
    return {
      type: 'error',
      message:
        'No speech transcript was received. Check your microphone, try again, or use text input.',
    };
  if (v.type === 'tool')
    return {
      type: 'tool',
      tool: {
        id: v.id,
        name: v.name,
        status: v.status,
        description: v.description,
        revision: v.revision,
        confirmationId: v.status === 'confirmation_required' ? v.confirmation_id : undefined,
      },
    };
  if (v.type === 'result')
    return {
      type: 'result',
      result: {
        id: v.id,
        title: v.title,
        text: v.text,
        cardType: v.card_type,
        data: v.data,
      },
    };
  return null;
}
export function mediaErrorMessage(error: unknown): string {
  const name = error instanceof Error ? error.name : '';
  if (['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(name))
    return 'Microphone access denied. Allow microphone access in your browser, or connect using text.';
  if (['NotFoundError', 'DevicesNotFoundError'].includes(name))
    return 'No microphone found. Connect a microphone or use text instead.';
  if (['NotReadableError', 'TrackStartError'].includes(name))
    return 'Microphone is unavailable. Close other apps using it, select another device, or use text.';
  return 'Connection or browser audio failed. Check your network, server configuration and Python worker, then retry. Text mode does not require a microphone.';
}
