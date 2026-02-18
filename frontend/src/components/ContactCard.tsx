import type { Contact } from '../types'

interface Props {
  contact: Contact
  selected: boolean
  message: string
  onToggle: () => void
  onMessageChange: (msg: string) => void
  attachVideo: boolean
  onAttachVideoChange: (val: boolean) => void
  disabled?: boolean
}

export default function ContactCard({
  contact,
  selected,
  message,
  onToggle,
  onMessageChange,
  attachVideo,
  onAttachVideoChange,
  disabled = false,
}: Props) {
  const initials = contact.full_name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  return (
    <div
      className={`border rounded-lg p-4 transition-colors ${
        selected
          ? 'border-blue-400 bg-blue-50 shadow-sm'
          : 'border-gray-200 bg-white hover:border-gray-300'
      }`}
    >
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          disabled={disabled}
          className="mt-3 w-5 h-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
        <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center text-white font-semibold text-sm shrink-0">
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <h3 className="font-semibold text-gray-900 truncate">
              {contact.full_name}
            </h3>
            {contact.industry && contact.industry !== 'Unknown' && (
              <span className="px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full text-xs font-medium">
                {contact.industry}
              </span>
            )}
          </div>
          {(contact.title || contact.company) && (
            <p className="text-sm text-gray-600 truncate">
              {contact.title}
              {contact.title && contact.company && ' @ '}
              {!contact.title && contact.company ? contact.company : ''}
              {contact.title && contact.company ? contact.company : ''}
            </p>
          )}

          {selected && (
            <div className="mt-3 space-y-2">
              <label className="text-xs font-medium text-gray-500 block">Message</label>
              <textarea
                value={message}
                onChange={(e) => onMessageChange(e.target.value)}
                disabled={disabled}
                rows={4}
                className="w-full border border-gray-300 rounded-md p-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 resize-none"
              />
              <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
                <input
                  type="checkbox"
                  checked={attachVideo}
                  onChange={(e) => onAttachVideoChange(e.target.checked)}
                  disabled={disabled}
                  className="rounded border-gray-300 text-blue-600"
                />
                Attach demo video
              </label>
            </div>
          )}
        </div>
        <a
          href={contact.profile_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-500 hover:text-blue-700 text-xs font-medium shrink-0 mt-2"
        >
          LinkedIn &rarr;
        </a>
      </div>
    </div>
  )
}
