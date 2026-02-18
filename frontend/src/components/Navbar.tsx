import { NavLink } from 'react-router-dom'

export default function Navbar() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 rounded-lg font-medium transition-colors ${
      isActive
        ? 'bg-blue-600 text-white'
        : 'text-gray-600 hover:bg-gray-100'
    }`

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3">
      <div className="flex items-center justify-between max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-blue-600">Minute.ly</span>
          <span className="text-sm text-gray-400">Outreach</span>
        </div>
        <div className="flex gap-2">
          <NavLink to="/" className={linkClass}>
            Today's Contacts
          </NavLink>
          <NavLink to="/followups" className={linkClass}>
            Follow-ups
          </NavLink>
          <NavLink to="/contacts" className={linkClass}>
            All Contacts
          </NavLink>
        </div>
      </div>
    </nav>
  )
}
