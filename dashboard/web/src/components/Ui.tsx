import { cn, toneClass } from "../lib/utils";

export function Button({ className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex h-9 items-center justify-center rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 shadow-panel transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
}

export function Panel({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <section className={cn("rounded-lg border border-slate-200 bg-white p-4 shadow-panel", className)} {...props} />;
}

export function Badge({ tone = "neutral", children }: { tone?: string; children: React.ReactNode }) {
  return <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1", toneClass(tone))}>{children}</span>;
}

type MetricCardProps = {
  label: string;
  value: React.ReactNode;
  source: string;
  tone?: string;
  onClick?: () => void;
  ariaLabel?: string;
  title?: string;
};

export function MetricCard({ label, value, source, tone = "neutral", onClick, ariaLabel, title }: MetricCardProps) {
  const content = (
    <>
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-slate-600">{label}</p>
        <Badge tone={tone}>{tone === "neutral" ? "info" : tone}</Badge>
      </div>
      <div className="mt-3 text-2xl font-semibold text-slate-950">{value}</div>
      <p className="mt-2 truncate text-xs text-slate-500" title={source}>{source}</p>
    </>
  );
  if (onClick) {
    return (
      <button
        type="button"
        aria-label={ariaLabel ?? `Open ${label} details`}
        title={title ?? `Open ${label} details`}
        onClick={onClick}
        className="min-h-[112px] rounded-lg border border-slate-200 bg-white p-4 text-left shadow-panel transition hover:border-blue-300 hover:bg-blue-50/40 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
      >
        {content}
      </button>
    );
  }
  return (
    <Panel className="min-h-[112px]">
      {content}
    </Panel>
  );
}
