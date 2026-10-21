import { Collapse } from 'antd'
import { prettyJson } from '../utils/format'

export function ConfigSnapshot({ snapshot }: { snapshot: Record<string, unknown> }) {
  return (
    <Collapse
      items={[
        {
          key: 'snapshot',
          label: 'Config snapshot (frozen when the run was created; not affected by later task edits)',
          children: <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{prettyJson(snapshot)}</pre>,
        },
      ]}
    />
  )
}
