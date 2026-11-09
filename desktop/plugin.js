// PRSN ID for Hermes, the Desktop half. One status bar item that shows this agent's PRSN ID
// state. Clicking it shows the longer line. It only reads. Its one answer comes from the
// plugin's own backend at /status, and nothing here can seal.
import { host, haptic } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx } from 'react/jsx-runtime'

const ID = 'prsn-id'
const POLL_MS = 300000
const UNCHECKED = { word: 'PRSN ID not checked', line: 'The plugin could not be reached just now.', verified: null }

function useStatus(ctx) {
  const [status, setStatus] = useState(null)
  useEffect(() => {
    let live = true
    const load = () => ctx.rest('/status').then(
      s => live && setStatus(s && s.word ? s : UNCHECKED),
      () => live && setStatus(UNCHECKED))
    load()
    const timer = setInterval(load, POLL_MS)
    return () => { live = false; clearInterval(timer) }
  }, [ctx])
  return status
}

function StatusChip({ ctx }) {
  const status = useStatus(ctx)
  const word = status ? status.word : 'PRSN ID'
  const tone = status && status.verified === false ? 'text-(--ui-text-error)' : 'text-(--ui-text-tertiary)'
  return jsx('button', {
    type: 'button',
    className: `px-1.5 text-[0.6875rem] ${tone}`,
    title: status ? status.line : 'PRSN ID',
    onClick: () => {
      haptic('tap')
      host.notify({ kind: 'info', message: status ? status.line : 'PRSN ID is being checked.' })
    },
    children: word
  })
}

export default {
  id: ID, // must match the folder name
  name: 'PRSN ID',
  register(ctx) {
    ctx.register({
      id: 'status-item',
      area: 'statusBar.right',
      order: 126,
      render: () => jsx(StatusChip, { ctx })
    })
  }
}
