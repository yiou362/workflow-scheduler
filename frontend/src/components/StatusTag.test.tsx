import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RUN_STATUS_LABELS } from '../utils/format'
import { StatusTag } from './StatusTag'
import type { RunStatus } from '../api/types'

describe('StatusTag', () => {
  it('renders an English label for every run status', () => {
    const statuses = Object.keys(RUN_STATUS_LABELS) as RunStatus[]
    expect(statuses).toHaveLength(12)
    for (const status of statuses) {
      const { unmount } = render(<StatusTag status={status} />)
      expect(screen.getByText(RUN_STATUS_LABELS[status])).toBeInTheDocument()
      unmount()
    }
  })

  it('never presents Completed as business success', () => {
    render(<StatusTag status="completed" />)
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.queryByText('Succeeded')).not.toBeInTheDocument()
  })
})
