import { App } from '@/components/app/app';

// Resolve server configuration at request time; credentials never enter client props.
export const dynamic = 'force-dynamic';

export default function Page() {
  return (
    <App
      tokenEndpoint="/api/token"
      agentName={process.env.AGENT_NAME?.trim() || undefined}
      isVideoInputSupported={false}
    />
  );
}
