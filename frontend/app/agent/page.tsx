import pageStyles from '../page.module.css';
import agentStyles from './agent.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { AgentChatScreen } from '@/components/agent/AgentChatScreen';

export default function AgentPage() {
  return (
    <RouteGuard redirectTo="/agent">
      <div className={`${pageStyles.screen} ${agentStyles.screen}`}>
        <AppHeader title="DocSuri" />
        <AgentChatScreen />
      </div>
      <BottomNav />
    </RouteGuard>
  );
}
