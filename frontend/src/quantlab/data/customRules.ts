import type { components } from '../../api/schema';
import { apiGet, apiSend } from '../../lib/apiRequest';

/**
 * The custom-rule endpoints (feature 008, M2): the template catalog the rule
 * builder is generated from, and the per-user rules it saves. Lives outside
 * api/client because that directory is regenerated; shapes are read off the
 * generated schema so a contract drift fails typecheck.
 */

export type SignalTemplate = components['schemas']['SignalTemplate'];
export type SignalTemplateList = components['schemas']['SignalTemplateList'];
export type CustomRule = components['schemas']['CustomRule'];
export type CustomRuleList = components['schemas']['CustomRuleList'];
export type CustomRuleRequest = components['schemas']['CustomRuleRequest'];
export type CustomRuleUpdateRequest = components['schemas']['CustomRuleUpdateRequest'];

export function listSignalTemplates(): Promise<SignalTemplateList> {
  return apiGet<SignalTemplateList>('/signal-templates');
}

export function listCustomRules(): Promise<CustomRuleList> {
  return apiGet<CustomRuleList>('/rules');
}

export function createCustomRule(body: CustomRuleRequest): Promise<CustomRule> {
  return apiSend<CustomRule>('/rules', 'POST', body);
}

export function updateCustomRule(
  ruleId: string,
  body: CustomRuleUpdateRequest,
): Promise<CustomRule> {
  return apiSend<CustomRule>(`/rules/${encodeURIComponent(ruleId)}`, 'PATCH', body);
}

export function deleteCustomRule(ruleId: string): Promise<void> {
  return apiSend<void>(`/rules/${encodeURIComponent(ruleId)}`, 'DELETE');
}
