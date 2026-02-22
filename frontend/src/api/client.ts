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
} from '../types'

const api = axios.create({
  baseURL: '/api',
})

// Batches
export const getTodayBatch = () =>
  api.get<TodayBatch>('/batches/today').then(r => r.data)

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

export const checkLogin = () =>
  api.post<{ logged_in: boolean }>('/linkedin/check-login').then(r => r.data)

export const logoutLinkedIn = () =>
  api.post<{ status: string; message: string }>('/linkedin/logout').then(r => r.data)

export const scrapeConnections = () =>
  api.post<JobStatus>('/linkedin/scrape-connections').then(r => r.data)

export const getJobStatus = (jobId: string) =>
  api.get<JobStatus>(`/linkedin/job/${jobId}`).then(r => r.data)
