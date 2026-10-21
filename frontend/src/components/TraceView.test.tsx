import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TraceView } from './TraceView'
import type { TraceItem } from '../api/types'

const failedTool: TraceItem = {
  id: 'trc_1',
  kind: 'tool',
  external_id: 'call_1',
  parent_external_id: 'msg_1',
  name: 'read',
  status: 'failed',
  sequence: 1,
  started_at: '2026-10-19T01:00:05.000Z',
  ended_at: '2026-10-19T01:00:06.000Z',
  duration_ms: 1000,
  input: { path: 'a.txt' },
  output: null,
  error: 'permission denied',
  metadata: null,
}

describe('TraceView', () => {
  it('shows an empty state', () => {
    render(<TraceView items={[]} integrity="none" gapCount={0} />)
    expect(screen.getByText('No trace entries')).toBeInTheDocument()
  })

  it('shows gap warning and failed tool details', () => {
    render(<TraceView items={[failedTool]} integrity="gap" gapCount={1} />)
    expect(screen.getByText('Trace has gaps, backfilled from the final message')).toBeInTheDocument()
    expect(screen.getByText('read')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
    fireEvent.click(screen.getByText('read'))
    expect(screen.getByText('permission denied')).toBeInTheDocument()
  })

  it('does not infer skills from prompt text', () => {
    render(<TraceView items={[failedTool]} integrity="complete" gapCount={0} />)
    expect(screen.queryByText('Skill')).not.toBeInTheDocument()
  })
})
