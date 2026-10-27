import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'

/** Pages render their own topbar/StepBar and width wrapper (.view.narrow 820px, .wrap 1180px). */
export function AppShell() {
  return (
    <div className="app">
      <Sidebar />
      <main>
        <Outlet />
      </main>
    </div>
  )
}
