import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { getFollowUps, sendFollowUps, getJobStatus } from '../api/client'
import type { FollowUpSendItem } from '../types'

interface FollowUpState {
  send: boolean
  message: string
}

export default function FollowUp() {
  const { data: batch, isLoading, error } = useQuery({
    queryKey: ['followups'],
    queryFn: getFollowUps,
  })

  const [states, setStates] = useState<Record<number, FollowUpState>>({})
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobProgress, setJobProgress] = useState({ progress: 0, total: 0, status: '' })

  useEffect(() => {
    if (batch?.contacts) {
      const s: Record<number, FollowUpState> = {}
      batch.contacts.forEach((item) => {
        s[item.contact.id] = {
          send: true,
          message: item.suggested_followup,
        }
      })
      setStates(s)
    }
  }, [batch])

  useEffect(() => {
    if (!jobId) return
    const interval = setInterval(async () => {
      const status = await getJobStatus(jobId)
      setJobProgress({
        progress: status.progress,
        total: status.total,
        status: status.status,
      })
      if (status.status === 'completed' || status.status === 'failed') {
        clearInterval(interval)
        setJobId(null)
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [jobId])

  const sendMutation = useMutation({
    mutationFn: (items: FollowUpSendItem[]) => sendFollowUps(items),
    onSuccess: (data) => {
      setJobId(data.job_id)
      setJobProgress({ progress: 0, total: data.total, status: 'queued' })
    },
  })

  const sendCount = Object.values(states).filter((s) => s.send).length
  const isSending = !!jobId || sendMutation.isPending

  const handleSend = () => {
    if (!batch) return
    const items: FollowUpSendItem[] = batch.contacts.map((item) => ({
      contact_id: item.contact.id,
      message: states[item.contact.id]?.message || '',
      send: states[item.contact.id]?.send ?? true,
    }))
    sendMutation.mutate(items)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading follow-ups...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6 text-red-600">
        Failed to load follow-ups. Is the backend running?
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Follow-ups</h1>
          <p className="text-sm text-gray-500 mt-1">
            Contacts messaged 2 days ago who haven't replied
          </p>
        </div>
        <button
          onClick={handleSend}
          disabled={sendCount === 0 || isSending}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSending
            ? `Sending... (${jobProgress.progress}/${jobProgress.total})`
            : `Send Follow-ups (${sendCount})`}
        </button>
      </div>

      {isSending && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="flex items-center gap-2">
            <div className="animate-spin w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full" />
            <span className="text-sm text-blue-700">
              Sending follow-ups... ({jobProgress.progress}/{jobProgress.total})
            </span>
          </div>
        </div>
      )}

      {(!batch?.contacts || batch.contacts.length === 0) ? (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg mb-2">No follow-ups pending</p>
          <p className="text-sm">
            Contacts messaged 2 days ago who haven't replied will appear here.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {batch.contacts.map((item) => (
            <div
              key={item.contact.id}
              className={`border rounded-lg p-4 transition-colors ${
                states[item.contact.id]?.send
                  ? 'border-blue-400 bg-blue-50'
                  : 'border-gray-200 bg-white opacity-60'
              }`}
            >
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={states[item.contact.id]?.send ?? true}
                  onChange={() =>
                    setStates((prev) => ({
                      ...prev,
                      [item.contact.id]: {
                        ...prev[item.contact.id],
                        send: !prev[item.contact.id]?.send,
                      },
                    }))
                  }
                  disabled={isSending}
                  className="mt-1 w-5 h-5 rounded border-gray-300 text-blue-600"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-gray-900">
                      {item.contact.full_name}
                    </h3>
                    <span className="text-xs text-gray-400">
                      Sent: {new Date(item.original_message_date).toLocaleDateString()}
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 mb-2">
                    {item.contact.title}
                    {item.contact.company && ` @ ${item.contact.company}`}
                  </p>
                  {states[item.contact.id]?.send && (
                    <textarea
                      value={states[item.contact.id]?.message || ''}
                      onChange={(e) =>
                        setStates((prev) => ({
                          ...prev,
                          [item.contact.id]: {
                            ...prev[item.contact.id],
                            message: e.target.value,
                          },
                        }))
                      }
                      disabled={isSending}
                      rows={2}
                      className="w-full border border-gray-300 rounded-md p-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 resize-none"
                    />
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
