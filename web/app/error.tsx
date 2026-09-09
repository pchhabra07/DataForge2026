"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="stage">
      <div className="agent-line">
        <p>Something broke: {error.message}</p>
        <button className="deck-btn" onClick={reset}>
          Retry
        </button>
      </div>
    </div>
  );
}
