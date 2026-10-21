import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Form } from 'antd'
import { describe, expect, it } from 'vitest'
import { ScheduleForm } from './ScheduleForm'
import type { ScheduleType } from '../api/types'

function Demo({ initial }: { initial: ScheduleType }) {
  const [form] = Form.useForm()
  return (
    <Form form={form} initialValues={{ schedule_type: initial, schedule_enabled: false }}>
      <button type="button" onClick={() => form.setFieldValue('schedule_type', 'cron')}>
        to-cron
      </button>
      <button type="button" onClick={() => form.setFieldValue('schedule_type', 'interval')}>
        to-interval
      </button>
      <button type="button" onClick={() => form.setFieldValue('schedule_type', 'none')}>
        to-none
      </button>
      <ScheduleForm form={form} utcOffset="+08:00" />
    </Form>
  )
}

describe('ScheduleForm', () => {
  it('switches fields with the schedule type', async () => {
    render(<Demo initial="none" />)
    expect(screen.getByText('Manual runs only; no automatic schedule')).toBeInTheDocument()

    fireEvent.click(screen.getByText('to-cron'))
    await waitFor(() => expect(screen.getByText('Cron expression')).toBeInTheDocument())

    fireEvent.click(screen.getByText('to-interval'))
    await waitFor(() => expect(screen.getByText('Interval (seconds)')).toBeInTheDocument())

    fireEvent.click(screen.getByText('to-none'))
    await waitFor(() => expect(screen.getByText('Manual runs only; no automatic schedule')).toBeInTheDocument())
  })

  it('always explains the fixed UTC offset', () => {
    render(<Demo initial="none" />)
    expect(screen.getByText('All times are interpreted as UTC+08:00')).toBeInTheDocument()
  })
})
