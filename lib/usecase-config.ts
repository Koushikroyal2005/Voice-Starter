// Public display contract only. Provider options, instructions and secrets are absent.
export interface PublicUseCase {
  schema_version: 1;
  id: string;
  name: string;
  description: string;
  languages: string[];
  result_card_types: string[];
  notice: string;
}
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
  if (raw.length > 6000) return null;
  try {
    const v = JSON.parse(raw);
    const identifier = (s: unknown) => typeof s === 'string' && /^[a-z][a-z0-9_]{0,47}$/.test(s);
    if (
      !v ||
      v.schema_version !== 1 ||
      !identifier(v.id) ||
      typeof v.name !== 'string' ||
      !v.name.length ||
      v.name.length > 80 ||
      typeof v.description !== 'string' ||
      !v.description.length ||
      v.description.length > 300 ||
      typeof v.notice !== 'string' ||
      v.notice.length > 400 ||
      !Array.isArray(v.languages) ||
      !v.languages.length ||
      v.languages.length > 10 ||
      !v.languages.every(
        (s: unknown) => typeof s === 'string' && /^[a-zA-Z][a-zA-Z0-9-]{0,23}$/.test(s)
      ) ||
      !Array.isArray(v.result_card_types) ||
      !v.result_card_types.length ||
      v.result_card_types.length > 10 ||
      !v.result_card_types.every(identifier)
    )
      return null;
    // Select fields explicitly; never spread an untrusted RPC response into props.
    return {
      schema_version: 1,
      id: v.id,
      name: v.name,
      description: v.description,
      languages: v.languages,
      result_card_types: v.result_card_types,
      notice: v.notice,
    };
  } catch {
    return null;
  }
}
