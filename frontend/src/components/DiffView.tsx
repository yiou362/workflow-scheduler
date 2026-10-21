interface Props {
  patch: string | null | undefined
}

/** Plain-text unified diff rendering; never injects HTML. */
export function DiffView({ patch }: Props) {
  if (!patch) return <pre style={{ margin: 0 }}>(no diff content)</pre>
  const lines = patch.split('\n')
  return (
    <pre style={{ margin: 0, maxHeight: 360, overflow: 'auto', fontSize: 12 }}>
      {lines.map((line, index) => {
        let color = 'inherit'
        if (line.startsWith('+') && !line.startsWith('+++')) color = '#237804'
        else if (line.startsWith('-') && !line.startsWith('---')) color = '#a8071a'
        else if (line.startsWith('@@')) color = '#096dd9'
        return (
          <div key={index} style={{ color }}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}
