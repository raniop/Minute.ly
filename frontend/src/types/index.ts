export interface Contact {
  id: number
  linkedin_id: string
  profile_url: string
  full_name: string
  first_name: string
  title: string
  company: string
  industry: string
  is_connected: boolean
  connection_status: string
  last_shown_at: string | null
  last_messaged_at: string | null
  has_replied: boolean
  tags: string
  created_at: string
  updated_at: string
}

export interface BatchContact {
  contact: Contact
  selected: boolean
  suggested_message: string
  message_id: number | null
}

export interface TodayBatch {
  batch_date: string
  contacts: BatchContact[]
}

export interface FollowUpItem {
  contact: Contact
  original_message_date: string
  suggested_followup: string
}

export interface FollowUpBatch {
  contacts: FollowUpItem[]
}

export interface SendItem {
  contact_id: number
  message: string
  attach_video: boolean
}

export interface FollowUpSendItem {
  contact_id: number
  message: string
  send: boolean
}

export interface JobStatus {
  job_id: string
  status: string
  progress: number
  total: number
  error: string | null
}

export interface WorkerStatus {
  worker_status: string
  browser_connected: boolean
  active_job: string | null
}

export interface ContactStats {
  total: number
  connected: number
  by_industry: Record<string, number>
  messaged: number
  replied: number
}

export interface LoginResponse {
  status: string
  message: string
}
