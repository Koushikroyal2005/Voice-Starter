'use client';

import { useState } from 'react';
import { AudioLines } from 'lucide-react';
import { ThemeToggle } from '@/components/app/theme-toggle';
import { AudioVisualizer, type VisualizerType, visualizerTypes } from './audio-visualizer';
import {
  AgentStatus,
  ConnectionStatus,
  ConversationTimeline,
  LanguageSelector,
  LiveTranscript,
} from './panels';
import { useVoiceWorkbench } from './use-voice-workbench';
import { VoiceControls } from './voice-controls';

export function VoiceWorkbench() {
  const voice = useVoiceWorkbench();
  const [visualizer, setVisualizer] = useState<VisualizerType>('bar');
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-8">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b pb-6">
        <div className="flex items-center gap-3">
          <span className="rounded-xl bg-teal-600 p-2.5 text-white">
            <AudioLines aria-hidden className="size-5" />
          </span>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Voice Workbench</h1>
            <p className="text-muted-foreground text-xs">A foundation for real conversations</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <ConnectionStatus state={voice.session.connectionState} />
          <ThemeToggle className="w-auto" />
        </div>
      </header>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-muted-foreground text-xs font-medium tracking-widest uppercase">
            Workspace / Live session
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">Let’s talk.</h2>
        </div>
        <LanguageSelector value={voice.agent.attributes['voice.language'] || 'Worker default'} />
      </div>
      {voice.control.error || voice.agent.state === 'failed' ? (
        <div
          role="alert"
          className="border-destructive/40 bg-destructive/5 mb-5 rounded-xl border p-4 text-sm"
        >
          {voice.control.error ||
            'Agent unavailable. Confirm the Python worker is running with the matching dispatch name.'}
        </div>
      ) : null}
      <div className="grid items-stretch gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <section
          aria-label="Voice interaction"
          className="bg-card min-w-0 rounded-2xl border p-5 sm:p-8"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-muted-foreground text-xs font-medium">AGENT OUTPUT</span>
            <label className="text-muted-foreground text-xs">
              Visualizer
              <select
                aria-label="Audio visualizer"
                className="bg-background text-foreground ml-2 rounded-md border p-2 capitalize"
                value={visualizer}
                onChange={(e) => setVisualizer(e.target.value as VisualizerType)}
              >
                {visualizerTypes.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
          </div>
          <AudioVisualizer
            label="Agent output"
            track={voice.agent.microphoneTrack}
            type={visualizer}
          />
          <AgentStatus state={voice.state} connected={voice.session.isConnected} />
          <div className="mt-8">
            <VoiceControls voice={voice} />
          </div>
          <div className="mt-6 flex items-center gap-4 border-t pt-4">
            <span className="text-muted-foreground shrink-0 text-xs">MIC INPUT</span>
            <div className="h-10 flex-1 overflow-hidden [&>div]:h-10 [&>div>div]:max-h-8">
              <AudioVisualizer
                label="Microphone input"
                track={voice.session.local.microphoneTrack}
                type="bar"
              />
            </div>
            <span className="text-muted-foreground text-xs">
              {voice.session.local.microphoneTrack?.publication?.isMuted
                ? 'Muted'
                : voice.session.local.microphoneTrack?.publication?.track
                  ? 'Live'
                  : 'Off'}
            </span>
          </div>
        </section>
        <LiveTranscript messages={voice.messages} agentState={voice.agent.state} />
      </div>
      <div className="mt-5">
        <ConversationTimeline
          entries={voice.entries}
          tools={voice.tools}
          results={voice.results}
          onConfirm={voice.confirmTool}
        />
      </div>
      <footer className="text-muted-foreground mt-6 flex flex-wrap justify-between gap-2 text-xs">
        <span>LiveKit audio · No simulated activity</span>
        <span>Tab to navigate · Escape to interrupt · Enter to send text</span>
      </footer>
    </div>
  );
}
