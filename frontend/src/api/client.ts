import axios from 'axios'
import type {
  TodayBatch,
  FollowUpBatch,
  SendItem,
  FollowUpSendItem,
  JobStatus,
  WorkerStatus,
  ContactStats,
  Contact,
  LoginResponse,
  ContactsCacheStatus,
  ActiveScrape,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

// Redirect to login page on 401 (session expired after deploy/restart)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Dispatch a custom event so the app can show a login prompt
      window.dispatchEvent(new CustomEvent('session-expired'))
    }
    return Promise.reject(error)
  }
)

// Batches
export const getTodayBatch = () =>
  api.get<TodayBatch>('/batches/today').then(r => r.data)

export const refreshTodayBatch = (keepContactIds: number[]) =>
  api.post<TodayBatch>('/batches/today/refresh', { keep_contact_ids: keepContactIds }).then(r => r.data)

export const sendTodayMessages = (items: SendItem[]) =>
  api.post<JobStatus>('/batches/today/send', { items }).then(r => r.data)

export const getFollowUps = () =>
  api.get<FollowUpBatch>('/batches/followups').then(r => r.data)

export const sendFollowUps = (items: FollowUpSendItem[]) =>
  api.post<JobStatus>('/batches/followups/send', { items }).then(r => r.data)

// Contacts
export const getContacts = (params?: Record<string, string>) =>
  api.get<Contact[]>('/contacts', { params }).then(r => r.data)

export const getContactStats = () =>
  api.get<ContactStats>('/contacts/stats').then(r => r.data)

// LinkedIn
export const getWorkerStatus = () =>
  api.get<WorkerStatus>('/linkedin/status').then(r => r.data)

export const loginLinkedIn = (email: string, password: string) =>
  api.post<LoginResponse>('/linkedin/login', { email, password }).then(r => r.data)

export const verifyLinkedIn = (code: string) =>
  api.post<LoginResponse>('/linkedin/verify', { code }).then(r => r.data)

export const checkLogin = (force: boolean = false) =>
  api.post<{ logged_in: boolean }>('/linkedin/check-login', { force }).then(r => r.data)

export const logoutLinkedIn = () =>
  api.post<{ status: string; message: string }>('/linkedin/logout').then(r => r.data)

export const getContactsCacheStatus = () =>
  api.get<ContactsCacheStatus>('/linkedin/contacts-status').then(r => r.data)

export const scrapeConnections = (force: boolean = false) =>
  api.post<JobStatus>('/linkedin/scrape-connections', { force }).then(r => r.data)

export const getJobStatus = (jobId: string) =>
  api.get<JobStatus>(`/linkedin/job/${jobId}`).then(r => r.data)

export const getActiveScrape = () =>
  api.get<ActiveScrape>('/linkedin/active-scrape').then(r => r.data)

export const reconnectLinkedIn = () =>
  api.post<{ reconnected: boolean; browser_connected?: boolean; reason?: string }>('/linkedin/reconnect').then(r => r.data)
