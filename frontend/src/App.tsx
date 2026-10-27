import { Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/shell/AppShell'
import { InputStep } from '@/features/research/InputStep'
import { ResearchPage } from '@/features/research/ResearchPage'
import { HistoryPage } from '@/features/history/HistoryPage'
import { ManufacturersPage } from '@/features/manufacturers/ManufacturersPage'
import { SettingsPage } from '@/features/settings/SettingsPage'
import { Placeholder } from '@/pages/Placeholder'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<InputStep />} />
        <Route path="research/:id" element={<ResearchPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="manufacturers" element={<ManufacturersPage />} />
        <Route path="shortlist" element={<ManufacturersPage starred />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Route>
    </Routes>
  )
}
