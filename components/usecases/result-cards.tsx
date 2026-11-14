'use client';

import { type ReactNode } from 'react';
import { type VoiceResult } from '@/components/voice/state';
import { type PublicUseCase } from '@/lib/usecase-config';
import { parseStudyPlan } from './education/study-plan';
import { StudyPlanCard } from './education/study-plan-card';

// Trusted application registration, not downloaded code or a voice-shell switch.
const renderers: Record<string, (result: VoiceResult) => ReactNode> = {
  study_plan: (result) => {
    const plan = parseStudyPlan(result.data);
    return plan ? <StudyPlanCard plan={plan} /> : null;
  },
};
export function renderUseCaseResult(result: VoiceResult, config: PublicUseCase) {
  if (!result.cardType || !config.result_card_types.includes(result.cardType)) return null;
  return Object.hasOwn(renderers, result.cardType) ? renderers[result.cardType](result) : null;
}
