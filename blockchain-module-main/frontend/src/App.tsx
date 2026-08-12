import { AuthProvider } from './contexts/AuthContext'
import Inventory from './pages/Inventory'

function App() {
  return (
    <AuthProvider>
      <div className="min-h-screen p-8">
        <Inventory />
      </div>
    </AuthProvider>
  )
}

export default App
