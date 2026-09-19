import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  LAYOUT_STORAGE_KEY,
  LAYOUT_VERSION,
  clearLayout,
  loadLayout,
  saveLayout,
} from '../src/workspace/layoutStorage';

const someLayout = { grid: { root: { type: 'branch' } }, panels: { chart: {} } };

describe('layoutStorage', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('round-trips a saved layout', () => {
    saveLayout(someLayout);

    const loaded = loadLayout();
    expect(loaded).not.toBeNull();
    expect(loaded!.version).toBe(LAYOUT_VERSION);
    expect(loaded!.layout).toEqual(someLayout);
  });

  it('returns null when nothing has been saved', () => {
    expect(loadLayout()).toBeNull();
  });

  it('returns null — never throws — for unparseable JSON', () => {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, '{not valid json');

    expect(() => loadLayout()).not.toThrow();
    expect(loadLayout()).toBeNull();
  });

  it('returns null for a record with a missing or unknown version', () => {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify({ layout: someLayout }));
    expect(loadLayout()).toBeNull();

    window.localStorage.setItem(
      LAYOUT_STORAGE_KEY,
      JSON.stringify({ version: LAYOUT_VERSION + 999, layout: someLayout }),
    );
    expect(loadLayout()).toBeNull();
  });

  it('returns null when the record has no layout payload', () => {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify({ version: LAYOUT_VERSION }));

    expect(loadLayout()).toBeNull();
  });

  it('clearLayout removes the stored record', () => {
    saveLayout(someLayout);
    clearLayout();

    expect(window.localStorage.getItem(LAYOUT_STORAGE_KEY)).toBeNull();
    expect(loadLayout()).toBeNull();
  });

  it('saveLayout swallows storage failures instead of breaking the workspace', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage disabled');
    });

    expect(() => saveLayout(someLayout)).not.toThrow();
  });

  it('loadLayout swallows storage read failures', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled');
    });

    expect(() => loadLayout()).not.toThrow();
    expect(loadLayout()).toBeNull();
  });
});
