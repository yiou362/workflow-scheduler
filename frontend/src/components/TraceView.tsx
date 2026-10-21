import { useMemo, useState } from 'react'
import { Alert, Empty, Pagination, Segmented, Space, Timeline, Typography } from 'antd'
import type { TraceIntegrity, TraceItem as TraceItemType } from '../api/types'
import { TraceItem } from './TraceItem'
import { INTEGRITY_LABELS } from '../utils/format'

interface Props {
  items: TraceItemType[]
  integrity: TraceIntegrity | null
  gapCount: number
}

const PAGE_SIZE = 100

export function TraceView({ items, integrity, gapCount }: Props) {
  const [view, setView] = useState<'timeline' | 'hierarchy'>('timeline')
  const [page, setPage] = useState(1)

  const pageItems = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE
    return items.slice(start, start + PAGE_SIZE)
  }, [items, page])

  const childrenMap = useMemo(() => {
    const ids = new Set(items.map((item) => item.external_id))
    const map = new Map<string, TraceItemType[]>()
    for (const item of pageItems) {
      if (item.parent_external_id && ids.has(item.parent_external_id)) {
        const list = map.get(item.parent_external_id) ?? []
        list.push(item)
        map.set(item.parent_external_id, list)
      }
    }
    return map
  }, [items, pageItems])

  const roots = pageItems.filter(
    (item) => !item.parent_external_id || !items.some((candidate) => candidate.external_id === item.parent_external_id),
  )

  return (
    <div data-testid="trace-view">
      <Space direction="vertical" style={{ width: '100%' }}>
        {integrity && integrity !== 'complete' ? (
          <Alert
            type={integrity === 'none' ? 'info' : 'warning'}
            showIcon
            message={INTEGRITY_LABELS[integrity] ?? integrity}
            description={gapCount > 0 ? `${gapCount} SSE disconnect(s)` : undefined}
          />
        ) : null}
        <Segmented
          value={view}
          onChange={(value) => setView(value as 'timeline' | 'hierarchy')}
          options={[
            { label: 'Timeline', value: 'timeline' },
            { label: 'Hierarchy', value: 'hierarchy' },
          ]}
        />
        {items.length === 0 ? (
          <Empty description="No trace entries" />
        ) : view === 'timeline' ? (
          <Timeline
            items={pageItems.map((item) => ({
              color: item.status === 'failed' || item.status === 'rejected' ? 'red' : 'blue',
              children: <TraceItem item={item} />,
            }))}
          />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }}>
            {roots.map((root) => {
              const children = childrenMap.get(root.external_id) ?? []
              return (
                <div key={root.id}>
                  <TraceItem item={root} />
                  {children.length > 0 ? (
                    <div style={{ marginLeft: 24, marginTop: 8 }}>
                      <Typography.Text type="secondary">Child entries</Typography.Text>
                      {children.map((child) => (
                        <TraceItem key={child.id} item={child} />
                      ))}
                    </div>
                  ) : null}
                </div>
              )
            })}
          </Space>
        )}
        {items.length > PAGE_SIZE ? (
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={items.length}
            showSizeChanger={false}
            onChange={setPage}
          />
        ) : null}
      </Space>
    </div>
  )
}
