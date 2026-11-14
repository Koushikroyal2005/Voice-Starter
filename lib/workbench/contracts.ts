// Runtime validation is generated from contracts/voice-workbench/v1, not these mappings.
import type { PublicUseCase, WorkbenchEvent, WorkbenchRpc } from './generated/types';
import {
  validateAccepted,
  validateCardType,
  validateConfirmationRequest,
  validateEmptyRequest,
  validateEvent,
  validateInterrupted,
  validatePublicUseCase,
  validateResultData,
  validateToolsState,
} from './generated/validators.cjs';

export type { PublicUseCase, ToolEvent, ResultEvent, WorkbenchRpc } from './generated/types';
export { WORKBENCH_TOPIC } from './generated/types';

const methods = {
  'voice.interrupt': { request: validateEmptyRequest, response: validateInterrupted },
  'voice.confirm_tool': { request: validateConfirmationRequest, response: validateAccepted },
  'voice.tools_state': { request: validateEmptyRequest, response: validateToolsState },
  'voice.usecase_config': { request: validateEmptyRequest, response: validatePublicUseCase },
} satisfies Record<
  WorkbenchRpc['method'],
  { request: (v: unknown) => boolean; response: (v: unknown) => boolean }
>;

export function encodeRpcRequest<M extends WorkbenchRpc['method']>(
  method: M,
  value: Extract<WorkbenchRpc, { method: M }>['request']
): string {
  if (!Object.hasOwn(methods, method) || !methods[method].request(value))
    throw new Error('Invalid workbench request.');
  const raw = JSON.stringify(value);
  if (raw.length > (method === 'voice.confirm_tool' ? 512 : 16384))
    throw new Error('Invalid workbench request.');
  return raw;
}

export function parseRpcResponse<M extends WorkbenchRpc['method']>(
  method: M,
  raw: string
): Extract<WorkbenchRpc, { method: M }>['response'] | null {
  if (!Object.hasOwn(methods, method) || raw.length > 16384) return null;
  try {
    const value = JSON.parse(raw);
    return methods[method].response(value) ? value : null;
  } catch {
    return null;
  }
}

export function parsePublicUseCase(raw: string): PublicUseCase | null {
  if (raw.length > 6000) return null;
  try {
    const v = JSON.parse(raw);
    if (!v || typeof v !== 'object') return null;
    // Retain the existing allowlisted projection; never spread an RPC response.
    const selected = {
      schema_version: v.schema_version,
      id: v.id,
      name: v.name,
      description: v.description,
      languages: v.languages,
      result_card_types: v.result_card_types,
      notice: v.notice,
    };
    return validatePublicUseCase(selected) ? (selected as PublicUseCase) : null;
  } catch {
    return null;
  }
}

export function parseWireEvent(raw: string): WorkbenchEvent | null {
  if (raw.length > 16384) return null;
  try {
    const v = JSON.parse(raw);
    if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
    // Compatibility projection: drop unknown fields and keep error copy local.
    let selected;
    switch (v.type) {
      case 'tool':
        selected = {
          type: v.type,
          id: v.id,
          name: v.name,
          status: v.status,
          description: v.description,
          revision: v.revision,
          ...(v.status === 'confirmation_required' ? { confirmation_id: v.confirmation_id } : {}),
        };
        break;
      case 'result':
        selected = {
          type: v.type,
          id: typeof v.id === 'string' ? v.id.slice(0, 200) : v.id,
          title: v.title,
          text: v.text,
          ...(validateCardType(v.card_type) ? { card_type: v.card_type } : {}),
          ...(validateResultData(v.data) ? { data: v.data } : {}),
        };
        break;
      case 'error':
        selected = { type: v.type, code: v.code };
        break;
      case 'interrupted':
        selected = { type: v.type };
        break;
      default:
        return null;
    }
    return validateEvent(selected) ? (selected as WorkbenchEvent) : null;
  } catch {
    return null;
  }
}
