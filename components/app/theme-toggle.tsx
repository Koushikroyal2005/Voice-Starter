'use client';

import { useTheme } from 'next-themes';
import { MonitorIcon, MoonIcon, SunIcon } from '@phosphor-icons/react';
import { cn } from '@/lib/shadcn/utils';

interface ThemeToggleProps {
  className?: string;
}

export function ThemeToggle({ className }: ThemeToggleProps) {
  const { theme, setTheme } = useTheme();

  return (
    <div
      className={cn(
        'text-foreground bg-background flex w-full flex-row justify-end divide-x overflow-hidden rounded-full border',
        className
      )}
    >
      <span className="sr-only">Color scheme toggle</span>
      <button
        type="button"
        aria-pressed={theme === 'dark'}
        onClick={() => setTheme('dark')}
        className="focus-visible:ring-ring min-h-11 min-w-11 cursor-pointer p-3 focus-visible:ring-2 focus-visible:ring-inset"
      >
        <span className="sr-only">Enable dark color scheme</span>
        <MoonIcon
          suppressHydrationWarning
          size={16}
          weight="bold"
          className={cn(theme !== 'dark' && 'opacity-25')}
        />
      </button>
      <button
        type="button"
        aria-pressed={theme === 'light'}
        onClick={() => setTheme('light')}
        className="focus-visible:ring-ring min-h-11 min-w-11 cursor-pointer p-3 focus-visible:ring-2 focus-visible:ring-inset"
      >
        <span className="sr-only">Enable light color scheme</span>
        <SunIcon
          suppressHydrationWarning
          size={16}
          weight="bold"
          className={cn(theme !== 'light' && 'opacity-25')}
        />
      </button>
      <button
        type="button"
        aria-pressed={theme === 'system'}
        onClick={() => setTheme('system')}
        className="focus-visible:ring-ring min-h-11 min-w-11 cursor-pointer p-3 focus-visible:ring-2 focus-visible:ring-inset"
      >
        <span className="sr-only">Enable system color scheme</span>
        <MonitorIcon
          suppressHydrationWarning
          size={16}
          weight="bold"
          className={cn(theme !== 'system' && 'opacity-25')}
        />
      </button>
    </div>
  );
}
