import { useState, useEffect } from 'react'
import { getWorkerStatus, loginLinkedIn, verifyLinkedIn } from '../api/client'

interface Props {
  onStatusChange?: (connected: boolean) => void
}

export default function LinkedInStatus({ onStatusChange }: Props) {
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<'disconnected' | 'connecting' | 'verification' | 'connected'>('disconnected')
  const [message, setMessage] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [verifyCode, setVerifyCode] = useState('')

  // Poll worker status
  useEffect(() => {
    const check = async () => {
      try {
        const ws = await getWorkerStatus()
        const isConnected = ws.browser_connected
        if (isConnected && status !== 'connected') {
          setStatus('connected')
          setMessage('')
        }
        onStatusChange?.(isConnected)
      } catch {
        // ignore
      }
    }
    check()
    const interval = setInterval(check, 5000)
    return () => clearInterval(interval)
  }, [status, onStatusChange])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) return
    setLoading(true)
    setMessage('')
    setStatus('connecting')
    try {
      const result = await loginLinkedIn(email, password)
      if (result.status === 'connected') {
        setStatus('connected')
        onStatusChange?.(true)
      } else if (result.status === 'verification_needed') {
        setStatus('verification')
      } else {
        setStatus('disconnected')
      }
      setMessage(result.message)
    } catch {
      setStatus('disconnected')
      setMessage('Login request failed. Please try again.')
    }
    setLoading(false)
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!verifyCode) return
    setLoading(true)
    setMessage('')
    try {
      const result = await verifyLinkedIn(verifyCode)
      if (result.status === 'connected') {
        setStatus('connected')
        onStatusChange?.(true)
      } else if (result.status === 'verification_needed') {
        setStatus('verification')
      } else {
        setStatus('disconnected')
      }
      setMessage(result.message)
    } catch {
      setMessage('Verification failed. Please try again.')
    }
    setLoading(false)
  }

  if (status === 'connected') {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6 flex items-center gap-3">
        <div className="w-3 h-3 bg-green-500 rounded-full" />
        <span className="text-green-800 font-medium">Connected to LinkedIn</span>
      </div>
    )
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5 mb-6">
      <div className="flex items-center gap-3 mb-4">
        <div className={`w-3 h-3 rounded-full ${
          status === 'connecting' ? 'bg-yellow-400 animate-pulse' :
          status === 'verification' ? 'bg-yellow-400' :
          'bg-red-500'
        }`} />
        <span className="font-medium text-gray-800">
          {status === 'connecting' ? 'Connecting to LinkedIn...' :
           status === 'verification' ? 'Verification Required' :
           'LinkedIn Not Connected'}
        </span>
      </div>

      {message && (
        <div className={`text-sm mb-4 p-3 rounded ${
          message.toLowerCase().includes('fail') || message.toLowerCase().includes('invalid') || message.toLowerCase().includes('incorrect')
            ? 'bg-red-50 text-red-700'
            : 'bg-blue-50 text-blue-700'
        }`}>
          {message}
        </div>
      )}

      {status === 'verification' ? (
        <form onSubmit={handleVerify} className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="block text-sm text-gray-600 mb-1">Verification Code</label>
            <input
              type="text"
              value={verifyCode}
              onChange={e => setVerifyCode(e.target.value)}
              placeholder="Enter the code from your email/phone"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              disabled={loading}
            />
          </div>
          <button
            type="submit"
            disabled={loading || !verifyCode}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Verifying...' : 'Verify'}
          </button>
        </form>
      ) : (
        <form onSubmit={handleLogin} className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="block text-sm text-gray-600 mb-1">LinkedIn Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="your@email.com"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              disabled={loading}
            />
          </div>
          <div className="flex-1">
            <label className="block text-sm text-gray-600 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Password"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              disabled={loading}
            />
          </div>
          <button
            type="submit"
            disabled={loading || !email || !password}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Connecting...' : 'Login'}
          </button>
        </form>
      )}
    </div>
  )
}
