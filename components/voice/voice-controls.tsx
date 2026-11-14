'use client';

import { useEffect, useState } from 'react';
import { MessageSquare, Mic, PhoneOff, Square } from 'lucide-react';
import { AgentControlBar } from '@/components/agents-ui/agent-control-bar';
import { Button } from '@/components/ui/button';
import { type useVoiceWorkbench } from './use-voice-workbench';

export function VoiceControls({ voice }: { voice: ReturnType<typeof useVoiceWorkbench> }) {
  const [chatOpen, setChatOpen] = useState(false);
  const { session, agent, control, start, end, interrupt, reportError } = voice;
  const busy = control.command !== 'idle';
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.key === 'Escape' &&
        !e.defaultPrevented &&
        session.isConnected &&
        !busy &&
        agent.isConnected
      ) {
        e.preventDefault();
        void interrupt();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [session.isConnected, busy, agent.isConnected, interrupt]);
  return (
    <div className="w-full space-y-4 [&_button]:min-h-11 [&_button]:min-w-11">
      {!session.isConnected ? (
        <div className="flex flex-wrap justify-center gap-3">
          <Button
            size="lg"
            disabled={busy}
            onClick={() => {
              setChatOpen(false);
              void start();
            }}
          >
            <Mic className="size-4" />
            {busy ? 'Connecting…' : 'Start voice session'}
          </Button>
          <Button
            size="lg"
            variant="outline"
            disabled={busy}
            onClick={() => {
              setChatOpen(true);
              void start(true);
            }}
          >
            <MessageSquare className="size-4" />
            Connect with text
          </Button>
          {control.command === 'starting' && (
            <Button variant="ghost" onClick={voice.cancelStart}>
              Cancel connection
            </Button>
          )}
        </div>
      ) : (
        <>
          <AgentControlBar
            isConnected={session.isConnected}
            controls={{
              microphone: true,
              chat: true,
              camera: false,
              screenShare: false,
              leave: false,
            }}
            isChatOpen={chatOpen}
            onIsChatOpenChange={setChatOpen}
            onDeviceError={({ error }) => reportError(error)}
          />
          <div className="flex flex-wrap justify-center gap-3">
            <Button
              variant="outline"
              disabled={busy || !agent.isConnected || voice.state === 'reconnecting'}
              onClick={() => void interrupt()}
              title="Interrupt agent (Escape)"
            >
              <Square className="size-4" />
              {control.command === 'interrupting' ? 'Stopping…' : 'Interrupt'}
              <kbd className="text-muted-foreground hidden text-xs sm:inline">Esc</kbd>
            </Button>
            <Button
              variant="destructive"
              disabled={busy && control.command !== 'starting'}
              onClick={() => (control.command === 'starting' ? voice.cancelStart() : void end())}
            >
              <PhoneOff className="size-4" />
              End session
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
