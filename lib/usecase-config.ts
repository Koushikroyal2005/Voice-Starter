// Public display contract only. Provider options, instructions and secrets are absent.
import { type PublicUseCase, parsePublicUseCase } from './workbench/contracts';

export type { PublicUseCase } from './workbench/contracts';
export const DEFAULT_USE_CASE: PublicUseCase = {
  schema_version: 1,
  id: 'general_assistant',
  name: 'Voice Workbench',
  description: 'A foundation for real conversations',
  languages: ['en'],
  result_card_types: ['text'],
  notice: '',
};
export function parseUseCaseConfig(raw: string): PublicUseCase | null {
  return parsePublicUseCase(raw);
}
