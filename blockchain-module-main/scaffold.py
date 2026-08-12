import os
import json

base_dir = r"D:\blockchain-module-main\blockchain-module-main\frontend"
os.makedirs(base_dir, exist_ok=True)

# 1. package.json
package_json = {
  "name": "nexus-erp-frontend",
  "private": True,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "lucide-react": "^0.300.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.43",
    "@types/react-dom": "^18.2.17",
    "@vitejs/plugin-react": "^4.2.1",
    "autoprefixer": "^10.4.16",
    "postcss": "^8.4.32",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.2.2",
    "vite": "^5.0.8"
  }
}

with open(os.path.join(base_dir, "package.json"), "w") as f:
    json.dump(package_json, f, indent=2)

# 2. vite.config.ts
vite_config = """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})
"""
with open(os.path.join(base_dir, "vite.config.ts"), "w") as f:
    f.write(vite_config)

# 3. tsconfig.json
tsconfig = {
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": True,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": True,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": True,
    "resolveJsonModule": True,
    "isolatedModules": True,
    "noEmit": True,
    "jsx": "react-jsx",
    "strict": True,
    "noUnusedLocals": True,
    "noUnusedParameters": True,
    "noFallthroughCasesInSwitch": True,
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
with open(os.path.join(base_dir, "tsconfig.json"), "w") as f:
    json.dump(tsconfig, f, indent=2)

# tsconfig.node.json
tsconfig_node = {
  "compilerOptions": {
    "composite": True,
    "skipLibCheck": True,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": True
  },
  "include": ["vite.config.ts"]
}
with open(os.path.join(base_dir, "tsconfig.node.json"), "w") as f:
    json.dump(tsconfig_node, f, indent=2)

# 4. tailwind.config.js
tailwind_config = """/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: "hsl(var(--primary))",
        "primary-foreground": "hsl(var(--primary-foreground))",
        destructive: "hsl(var(--destructive))",
        "destructive-foreground": "hsl(var(--destructive-foreground))",
        muted: "hsl(var(--muted))",
        "muted-foreground": "hsl(var(--muted-foreground))",
        success: "hsl(var(--success))",
        warning: "hsl(var(--warning))",
        border: "hsl(var(--border))",
      }
    },
  },
  plugins: [],
}
"""
with open(os.path.join(base_dir, "tailwind.config.js"), "w") as f:
    f.write(tailwind_config)

# 5. postcss.config.js
postcss_config = """export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
"""
with open(os.path.join(base_dir, "postcss.config.js"), "w") as f:
    f.write(postcss_config)

# 6. index.html
index_html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NEXUS ERP - Dummy Frontend</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""
with open(os.path.join(base_dir, "index.html"), "w") as f:
    f.write(index_html)

# 7. src/ directory
src_dir = os.path.join(base_dir, "src")
os.makedirs(src_dir, exist_ok=True)
os.makedirs(os.path.join(src_dir, "pages"), exist_ok=True)
os.makedirs(os.path.join(src_dir, "components"), exist_ok=True)
os.makedirs(os.path.join(src_dir, "services"), exist_ok=True)
os.makedirs(os.path.join(src_dir, "hooks"), exist_ok=True)
os.makedirs(os.path.join(src_dir, "contexts"), exist_ok=True)

# index.css
index_css = """@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 210 40% 98%;
    --foreground: 222.2 84% 4.9%;
    --primary: 221.2 83.2% 53.3%;
    --primary-foreground: 210 40% 98%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;
    --muted: 210 40% 96.1%;
    --muted-foreground: 215.4 16.3% 46.9%;
    --success: 142.1 76.2% 36.3%;
    --warning: 38 92% 50%;
    --border: 214.3 31.8% 91.4%;
  }
}

body {
  background-color: hsl(var(--background));
  color: hsl(var(--foreground));
}

.glass-card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
  border: 1px solid hsl(var(--border));
}

.btn-navy {
  background-color: hsl(var(--primary));
  color: white;
  border-radius: 8px;
}
.btn-navy:hover {
  opacity: 0.9;
}
"""
with open(os.path.join(src_dir, "index.css"), "w") as f:
    f.write(index_css)

# main.tsx
main_tsx = """import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
"""
with open(os.path.join(src_dir, "main.tsx"), "w") as f:
    f.write(main_tsx)

# App.tsx
app_tsx = """import { AuthProvider } from './contexts/AuthContext'
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
"""
with open(os.path.join(src_dir, "App.tsx"), "w") as f:
    f.write(app_tsx)

# hooks/use-toast.ts (dummy)
use_toast_ts = """export const useToast = () => {
  return {
    toast: (opts: any) => {
      console.log("TOAST:", opts.title, opts.description);
      alert(`${opts.title}\\n${opts.description || ''}`);
    }
  }
}
"""
with open(os.path.join(src_dir, "hooks", "use-toast.ts"), "w") as f:
    f.write(use_toast_ts)

# contexts/AuthContext.tsx (dummy)
auth_context_tsx = """import React, { createContext, useContext } from 'react';

const AuthContext = createContext({ user: { id: "user_1", name: "Admin", email: "admin@nexus.com" }});

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  return (
    <AuthContext.Provider value={{ user: { id: "user_1", name: "Admin", email: "admin@nexus.com" }}}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext);
"""
with open(os.path.join(src_dir, "contexts", "AuthContext.tsx"), "w") as f:
    f.write(auth_context_tsx)

print("Scaffolded basic frontend React application!")
