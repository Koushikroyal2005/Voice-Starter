'use client';

import { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import { DisconnectReason, RoomEvent } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import { toast } from 'sonner';
import { useAgent, useSessionContext } from '@livekit/components-react';
import { AgentSessionView_01 } from '@/components/agents-ui/blocks/agent-session-view-01';
import { WelcomeView } from '@/components/app/welcome-view';

const MotionWelcomeView = motion.create(WelcomeView);
const MotionSessionView = motion.create(AgentSessionView_01);

const VIEW_MOTION_PROPS = {
  variants: {
    visible: {
      opacity: 1,
    },
    hidden: {
      opacity: 0,
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.5,
    ease: 'linear',
  },
};

interface ViewControllerProps {
  isVideoInputSupported: boolean;
}

export function ViewController({ isVideoInputSupported }: ViewControllerProps) {
  const { isConnected, start, prepareConnection, room } = useSessionContext();
  const [isStarting, setIsStarting] = useState(false);
  const startingRef = useRef(false);
  const agent = useAgent();
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const onDisconnected = (reason?: DisconnectReason) => {
      if (reason !== DisconnectReason.CLIENT_INITIATED) {
        toast.warning('Call disconnected', {
          description: 'Select Start call to reconnect. Check that the Python worker is running.',
        });
      }
    };
    room.on(RoomEvent.Disconnected, onDisconnected);
    return () => {
      room.off(RoomEvent.Disconnected, onDisconnected);
    };
  }, [room]);

  async function handleStartCall() {
    if (startingRef.current) return;
    startingRef.current = true;
    setIsStarting(true);
    try {
      // Validate token setup before the SDK requests microphone access.
      await prepareConnection();
      await start();
    } catch {
      // Release any partially acquired microphone/room state before another attempt.
      await room.disconnect().catch(() => undefined);
      toast.error('Could not start call', {
        description:
          'Check microphone permission, network access, root .env.local, and the Python worker. Then try again.',
      });
    } finally {
      startingRef.current = false;
      setIsStarting(false);
    }
  }

  return (
    <AnimatePresence mode="wait">
      {/* Welcome view */}
      {!isConnected && (
        <MotionWelcomeView
          key="welcome"
          {...VIEW_MOTION_PROPS}
          startButtonText={isStarting ? 'Connecting...' : 'Start call'}
          isStarting={isStarting}
          onStartCall={handleStartCall}
        />
      )}
      {/* Session view */}
      {isConnected && (
        <MotionSessionView
          key="session-view"
          {...VIEW_MOTION_PROPS}
          preConnectMessage={
            agent.isConnected ? 'Agent is listening, ask it a question' : 'Waiting for agent'
          }
          supportsChatInput={true}
          supportsVideoInput={isVideoInputSupported}
          supportsScreenShare={isVideoInputSupported}
          isPreConnectBufferEnabled={true}
          themeMode={resolvedTheme === 'dark' ? 'dark' : 'light'}
          className="fixed inset-0"
        />
      )}
    </AnimatePresence>
  );
}
