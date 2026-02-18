interface Props {
  status: string
}

const colors: Record<string, string> = {
  sent: 'bg-green-100 text-green-800',
  queued: 'bg-yellow-100 text-yellow-800',
  sending: 'bg-blue-100 text-blue-800',
  failed: 'bg-red-100 text-red-800',
  draft: 'bg-gray-100 text-gray-600',
}

export default function StatusBadge({ status }: Props) {
  const colorClass = colors[status] || 'bg-gray-100 text-gray-600'
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {status}
    </span>
  )
}
