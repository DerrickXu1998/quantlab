import { render, screen as dom, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../../../src/api/client';
import { ApiError } from '../../../src/api/client';
import { ScreenView } from '../../../src/research/screen/ScreenView';
import { UNIVERSES, makeScreenResult } from './fixtures';

vi.mock('../../../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return { ...actual, screen: vi.fn(), listUniverses: vi.fn() };
});

const listUniverses = vi.mocked(apiClient.listUniverses);
const runScreen = vi.mocked(apiClient.screen);

function renderScreen(onSelect = vi.fn()) {
  render(<ScreenView onSelectSymbol={onSelect} />);
  return onSelect;
}

/** The universe select only exists once `/universes` has answered. */
async function ready() {
  await dom.findByLabelText('Universe');
}

beforeEach(() => {
  vi.clearAllMocks();
  listUniverses.mockResolvedValue(UNIVERSES);
  runScreen.mockResolvedValue(makeScreenResult());
});

describe('Screen — asking the question', () => {
  it('opens on a named idle state, having asked the warehouse nothing', async () => {
    // A screen is ~1s of index work over 598 names. Landing on a blank table
    // would read as "nothing qualified" before anyone had asked anything.
    renderScreen();
    await ready();

    expect(dom.getByTestId('screen-idle')).toHaveTextContent(/no screen run yet/i);
    expect(runScreen).not.toHaveBeenCalled();
  });

  it('does not run while a constraint is being typed', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();

    await user.click(dom.getByRole('button', { name: /add/i }));
    await user.type(within(dom.getByTestId('constraint-pe')).getByLabelText('Min'), '5');

    expect(runScreen).not.toHaveBeenCalled();
    // And it says so, rather than leaving the user to wonder.
    expect(dom.getByTestId('screen-run-note')).toHaveTextContent(/runs when you ask/i);
  });

  it('sends the constraint in the metric’s own unit when Run is pressed', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();

    await user.click(dom.getByRole('button', { name: /add/i }));
    await user.selectOptions(within(dom.getByTestId('constraint-pe')).getByLabelText('Metric'), 'roe');
    await user.type(within(dom.getByTestId('constraint-roe')).getByLabelText('Min'), '0.15');
    await user.click(dom.getByTestId('run-screen'));

    await waitFor(() => expect(runScreen).toHaveBeenCalledTimes(1));
    expect(runScreen.mock.calls[0][0]).toMatchObject({
      universe: 'liquid-500-ftse-core',
      constraints: [{ metric: 'roe', min: 0.15, max: null }],
    });
  });

  it('will not run an unparseable bound, and marks the row instead', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();

    await user.click(dom.getByRole('button', { name: /add/i }));
    await user.type(within(dom.getByTestId('constraint-pe')).getByLabelText('Min'), 'cheap');

    expect(dom.getByRole('alert')).toHaveTextContent(/must be numbers/i);
    expect(dom.getByTestId('run-screen')).toBeDisabled();
  });
});

describe('Screen — coverage, which is the whole point', () => {
  it('states each metric’s own coverage, and it is not uniform', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));

    // The measured figures: gross profit is filed by 237 names, revenue by
    // 376, net income by 437. A screen that averaged these away would have a
    // gross-margin screen quietly run over 40% of the list.
    const grossMargin = await dom.findByTestId('coverage-gross_margin');
    expect(grossMargin).toHaveTextContent('Gross margin — 237 of 598 names measured');
    expect(dom.getByTestId('coverage-net_margin')).toHaveTextContent(
      'Net margin — 376 of 598 names measured',
    );
    expect(dom.getByTestId('coverage-roe')).toHaveTextContent(
      'ROE — 437 of 598 names measured',
    );
  });

  it('names the filed concepts a metric is built from', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));

    expect(await dom.findByTestId('coverage-gross_margin')).toHaveTextContent(
      /needs gross profit, revenue/i,
    );
  });

  it('shows a constraint’s coverage on the constraint itself', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();

    await user.click(dom.getByRole('button', { name: /add/i }));
    // Before the first run there is no coverage to report, and it says so
    // rather than showing a zero.
    expect(within(dom.getByTestId('constraint-pe')).getByTestId('coverage-pe')).toHaveTextContent(
      /reported once the screen runs/i,
    );

    await user.type(within(dom.getByTestId('constraint-pe')).getByLabelText('Max'), '15');
    await user.click(dom.getByTestId('run-screen'));

    await waitFor(() =>
      expect(within(dom.getByTestId('constraint-pe')).getByTestId('coverage-pe')).toHaveTextContent(
        '425 of 598 names measured',
      ),
    );
  });

  it('reports the two exclusions separately and never as one number', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));

    const failed = await dom.findByTestId('exclusion-constraint');
    const unmeasured = dom.getByTestId('exclusion-unmeasured');

    expect(failed).toHaveTextContent('312');
    expect(failed).toHaveTextContent(/did not qualify/i);
    expect(unmeasured).toHaveTextContent('284');
    expect(unmeasured).toHaveTextContent(/never measured/i);
    // 312 + 284 = 596. If that sum is ever on screen as one figure, a fact
    // about the warehouse has been passed off as a fact about companies.
    expect(dom.queryByText('596')).toBeNull();
  });

  it('explains an empty result with the split, not with "nothing qualified"', async () => {
    runScreen.mockResolvedValue(
      makeScreenResult({ rows: [], excluded_by_constraint: 12, excluded_unmeasured: 586 }),
    );
    const user = userEvent.setup();
    renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));

    const empty = await dom.findByTestId('screen-no-matches');
    expect(empty).toHaveTextContent(/12 were measured and failed/i);
    expect(empty).toHaveTextContent(/586 were never measured at all/i);
    expect(empty).toHaveTextContent(/loosening the bounds only reaches the first group/i);
  });
});

describe('Screen — the table', () => {
  it('formats every figure and renders an unfiled one as a dash, never a zero', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));

    const row = await dom.findByTestId('screen-row-CAT.US');
    // Not `11.6438`, and certainly not 11.643800000000001.
    expect(row).toHaveTextContent('11.6×');
    expect(row).toHaveTextContent('41.2%');
    // Caterpillar never filed gross profit. An em dash, not 0.0%.
    expect(row).toHaveTextContent('—');
    expect(row).not.toHaveTextContent('0.0%');
  });

  it('hands a clicked name to the shell', async () => {
    const user = userEvent.setup();
    const onSelect = renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));

    await user.click(await dom.findByRole('button', { name: 'CAT.US' }));

    expect(onSelect).toHaveBeenCalledWith('CAT.US');
  });

  it('re-ranks on a header click, which is a deliberate act on an existing answer', async () => {
    const user = userEvent.setup();
    renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));
    await dom.findByTestId('screen-table');

    await user.click(dom.getByRole('button', { name: /leverage/i }));

    await waitFor(() => expect(runScreen).toHaveBeenCalledTimes(2));
    expect(runScreen.mock.calls[1][0]).toMatchObject({ sortBy: 'leverage', descending: true });
  });
});

describe('Screen — the four states of a read', () => {
  it('treats a 404 on the universes as unsupported, not as a failure', async () => {
    // The route is being written in parallel. "This deployment does not serve
    // it" is a different sentence from "it broke", and a very different one
    // from "nothing matched".
    listUniverses.mockRejectedValue(new ApiError(404, 'Not Found'));
    renderScreen();

    const state = await dom.findByTestId('screen-unsupported');
    expect(state).toHaveTextContent(/not served here/i);
    expect(state).toHaveTextContent(/nothing is wrong with your filters/i);
    expect(dom.queryByTestId('screen-universes-error')).toBeNull();
  });

  it('treats any other failure as an error, and offers a retry', async () => {
    listUniverses.mockRejectedValue(new ApiError(500, 'boom'));
    renderScreen();

    const state = await dom.findByTestId('screen-universes-error');
    expect(state).toHaveTextContent(/unreachable/i);
    expect(dom.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('separates a backend with no universes from a backend that serves none', async () => {
    listUniverses.mockResolvedValue({ items: [] });
    renderScreen();

    expect(await dom.findByTestId('screen-no-universes')).toHaveTextContent(
      /no universes published/i,
    );
  });

  it('says so when the screen route itself is missing', async () => {
    runScreen.mockRejectedValue(new ApiError(404, 'Not Found'));
    const user = userEvent.setup();
    renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));

    expect(await dom.findByTestId('screen-route-unsupported')).toHaveTextContent(
      /not served here/i,
    );
  });

  it('shows no table at all when the screen fails, rather than an empty one', async () => {
    runScreen.mockRejectedValue(new ApiError(503, 'warehouse down'));
    const user = userEvent.setup();
    renderScreen();
    await ready();
    await user.click(dom.getByTestId('run-screen'));

    const state = await dom.findByTestId('screen-error');
    expect(state).toHaveTextContent(/warehouse down/i);
    expect(state).toHaveTextContent(/an empty table here would read as a result/i);
    expect(dom.queryByTestId('screen-table')).toBeNull();
  });
});
