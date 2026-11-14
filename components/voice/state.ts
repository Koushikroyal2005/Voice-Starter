export type VoiceState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'executing'
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
}
export function deriveVoiceState(s: Snapshot): VoiceState {
  if (s.command === 'ending') return 'disconnecting';
  if (s.connection === 'reconnecting' || s.connection === 'signalReconnecting')
    return 'reconnecting';
  if (s.error || s.agent === 'failed') return 'error';
  if (s.command === 'starting' || s.connection === 'connecting') return 'connecting';
  if (s.connection !== 'connected') return 'idle';
  if (s.interrupted) return 'interrupted';
  if (s.executing) return 'executing';
  if (s.agent === 'idle') return 'idle';
  if (s.agent === 'speaking' || s.agent === 'thinking' || s.agent === 'listening') return s.agent;
  return 'connecting';
}
export interface ToolActivity {
  id: string;
  name: string;
  status: 'running' | 'done' | 'error' | 'cancelled';
}
export interface VoiceResult {
  id: string;
  title: string;
  text: string;
}
export type WorkerEvent =
  | { type: 'interrupted' }
  | { type: 'tool'; tool: ToolActivity }
  | { type: 'result'; result: VoiceResult };
// Caller must also authenticate the packet's participant against the connected agent.
export function parseWorkerEvent(raw: string): WorkerEvent | null {
  if (raw.length > 16384) return null;
  try {
    const v = JSON.parse(raw);
    if (!v || typeof v !== 'object') return null;
    if (v.type === 'interrupted') return { type: 'interrupted' };
    if (
      v.type === 'tool' &&
      typeof v.id === 'string' &&
      v.id.length <= 200 &&
      typeof v.name === 'string' &&
      v.name.length <= 200 &&
      ['running', 'done', 'error', 'cancelled'].includes(v.status)
    )
      return { type: 'tool', tool: { id: v.id, name: v.name, status: v.status } };
    if (
      v.type === 'result' &&
      typeof v.id === 'string' &&
      typeof v.title === 'string' &&
      typeof v.text === 'string' &&
      v.title.length <= 200
    )
      return { type: 'result', result: { id: v.id.slice(0, 200), title: v.title, text: v.text } };
  } catch {
    /* Ignore invalid or unrelated room data. */
  }
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
