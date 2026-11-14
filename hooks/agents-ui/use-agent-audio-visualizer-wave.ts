import { type LocalAudioTrack, type RemoteAudioTrack } from 'livekit-client';
import {
  type AgentState,
  type TrackReference,
  type TrackReferenceOrPlaceholder,
  useTrackVolume,
} from '@livekit/components-react';

/** A stylized energy visualization, not a PCM waveform or a state-based loader. */
export function useAgentAudioVisualizerWave({
  state,
  audioTrack,
  volume: volumeProp,
}: {
  state?: AgentState;
  audioTrack?: LocalAudioTrack | RemoteAudioTrack | TrackReferenceOrPlaceholder;
  volume?: number;
}) {
  const measured = useTrackVolume(audioTrack as TrackReference, {
    fftSize: 512,
    smoothingTimeConstant: 0.55,
  });
  const volume =
    state === 'disconnected' || (!audioTrack && volumeProp === undefined)
      ? 0
      : Math.max(0, Math.min(1, volumeProp ?? measured));
  return { speed: volume * 10, amplitude: volume * 0.4, frequency: 20 + volume * 60, opacity: 1 };
}
