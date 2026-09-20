import { useEffect, useState } from 'react';
import { ApiError, listStrategyTemplates } from '../api/client';
import type { CatalogModel, StrategyTemplate } from '../api/types';
import { withExecutionDefaults } from '../api/types';
import { defaultValues } from '../workbench/paramSpec';
import { emptyDraft, findModel, nextComponentId } from './strategyModel';
import type { Draft, DraftComponent } from './strategyModel';

/**
 * The onboarding path: complete starter strategies, one click each.
 *
 * They come from `GET /strategy-templates`, not from a table in this file.
 * Only the registry knows which rules a deployment actually has, so a
 * hardcoded template could name a rule that is not registered and would fail
 * on save with nothing useful to say; and a template's parameters have to
 * match the rule's declared ones, which is knowledge that belongs next to the
 * rule (Constitution II).
 *
 * What stays here is the guard: the server's template is still checked against
 * the live catalogue before it is loaded, because the two can disagree — a
 * rule can be unregistered in one deployment and not another — and a component
 * pointing at a missing rule is better dropped loudly than carried silently.
 */

export type LoadStatus = 'loading' | 'ready' | 'error';

export interface TemplateCatalogue {
  items: StrategyTemplate[];
  status: LoadStatus;
  error: string | null;
  reload: () => void;
}

export function useStrategyTemplates(): TemplateCatalogue {
  const [items, setItems] = useState<StrategyTemplate[]>([]);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    listStrategyTemplates()
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setError(null);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(caught instanceof ApiError ? caught.message : 'could not load the templates');
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  return { items, status, error, reload: () => setNonce((value) => value + 1) };
}

export interface LoadedTemplate {
  draft: Draft;
  /** Components the template asked for that this registry cannot provide. */
  missing: string[];
}

/**
 * Build an editable draft from a server template, against the live registry.
 *
 * A rule the registry does not have is reported rather than faked: the user
 * gets the rest of the strategy plus an honest note about what was left out,
 * which is far more useful than a component that will be rejected on save.
 */
export function templateToDraft(
  template: StrategyTemplate,
  catalog: CatalogModel[],
): LoadedTemplate {
  const missing: string[] = [];
  const components: DraftComponent[] = [];

  for (const wanted of template.components) {
    const model = findModel(catalog, wanted.rule_name);
    if (!model) {
      missing.push(wanted.rule_name);
      continue;
    }
    if (!model.roles.includes(wanted.role)) {
      // The registry is authoritative about what a rule can do, not the
      // template — so this drops the component rather than overriding roles.
      missing.push(`${wanted.rule_name} (cannot act as ${wanted.role})`);
      continue;
    }

    // Declared defaults first, then the template's values for the parameters
    // this rule actually declares. A value for a parameter the rule does not
    // have would be uneditable on the form and meaningless to the engine.
    const values = defaultValues(model.parameters);
    for (const spec of model.parameters) {
      const suggested = wanted.parameters?.[spec.name];
      if (suggested !== undefined && suggested !== null) values[spec.name] = String(suggested);
    }

    components.push({
      id: nextComponentId(),
      rule_name: model.name,
      // Templates leave the version null, which means "the latest registered".
      rule_version: wanted.rule_version ?? model.version,
      role: wanted.role,
      weight: wanted.weight ?? 1,
      invert: wanted.invert ?? false,
      values,
    });
  }

  const draft: Draft = {
    ...emptyDraft(template.name),
    // Never the template's id: loading one starts an unsaved strategy, and
    // carrying the id through would make the first Save try to replace a
    // template that is not the caller's to replace.
    id: null,
    description: template.description ?? '',
    components,
    entry_logic: template.entry_logic,
    exit_logic: template.exit_logic,
    entry_threshold: template.entry_threshold ?? 1,
    exit_threshold: template.exit_threshold ?? 1,
    combine_window_days: template.combine_window_days,
    execution: withExecutionDefaults(template.execution),
  };

  return { draft, missing };
}
