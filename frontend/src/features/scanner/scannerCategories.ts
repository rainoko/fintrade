/** One selectable entry in `ScannerCategoryPicker`'s dropdown. */
export interface ScannerCategory {
  /** IBKR's own scan-type code, e.g. `'TOP_PERC_GAIN'` — used as
   * `POST /api/ibkr/scanner/run`'s `scan_config.type`. */
  code: string
  /** Human-readable label shown in the picker. */
  label: string
}

/**
 * Normalizes `GET /api/ibkr/scanner/params`'s `categories` — IBKR's own
 * `scan_type_list`, passed through by the backend as an untyped
 * `Record<string, unknown>[]` since its exact field shape is entirely
 * gateway-defined and not modeled server-side (see the `backend-market-
 * scanner` task's `decisions` entry) — into the `{code, label}` shape this
 * page's category picker needs.
 *
 * An entry with no usable string `code` field is dropped entirely rather
 * than shown with a placeholder value: `code` is exactly what gets sent
 * back as `scan_config.type` to actually run a scan, so a category that
 * can't supply one can't be run either way. `label` falls back to `code`
 * itself when `display_name` is missing, rather than a generic "Category N"
 * placeholder — showing IBKR's own scan-type code is still more useful to
 * the caller than an uninformative ordinal.
 */
export function toScannerCategories(raw: Record<string, unknown>[]): ScannerCategory[] {
  const categories: ScannerCategory[] = []
  for (const entry of raw) {
    const code = entry.code
    if (typeof code !== 'string' || code.length === 0) {
      continue
    }
    const displayName = entry.display_name
    categories.push({
      code,
      label: typeof displayName === 'string' && displayName.length > 0 ? displayName : code,
    })
  }
  return categories
}
