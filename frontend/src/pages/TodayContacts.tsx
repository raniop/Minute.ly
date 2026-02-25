import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getTodayBatch, sendTodayMessages, refreshTodayBatch, getJobStatus } from '../api/client'
import ContactCard from '../components/ContactCard'
import type { SendItem } from '../types'

interface ContactState {
  selected: boolean
  message: string
  attachVideo: boolean
}

export default function TodayContacts() {
  const queryClient = useQueryClient()

  const { data: batch, isLoading, error } = useQuery({
    queryKey: ['todayBatch'],
    queryFn: getTodayBatch,
  })

  const [contactStates, setContactStates] = useState<Record<number, ContactState>>({})
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobProgress, setJobProgress] = useState({ progress: 0, total: 0, status: '' })

  // Initialize states when batch loads
  useEffect(() => {
    if (batch?.contacts) {
      const states: Record<number, ContactState> = {}
      batch.contacts.forEach((bc) => {
        // Preserve selection state for contacts that were already in the list
        const existing = contactStates[bc.contact.id]
        states[bc.contact.id] = {
          selected: existing?.selected ?? false,
          message: existing?.message ?? bc.suggested_message,
          attachVideo: existing?.attachVideo ?? true,
        }
      })
      setContactStates(states)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch])

  // Poll job status
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
    mutationFn: (items: SendItem[]) => sendTodayMessages(items),
    onSuccess: (data) => {
      setJobId(data.job_id)
      setJobProgress({ progress: 0, total: data.total, status: 'queued' })
    },
  })

  const refreshMutation = useMutation({
    mutationFn: (keepIds: number[]) => refreshTodayBatch(keepIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['todayBatch'] })
    },
  })

  const selectedCount = Object.values(contactStates).filter((s) => s.selected).length
  const unselectedCount = (batch?.contacts.length || 0) - selectedCount

  const handleSelectAll = () => {
    const allSelected = selectedCount === batch?.contacts.length
    setContactStates((prev) => {
      const next = { ...prev }
      for (const key of Object.keys(next)) {
        next[Number(key)] = { ...next[Number(key)], selected: !allSelected }
      }
      return next
    })
  }

  const handleRefresh = () => {
    if (!batch) return
    // Keep only the selected contacts, replace the rest
    const keepIds = batch.contacts
      .filter((bc) => contactStates[bc.contact.id]?.selected)
      .map((bc) => bc.contact.id)
    refreshMutation.mutate(keepIds)
  }

  const handleSend = () => {
    if (!batch) return
    const items: SendItem[] = batch.contacts
      .filter((bc) => contactStates[bc.contact.id]?.selected)
      .map((bc) => ({
        contact_id: bc.contact.id,
        message: contactStates[bc.contact.id].message,
        attach_video: contactStates[bc.contact.id].attachVideo,
      }))
    sendMutation.mutate(items)
  }

  const isSending = !!jobId || sendMutation.isPending
  const remaining = jobProgress.total - jobProgress.progress

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading today's contacts...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6 text-red-600">
        Failed to load contacts. Is the backend running?
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Today's Contacts</h1>
          <p className="text-sm text-gray-500 mt-1">
            {batch?.contacts.length || 0} contact{batch?.contacts.length === 1 ? '' : 's'} available for today
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleRefresh}
            disabled={isSending || refreshMutation.isPending || unselectedCount === 0}
            className="px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            title={unselectedCount > 0
              ? `Replace ${unselectedCount} unselected contact${unselectedCount === 1 ? '' : 's'} with new ones`
              : 'Select contacts to keep, then refresh to replace the rest'
            }
          >
            {refreshMutation.isPending ? 'Refreshing...' : `Refresh (${unselectedCount})`}
          </button>
          <button
            onClick={handleSelectAll}
            disabled={isSending}
            className="px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {selectedCount > 0 && selectedCount === batch?.contacts.length ? 'Deselect All' : 'Select All'}
          </button>
          <button
            onClick={handleSend}
            disabled={selectedCount === 0 || isSending}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSending
              ? `Sending... (${jobProgress.progress}/${jobProgress.total})`
              : `Send Selected (${selectedCount})`}
          </button>
        </div>
      </div>

      {isSending && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="flex items-center gap-2">
            <div className="animate-spin w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full" />
            <span className="text-sm text-blue-700">
              Sending message {jobProgress.progress + 1} of {jobProgress.total} via LinkedIn...
              {remaining > 0 && jobProgress.progress > 0 && (
                <span className="text-blue-500"> (next message in ~90 seconds)</span>
              )}
            </span>
          </div>
          <div className="mt-2 bg-blue-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all"
              style={{
                width: `${jobProgress.total > 0 ? (jobProgress.progress / jobProgress.total) * 100 : 0}%`,
              }}
            />
          </div>
        </div>
      )}

      {(!batch?.contacts || batch.contacts.length === 0) ? (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg mb-2">No contacts available for today</p>
          <p className="text-sm">
            Scrape your LinkedIn connections first, or wait for the cooldown period.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {batch.contacts.map((bc) => (
            <ContactCard
              key={bc.contact.id}
              contact={bc.contact}
              selected={contactStates[bc.contact.id]?.selected || false}
              message={contactStates[bc.contact.id]?.message || ''}
              attachVideo={contactStates[bc.contact.id]?.attachVideo ?? true}
              disabled={isSending}
              onToggle={() =>
                setContactStates((prev) => ({
                  ...prev,
                  [bc.contact.id]: {
                    ...prev[bc.contact.id],
                    selected: !prev[bc.contact.id]?.selected,
                  },
                }))
              }
              onMessageChange={(msg) =>
                setContactStates((prev) => ({
                  ...prev,
                  [bc.contact.id]: { ...prev[bc.contact.id], message: msg },
                }))
              }
              onAttachVideoChange={(val) =>
                setContactStates((prev) => ({
                  ...prev,
                  [bc.contact.id]: { ...prev[bc.contact.id], attachVideo: val },
                }))
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}
