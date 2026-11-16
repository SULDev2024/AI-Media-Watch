import { useLocation, Link } from 'react-router-dom'
import { ChevronRight, Plus, ShieldCheck } from 'lucide-react'

const names: Record<string, string> = { queue: 'Detection queue', analyze: 'Analyze content', investigate: 'Investigations', agents: 'Agent workspace', graph: 'Network graph', biometrics: 'Biometrics', analytics: 'Analytics', metrics: 'Model performance', validation: 'Validation', 'feedback-log': 'Feedback log', report: 'Evidence report', cases: 'Case file' }
export function TopBar() {
  const { pathname } = useLocation()
  return <header className="topbar"><div className="breadcrumb"><ShieldCheck size={16} /><span>Workspace</span><ChevronRight size={13} /><strong>{names[pathname.split('/')[1]] || 'Overview'}</strong></div><div className="topbar-actions"><span className="private-label"><span />Authenticated workspace</span><Link to="/analyze" className="button-primary button-small"><Plus size={15} />New analysis</Link></div></header>
}
