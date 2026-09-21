import { Hourglass, ServerCrash, Wrench } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '../../components/ui/button';
import { EmptyState } from '../../components/ui/empty-state';
import { Input, Label, Select } from '../../components/ui/field';
import { StatusBadge } from '../../components/ui/status-badge';
import {
  createCustomRule,
  listSignalTemplates,
  updateCustomRule,
  type CustomRule,
  type SignalTemplate,
} from '../data/customRules';
import {
  asChoices,
  asNumber,
  buildConfig,
  configErrors,
  describeRule,
  formStateFromConfig,
  initialFormState,
  isInputField,
  isOperandField,
  OPERAND_PARAMS,
  type FormState,
  type InputState,
  type OperandState,
} from '../../workbench/templateSpec';

const labelClasses = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

type Templates =
  | { status: 'loading' }
  | { status: 'ready'; items: SignalTemplate[] }
  | { status: 'error'; message: string };

function useSignalTemplates(): Templates & { retry: () => void } {
  const [state, setState] = useState<Templates>({ status: 'loading' });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    listSignalTemplates()
      .then((result) => {
        if (!cancelled) setState({ status: 'ready', items: result.items });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: 'error',
            message: error instanceof Error ? error.message : 'could not load the templates',
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  return { ...state, retry: () => setNonce((n) => n + 1) };
}

function FieldError({ id, message }: { id: string; message: string }) {
  return (
    <p id={id} role="alert" className="text-[10px] text-destructive">
      {message}
    </p>
  );
}

/** The per-kind parameter inputs shared by the input composite and the two
 *  crossover operands, from the template contract's parameter vocabulary. */
function ParamInputs({
  kind,
  params,
  errors,
  keyPrefix,
  onChange,
}: {
  kind: string;
  params: Record<string, string>;
  errors: Record<string, string>;
  keyPrefix: string;
  onChange: (name: string, value: string) => void;
}) {
  return (
    <>
      {(OPERAND_PARAMS[kind] ?? []).map((spec) => {
        const key = `${keyPrefix}.${spec.name}`;
        const error = errors[key];
        return (
          <div key={spec.name} className="space-y-1">
            <Label>
              <span>
                <span className="font-mono">{spec.name}</span>
                <span className="ml-2 font-sans text-[10px] normal-case tracking-normal text-muted-foreground">
                  {spec.minimum}–{spec.maximum}
                </span>
              </span>
              <Input
                type="number"
                value={params[spec.name] ?? ''}
                min={spec.minimum}
                max={spec.maximum}
                step={spec.type === 'float' ? 'any' : '1'}
                aria-invalid={Boolean(error)}
                onChange={(event) => onChange(spec.name, event.target.value)}
              />
            </Label>
            {error ? (
              <FieldError id={`rule-${key}-error`} message={`${spec.name}: ${error}`} />
            ) : null}
          </div>
        );
      })}
    </>
  );
}

/**
 * The custom-rule builder: pick a template, fill the config form its
 * `config_fields` generate, read the plain-English preview, name it, save.
 * With `rule` set it edits instead — the template is fixed at creation, so
 * only name and config are on the table (the backend snapshots the result for
 * future runs; old runs keep theirs).
 */
export function RuleBuilder({
  rule = null,
  onClose,
  onSaved,
}: {
  /** Set when editing an existing rule; null builds a new one. */
  rule?: CustomRule | null;
  onClose: () => void;
  onSaved: (rule: CustomRule) => void;
}) {
  const templates = useSignalTemplates();
  const [templateId, setTemplateId] = useState<string | null>(rule?.template ?? null);
  const [form, setForm] = useState<FormState>({});
  const [name, setName] = useState(rule?.name ?? '');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const template =
    templates.status === 'ready'
      ? (templates.items.find((item) => item.id === templateId) ?? null)
      : null;

  // (Re)seed the form when the template changes or an edit target loads.
  useEffect(() => {
    if (!template) return;
    setForm(
      rule && rule.template === template.id
        ? formStateFromConfig(template, rule.config)
        : initialFormState(template),
    );
    // Seeding is keyed on identity, not on every edit of the rule prop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template]);

  const errors = useMemo(() => (template ? configErrors(template, form) : {}), [template, form]);
  const config = useMemo(() => (template ? buildConfig(template, form) : {}), [template, form]);
  const preview = useMemo(
    () => (template ? describeRule(template.id, config) : ''),
    [template, config],
  );

  const blocked =
    saving || Object.keys(errors).length > 0 || name.trim() === '' || template === null;

  const update = (key: string, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (blocked || !template) return;
    setSaving(true);
    setSaveError(null);
    try {
      const saved =
        rule === null
          ? await createCustomRule({ name: name.trim(), template: template.id, config })
          : await updateCustomRule(rule.rule_id, { name: name.trim(), config });
      onSaved(saved);
    } catch (caught: unknown) {
      setSaveError(caught instanceof Error ? caught.message : 'the rule could not be saved');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(event) => void save(event)} className="space-y-4" data-testid="rule-builder">
      {templates.status === 'error' ? (
        <EmptyState
          testId="rule-templates-error"
          icon={ServerCrash}
          tone="error"
          title="Templates unavailable"
          detail={templates.message}
          action={
            <Button type="button" variant="outline" size="sm" onClick={templates.retry}>
              Retry
            </Button>
          }
        />
      ) : templates.status !== 'ready' ? (
        <EmptyState icon={Hourglass} title="Loading templates…" role="status" />
      ) : templates.items.length === 0 ? (
        <EmptyState
          testId="rule-templates-empty"
          icon={Wrench}
          title="No templates registered"
          detail="The backend ships no signal templates, so there is nothing to build from."
        />
      ) : (
        <>
          <div className="space-y-1">
            <Label htmlFor="rule-template">
              <span>Template</span>
            </Label>
            <Select
              id="rule-template"
              value={templateId ?? ''}
              disabled={rule !== null}
              title={rule !== null ? 'A rule’s template is fixed at creation.' : undefined}
              onChange={(event) => setTemplateId(event.target.value || null)}
            >
              {templateId === null ? <option value="">Choose a template…</option> : null}
              {templates.items.map((item) => (
                <option
                  key={`${item.id}@${item.version}`}
                  value={item.id}
                  disabled={!item.available_on_dataset}
                >
                  {item.id} v{item.version}
                  {item.available_on_dataset ? '' : ' — not on this dataset'}
                </option>
              ))}
            </Select>
            {template ? (
              <p className="text-[10px] text-muted-foreground">{template.description}</p>
            ) : null}
            {template && !template.available_on_dataset ? (
              <StatusBadge
                tone="disabled"
                title="The active dataset cannot serve this template’s inputs."
              >
                Not on this dataset
              </StatusBadge>
            ) : null}
          </div>

          {template ? (
            <fieldset className="space-y-2 border-t border-border pt-3" data-testid="rule-config">
              <legend className={labelClasses}>Config</legend>
              {Object.entries(template.config_fields).map(([key, field]) => {
                const value = form[key];
                const choices = asChoices(field);
                const number = asNumber(field);

                if (
                  isInputField(field) &&
                  value &&
                  typeof value === 'object' &&
                  'source' in value
                ) {
                  const input = value as InputState;
                  return (
                    <div key={key} className="space-y-2 rounded-sm border border-border p-2">
                      <Label>
                        <span>Input series</span>
                        <Select
                          aria-label="Input source"
                          value={input.source}
                          onChange={(event) =>
                            setForm((current) => ({
                              ...current,
                              [key]: { ...input, source: event.target.value },
                            }))
                          }
                        >
                          {field.sources.map((source) => (
                            <option key={source} value={source}>
                              {source === 'close' ? 'Close price' : 'Indicator'}
                            </option>
                          ))}
                        </Select>
                      </Label>
                      {input.source === 'indicator' ? (
                        <>
                          <Label>
                            <span>Indicator</span>
                            <Select
                              aria-label="Indicator"
                              value={input.indicator}
                              onChange={(event) => {
                                const indicator = event.target.value;
                                setForm((current) => ({
                                  ...current,
                                  [key]: {
                                    ...input,
                                    indicator,
                                    params: Object.fromEntries(
                                      (OPERAND_PARAMS[indicator] ?? []).map((spec) => [
                                        spec.name,
                                        String(spec.default),
                                      ]),
                                    ),
                                  },
                                }));
                              }}
                            >
                              {field.indicators.map((indicator) => (
                                <option key={indicator} value={indicator}>
                                  {indicator}
                                </option>
                              ))}
                            </Select>
                          </Label>
                          <ParamInputs
                            kind={input.indicator}
                            params={input.params}
                            errors={errors}
                            keyPrefix={key}
                            onChange={(name, next) =>
                              setForm((current) => ({
                                ...current,
                                [key]: { ...input, params: { ...input.params, [name]: next } },
                              }))
                            }
                          />
                        </>
                      ) : null}
                    </div>
                  );
                }

                if (
                  isOperandField(field) &&
                  value &&
                  typeof value === 'object' &&
                  'kind' in value
                ) {
                  const operand = value as OperandState;
                  return (
                    <div key={key} className="space-y-2 rounded-sm border border-border p-2">
                      <Label>
                        <span>Operand {key.toUpperCase()}</span>
                        <Select
                          aria-label={`Operand ${key.toUpperCase()}`}
                          value={operand.kind}
                          onChange={(event) => {
                            const kind = event.target.value;
                            setForm((current) => ({
                              ...current,
                              [key]: {
                                kind,
                                params: Object.fromEntries(
                                  (OPERAND_PARAMS[kind] ?? []).map((spec) => [
                                    spec.name,
                                    String(spec.default),
                                  ]),
                                ),
                              },
                            }));
                          }}
                        >
                          {field.operands.map((kind) => (
                            <option key={kind} value={kind}>
                              {kind}
                            </option>
                          ))}
                        </Select>
                      </Label>
                      <ParamInputs
                        kind={operand.kind}
                        params={operand.params}
                        errors={errors}
                        keyPrefix={key}
                        onChange={(name, next) =>
                          setForm((current) => ({
                            ...current,
                            [key]: { ...operand, params: { ...operand.params, [name]: next } },
                          }))
                        }
                      />
                    </div>
                  );
                }

                // transform_window applies only under pct_change; hide it
                // otherwise rather than validate a field the user cannot see.
                if (key === 'transform_window' && form.transform !== 'pct_change') return null;

                if (choices && typeof value === 'string') {
                  return (
                    <div key={key} className="space-y-1">
                      <Label>
                        <span className="font-mono">{key}</span>
                        <Select
                          aria-label={key}
                          value={value}
                          onChange={(event) => update(key, event.target.value)}
                        >
                          {choices.choices.map((choice) => (
                            <option key={choice} value={choice}>
                              {choice}
                            </option>
                          ))}
                        </Select>
                      </Label>
                    </div>
                  );
                }

                if (number && typeof value === 'string') {
                  const error = errors[key];
                  return (
                    <div key={key} className="space-y-1">
                      <Label>
                        <span>
                          <span className="font-mono">{key}</span>
                          {number.minimum !== undefined ? (
                            <span className="ml-2 font-sans text-[10px] normal-case tracking-normal text-muted-foreground">
                              {number.minimum}–{number.maximum}
                            </span>
                          ) : null}
                        </span>
                        <Input
                          type="number"
                          value={value}
                          min={number.minimum}
                          max={number.maximum}
                          step={number.type === 'float' ? 'any' : '1'}
                          aria-invalid={Boolean(error)}
                          aria-label={key}
                          onChange={(event) => update(key, event.target.value)}
                        />
                      </Label>
                      {error ? (
                        <FieldError id={`rule-${key}-error`} message={`${key}: ${error}`} />
                      ) : null}
                    </div>
                  );
                }

                return null;
              })}
            </fieldset>
          ) : null}

          {template ? (
            <p
              data-testid="rule-preview"
              className="rounded-sm border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-foreground"
            >
              {preview}
            </p>
          ) : null}

          <div className="space-y-1">
            <Label htmlFor="rule-name">
              <span>Name</span>
            </Label>
            <Input
              id="rule-name"
              value={name}
              placeholder="e.g. RSI oversold recovery"
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={blocked} className="px-4">
              {saving ? 'Saving…' : rule === null ? 'Save rule' : 'Save changes'}
            </Button>
          </div>

          {saveError ? (
            <p role="alert" className="text-[11px] text-destructive">
              {saveError}
            </p>
          ) : null}
        </>
      )}
    </form>
  );
}
