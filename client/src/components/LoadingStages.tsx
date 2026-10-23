import { useEffect, useState } from "react";

interface Props {
  messages: readonly string[];
  intervalMs?: number;
  className?: string;
}

export default function LoadingStages({
  messages,
  intervalMs = 1500,
  className = "",
}: Props) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (messages.length < 2) return;
    const id = window.setInterval(() => {
      setIndex((current) => (current + 1) % messages.length);
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [messages, intervalMs]);

  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-center justify-center gap-2.5 ${className}`}
    >
      <span className="flex items-center gap-1" aria-hidden="true">
        <span className="h-1.5 w-1.5 rounded-full bg-sky-500 animate-pulse" />
        <span className="h-1.5 w-1.5 rounded-full bg-sky-500 animate-pulse [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 rounded-full bg-sky-500 animate-pulse [animation-delay:300ms]" />
      </span>
      <span
        key={index}
        className="animate-[slideDownFade_0.35s_ease-out]"
      >
        {messages[index] ?? messages[0] ?? ""}
      </span>
    </div>
  );
}
