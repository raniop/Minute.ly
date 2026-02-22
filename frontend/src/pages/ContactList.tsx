import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getContacts, getContactStats, scrapeConnections, getJobStatus } from '../api/client'
import { useState, useEffect, useCallback } from 'react'
import LinkedInStatus from '../components/LinkedInStatus'

export default function ContactList() {
  const [industry, setIndustry] = useState('')
  const [browserConnected, setBrowserConnected] = useState(false)
  const [scraping, setScraping] = useState(false)
  const [scrapeJobId, setScrapeJobId] = useState<string | null>(null)
  const [scrapeProgress, setScrapeProgress] = useState({ progress: 0, total: 0, status: '' })
  const queryClient = useQueryClient()

  const { data: contacts, isLoading } = useQuery({
    queryKey: ['contacts', industry],
    queryFn: () =>
      getContacts(
        industry
          ? { industry, connected_only: 'true' }
          : { connected_only: 'true' }
      ),
  })

  const { data: stats } = useQuery({
    queryKey: ['contactStats'],
    queryFn: getContactStats,
  })

  const handleStatusChange = useCallback((connected: boolean) => {
    setBrowserConnected(connected)
  }, [])

  const handleScrape = async () => {
    setScraping(true)
    setScrapeProgress({ progress: 0, total: 0, status: 'queued' })
    try {
      const result = await scrapeConnections()
      setScrapeJobId(result.job_id)
    } catch {
      setScraping(false)
      setScrapeProgress({ progress: 0, total: 0, status: '' })
    }
  }

  // Poll scrape job status
  useEffect(() => {
    if (!scrapeJobId) return
    const interval = setInterval(async () => {
      try {
        const status = await getJobStatus(scrapeJobId)
        setScrapeProgress({
          progress: status.progress,
          total: status.total,
          status: status.status,
        })
        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(interval)
          setScrapeJobId(null)
          setScraping(false)
          queryClient.invalidateQueries({ queryKey: ['contacts'] })
          queryClient.invalidateQueries({ queryKey: ['contactStats'] })
        }
      } catch {
        // ignore
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [scrapeJobId, queryClient])

  return (
    <div className="max-w-6xl mx-auto p-6">
      <LinkedInStatus onStatusChange={handleStatusChange} />

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">All Contacts</h1>
        <div className="flex items-center gap-3">
          {scraping && scrapeProgress.total > 0 && (
            <span className="text-sm text-gray-500">
              {scrapeProgress.progress}/{scrapeProgress.total} scraped
            </span>
          )}
          <button
            onClick={handleScrape}
            disabled={scraping || !browserConnected}
            className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
            title={!browserConnected ? 'Login to LinkedIn first' : ''}
          >
            {scraping ? 'Scraping...' : 'Scrape LinkedIn Connections'}
          </button>
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-white border rounded-lg p-4 text-center">
            <div className="text-2xl font-bold text-gray-900">{stats.total}</div>
            <div className="text-sm text-gray-500">Total</div>
          </div>
          <div className="bg-white border rounded-lg p-4 text-center">
            <div className="text-2xl font-bold text-blue-600">{stats.connected}</div>
            <div className="text-sm text-gray-500">Connected</div>
          </div>
          <div className="bg-white border rounded-lg p-4 text-center">
            <div className="text-2xl font-bold text-green-600">{stats.messaged}</div>
            <div className="text-sm text-gray-500">Messaged</div>
          </div>
          <div className="bg-white border rounded-lg p-4 text-center">
            <div className="text-2xl font-bold text-purple-600">{stats.replied}</div>
            <div className="text-sm text-gray-500">Replied</div>
          </div>
        </div>
      )}

      <div className="mb-4">
        <select
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
        >
          <option value="">All Industries</option>
          <option value="Sports">Sports</option>
          <option value="News">News</option>
          <option value="Entertainment">Entertainment</option>
          <option value="Unknown">Unknown</option>
        </select>
      </div>

      {isLoading ? (
        <div className="text-gray-500 text-center py-8">Loading contacts...</div>
      ) : (
        <div className="bg-white border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Name</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Title</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Company</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Industry</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Last Messaged</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {contacts?.map((contact) => (
                <tr key={contact.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <a
                      href={contact.profile_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline font-medium"
                    >
                      {contact.full_name}
                    </a>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{contact.title}</td>
                  <td className="px-4 py-3 text-gray-600">{contact.company}</td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full text-xs">
                      {contact.industry}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {contact.has_replied ? (
                      <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded-full text-xs">
                        Replied
                      </span>
                    ) : contact.last_messaged_at ? (
                      <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full text-xs">
                        Messaged
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full text-xs">
                        New
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {contact.last_messaged_at
                      ? new Date(contact.last_messaged_at).toLocaleDateString()
                      : '-'}
                  </td>
                </tr>
              ))}
              {(!contacts || contacts.length === 0) && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                    No contacts found. {browserConnected ? 'Click "Scrape LinkedIn Connections" to get started.' : 'Login to LinkedIn first, then scrape your connections.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
