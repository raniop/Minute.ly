/**
 * Build an initial outreach message for a contact.
 * Mirrors the backend template logic so we can show a preview in the UI.
 */
export function build_initial_message(
  name: string,
  _company: string = '',
  _industry: string = 'Unknown'
): string {
  return (
    `Hi ${name},\n` +
    `Great to connect, and thanks for accepting the invite.\n` +
    `I wanted to share something we've built at Minute-ly.com, ` +
    ` an AI model that instantly transforms horizontal video into ` +
    `vertical format at scale. It's already being used by major ` +
    `organizations including Fox, Paramount, Formula 1, NASCAR, ` +
    `ATP Tour, Univision, and others.\n` +
    `Sharing a quick 30-second demo here - would love to hear your thoughts.`
  )
}
