import { describe, expect, it } from 'vitest'
import { toScannerCategories } from './scannerCategories'

describe('toScannerCategories', () => {
  it('maps code/display_name entries to {code, label}', () => {
    const result = toScannerCategories([
      { code: 'TOP_PERC_GAIN', display_name: 'Top % Gainers' },
      { code: 'TOP_PERC_LOSE', display_name: 'Top % Losers' },
    ])

    expect(result).toEqual([
      { code: 'TOP_PERC_GAIN', label: 'Top % Gainers' },
      { code: 'TOP_PERC_LOSE', label: 'Top % Losers' },
    ])
  })

  it('falls back to code as the label when display_name is missing', () => {
    const result = toScannerCategories([{ code: 'HOT_BY_VOLUME' }])

    expect(result).toEqual([{ code: 'HOT_BY_VOLUME', label: 'HOT_BY_VOLUME' }])
  })

  it('falls back to code as the label when display_name is not a string', () => {
    const result = toScannerCategories([{ code: 'HOT_BY_VOLUME', display_name: 42 }])

    expect(result).toEqual([{ code: 'HOT_BY_VOLUME', label: 'HOT_BY_VOLUME' }])
  })

  it('drops an entry with no usable string code', () => {
    const result = toScannerCategories([
      { display_name: 'No code at all' },
      { code: '', display_name: 'Empty code' },
      { code: 123, display_name: 'Numeric code' },
      { code: 'VALID', display_name: 'Valid entry' },
    ])

    expect(result).toEqual([{ code: 'VALID', label: 'Valid entry' }])
  })

  it('returns an empty array for an empty input', () => {
    expect(toScannerCategories([])).toEqual([])
  })
})
