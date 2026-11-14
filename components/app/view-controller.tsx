'use client';

import { renderUseCaseResult } from '@/components/usecases/result-cards';
import { VoiceWorkbench } from '@/components/voice/voice-workbench';

// Retain the app boundary; the reusable voice shell contains no domain logic.
export function ViewController(_props: { isVideoInputSupported: boolean }) {
  void _props; // Retained for compatibility with the existing app boundary.
  return <VoiceWorkbench renderResult={renderUseCaseResult} />;
}
