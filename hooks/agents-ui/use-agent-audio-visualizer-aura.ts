import { type LocalAudioTrack, type RemoteAudioTrack } from 'livekit-client';
import {
  type AgentState,
  type TrackReference,
  type TrackReferenceOrPlaceholder,
  useTrackVolume,
} from '@livekit/components-react';

/** Stylized shader driven by measured track energy, not by session-state pulses. */
export function useAgentAudioVisualizerAura(
  state: AgentState | undefined,
  audioTrack?: LocalAudioTrack | RemoteAudioTrack | TrackReferenceOrPlaceholder,
  volumeProp?: number
) {
  const measured = useTrackVolume(audioTrack as TrackReference, {
    fftSize: 512,
    smoothingTimeConstant: 0.55,
  });
  const volume =
    state === 'disconnected' || (!audioTrack && volumeProp === undefined)
      ? 0
      : Math.max(0, Math.min(1, volumeProp ?? measured));
  return {
    speed: volume * 70,
    scale: 0.2 + volume * 0.2,
    amplitude: volume * 2,
    frequency: 0.5 + volume,
    brightness: 1 + volume,
  };
}
