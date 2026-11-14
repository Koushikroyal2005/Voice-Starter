'use client';

import { useTheme } from 'next-themes';
import { useReducedMotion } from 'motion/react';
import { type TrackReferenceOrPlaceholder } from '@livekit/components-react';
import { AgentAudioVisualizerAura } from '@/components/agents-ui/agent-audio-visualizer-aura';
import { AgentAudioVisualizerBar } from '@/components/agents-ui/agent-audio-visualizer-bar';
import { AgentAudioVisualizerGrid } from '@/components/agents-ui/agent-audio-visualizer-grid';
import { AgentAudioVisualizerRadial } from '@/components/agents-ui/agent-audio-visualizer-radial';
import { AgentAudioVisualizerWave } from '@/components/agents-ui/agent-audio-visualizer-wave';

export const visualizerTypes = ['aura', 'bar', 'grid', 'radial', 'wave'] as const;
export type VisualizerType = (typeof visualizerTypes)[number];
export function AudioVisualizer({
  track,
  type = 'bar',
  label,
}: {
  track?: TrackReferenceOrPlaceholder;
  type?: VisualizerType;
  label: string;
}) {
  const { resolvedTheme } = useTheme();
  const reduceMotion = useReducedMotion();
  if (reduceMotion) type = 'bar'; // Energy meter only; avoid moving shader fields.
  const active = !!track?.publication?.track && !track.publication.isMuted;
  // Always use the audio-driven branch, never a state-based synthetic loader.
  const props = {
    audioTrack: active ? track : undefined,
    state: 'speaking' as const,
    color: '#14b8a6' as const,
  };
  return (
    <div
      role="img"
      aria-label={`${label}: ${active ? 'live audio level' : 'no active audio track'}`}
      className="flex h-64 w-full items-center justify-center overflow-hidden motion-reduce:[&_*]:!transition-none"
    >
      {!active ? (
        <div className="bg-muted-foreground/25 h-px w-40" />
      ) : type === 'aura' ? (
        <AgentAudioVisualizerAura
          {...props}
          themeMode={resolvedTheme === 'dark' ? 'dark' : 'light'}
          className="size-64"
        />
      ) : type === 'wave' ? (
        <AgentAudioVisualizerWave {...props} className="size-64" />
      ) : type === 'grid' ? (
        <AgentAudioVisualizerGrid
          {...props}
          rowCount={9}
          columnCount={9}
          className="size-56 gap-1"
        />
      ) : type === 'radial' ? (
        <AgentAudioVisualizerRadial {...props} barCount={32} radius={65} className="size-64" />
      ) : (
        <AgentAudioVisualizerBar {...props} barCount={15} className="h-28 w-56 gap-2" />
      )}
    </div>
  );
}
