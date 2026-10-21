import { Typography } from 'antd'
import { formatTime } from '../utils/time'

interface Props {
  value: string | null | undefined
  offset?: string
  showOffset?: boolean
}

export function TimeText({ value, offset = '+08:00', showOffset = false }: Props) {
  if (!value) return <span>—</span>
  const text = formatTime(value, offset)
  return (
    <Typography.Text title={value}>
      {text}
      {showOffset ? ` (UTC${offset})` : ''}
    </Typography.Text>
  )
}
