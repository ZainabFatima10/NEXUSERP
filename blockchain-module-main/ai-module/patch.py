import re

with open("Inventory.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update Imports
content = content.replace(
    "} from \"@/services/api\";",
    "  getNotifications, Notification\n} from \"@/services/api\";"
)

# 2. Update StatusBadge colors
content = content.replace(
    "    Critical:   \"bg-destructive/10 text-destructive\",",
    "    Critical:   \"bg-destructive/10 text-destructive\",\n    \"Out of Stock\": \"bg-destructive text-destructive-foreground\","
)

# 3. Add notifications state
content = content.replace(
    "  const [refreshing, setRefreshing] = useState(false);",
    "  const [refreshing, setRefreshing] = useState(false);\n  const [notifications, setNotifications] = useState<Notification[]>([]);"
)

# 4. Update summary state
content = content.replace(
    "  const [summary, setSummary]       = useState({ total_items: 0, ok: 0, low: 0, critical: 0 });",
    "  const [summary, setSummary]       = useState({ total_items: 0, ok: 0, low: 0, critical: 0, out_of_stock: 0 });"
)

# 5. Update load function
content = content.replace(
    """      const [inv, ordersRes] = await Promise.all([
        getInventoryOverview(),
        listOrders({ limit: 200 }),
      ]);
      setItems(inv.items);
      setSummary(inv.summary);
      const all = ordersRes.orders;""",
    """      const [inv, ordersRes, notifsRes] = await Promise.all([
        getInventoryOverview(),
        listOrders({ limit: 200 }),
        getNotifications({ unread: true })
      ]);
      setItems(inv.items);
      setSummary(inv.summary);
      setNotifications(notifsRes.notifications.slice(0, 5));
      const all = ordersRes.orders;"""
)

# 6. Replace KPIs Grid
old_kpi = """      {/* Summary KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Total Items",  value: summary.total_items, icon: Package,       color: "text-primary" },
          { label: "OK",           value: summary.ok,          icon: CheckCircle2,  color: "text-success" },
          { label: "Low Stock",    value: summary.low,         icon: AlertTriangle, color: "text-warning" },
          { label: "Critical",     value: summary.critical,    icon: XCircle,       color: "text-destructive" },
        ].map((k) => (
          <div key={k.label} className="glass-card p-4 glow-cyan-hover">
            <div className="flex items-center gap-2 mb-2">
              <k.icon size={18} className={k.color} />
              <span className="text-xs text-muted-foreground">{k.label}</span>
            </div>
            <p className="text-2xl font-heading font-bold">{k.value}</p>
          </div>
        ))}
      </div>"""

new_kpi = """      {/* Summary KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
        {[
          { label: "Total Items",  value: summary.total_items, icon: Package,       color: "text-primary" },
          { label: "OK",           value: summary.ok,          icon: CheckCircle2,  color: "text-success" },
          { label: "Low Stock",    value: summary.low,         icon: AlertTriangle, color: "text-warning" },
          { label: "Critical",     value: summary.critical,    icon: XCircle,       color: "text-destructive" },
          { label: "Out of Stock", value: summary.out_of_stock, icon: XCircle,       color: "text-destructive" },
        ].map((k) => (
          <div key={k.label} className="glass-card p-4 glow-cyan-hover flex flex-col justify-between">
            <div className="flex items-center gap-2 mb-2">
              <k.icon size={18} className={k.color} />
              <span className="text-xs text-muted-foreground whitespace-nowrap">{k.label}</span>
            </div>
            <p className="text-2xl font-heading font-bold">{k.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: "Generation", value: items.filter(i => i.category === "Generation").length, color: "text-primary" },
          { label: "Infrastructure", value: items.filter(i => i.category === "Infrastructure").length, color: "text-secondary" },
          { label: "Operational", value: items.filter(i => i.category === "Operational").length, color: "text-accent-cyan" },
        ].map((k) => (
          <div key={k.label} className="glass-card p-4 flex items-center justify-between">
            <span className="text-sm font-medium text-muted-foreground">{k.label}</span>
            <p className="text-xl font-bold">{k.value}</p>
          </div>
        ))}
      </div>

      {/* Analytics & Notifications */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-sm font-heading font-bold text-muted-foreground uppercase tracking-wider">Inventory Distribution</h2>
          <div className="glass-card p-6 h-64 flex flex-col justify-end overflow-hidden">
             <div className="flex items-end h-full gap-8 w-full px-4">
                {["Generation", "Infrastructure", "Operational"].map(cat => {
                   const count = items.filter(i => i.category === cat).length;
                   const pct = summary.total_items > 0 ? (count / summary.total_items) * 100 : 0;
                   return (
                     <div key={cat} className="flex-1 flex flex-col items-center justify-end h-full group">
                       <div className="w-full bg-primary/20 rounded-t-md transition-all group-hover:bg-primary/40 relative flex flex-col items-center justify-start pt-2" style={{ height: `${Math.max(pct, 5)}%` }}>
                         <span className="text-xs font-bold -mt-6 bg-background/80 px-2 py-0.5 rounded text-foreground">{count}</span>
                       </div>
                       <span className="text-xs text-muted-foreground mt-3 font-medium text-center">{cat}</span>
                     </div>
                   );
                })}
             </div>
          </div>
        </div>
        
        <div className="space-y-3">
          <h2 className="text-sm font-heading font-bold text-muted-foreground uppercase tracking-wider">Recent Alerts</h2>
          <div className="glass-card p-4 h-64 overflow-y-auto space-y-3">
             {notifications.length === 0 ? (
               <div className="h-full flex items-center justify-center">
                 <p className="text-xs text-muted-foreground">No recent alerts.</p>
               </div>
             ) : (
               notifications.map(n => (
                 <div key={n.id} className="border-l-2 border-primary pl-3 py-1 bg-muted/30 rounded-r-md px-2">
                   <h4 className="text-xs font-bold text-foreground truncate">{n.title}</h4>
                   <p className="text-[10px] text-muted-foreground line-clamp-2 mt-1">{n.description}</p>
                 </div>
               ))
             )}
          </div>
        </div>
      </div>"""

content = content.replace(old_kpi, new_kpi)

with open("Inventory.tsx", "w", encoding="utf-8") as f:
    f.write(content)

print("Inventory.tsx patched successfully!")
