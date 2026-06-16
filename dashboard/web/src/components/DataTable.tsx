import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { ArrowUpDown } from "lucide-react";
import { formatMelbourneDateTime, humanizeLabel, humanizeValue, isTimestampColumn } from "../lib/utils";

interface DataTableProps {
  rows: Array<Record<string, unknown>>;
  columns: string[];
  emptyLabel?: string;
  clientRows?: Array<Record<string, unknown>>;
  onRowClick?: (row: Record<string, unknown>) => void;
  rowAriaLabel?: (row: Record<string, unknown>) => string;
}

function faviconCandidates(row: Record<string, unknown>) {
  const candidates = row.favicon_candidates_json;
  const output: string[] = [];
  const push = (candidate: unknown) => {
    if (typeof candidate === "string" && candidate.trim()) output.push(candidate.trim());
  };
  if (Array.isArray(candidates)) {
    candidates.forEach(push);
  } else if (typeof candidates === "string" && candidates.trim()) {
    try {
      const parsed = JSON.parse(candidates);
      if (Array.isArray(parsed)) {
        parsed.forEach(push);
      }
    } catch {
      push(candidates);
    }
  }
  const primary = String(row.favicon_url ?? "");
  if (primary.trim()) output.unshift(primary.trim());
  const canonicalHost = String(row.canonical_host ?? "").replace(/^https?:\/\//, "").split("/")[0].trim();
  if (canonicalHost) {
    output.push(`https://www.google.com/s2/favicons?domain=${canonicalHost}&sz=64`);
    output.push(`https://icons.duckduckgo.com/ip3/${canonicalHost}.ico`);
  }
  return Array.from(new Set(output));
}

function FaviconCellMark({ row }: { row: Record<string, unknown> }) {
  const candidates = faviconCandidates(row);
  const [candidateIndex, setCandidateIndex] = useState(0);
  const src = candidates[candidateIndex] ?? "";
  const name = String(row.client_name ?? row.client_slug ?? "Client");
  const initial = name.trim().charAt(0).toUpperCase() || "C";
  if (!src) {
    return <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-100 text-[10px] font-semibold text-slate-600 ring-1 ring-slate-200">{initial}</span>;
  }
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 ring-1 ring-slate-200">
      <img
        src={src}
        alt=""
        className="h-5 w-5 rounded-sm object-contain"
        loading="lazy"
        onError={() => setCandidateIndex((index) => Math.min(index + 1, candidates.length))}
      />
    </span>
  );
}

const clientBrandingKeys = ["client_name", "canonical_host", "favicon_url", "favicon_source", "favicon_candidates_json"] as const;

function withClientBranding(rows: Array<Record<string, unknown>>, clientRows: Array<Record<string, unknown>>) {
  if (!clientRows.length) return rows;
  const clientsBySlug = new Map<string, Record<string, unknown>>();
  clientRows.forEach((client) => {
    const slug = String(client.client_slug ?? "");
    if (slug) clientsBySlug.set(slug, client);
  });
  return rows.map((row) => {
    const client = clientsBySlug.get(String(row.client_slug ?? ""));
    if (!client) return row;
    const enriched = { ...row };
    clientBrandingKeys.forEach((key) => {
      if (enriched[key] === null || enriched[key] === undefined || enriched[key] === "") enriched[key] = client[key];
    });
    return enriched;
  });
}

function formatCurrency(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return humanizeValue(value);
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 }).format(numeric);
}

function formatRate(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return humanizeValue(value);
  return `${(Math.abs(numeric) <= 1 ? numeric * 100 : numeric).toFixed(1)}%`;
}

export function DataTable({ rows, columns, emptyLabel = "No rows", clientRows = [], onRowClick, rowAriaLabel }: DataTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const displayRows = useMemo(() => withClientBranding(rows, clientRows), [rows, clientRows]);
  const defs = useMemo<ColumnDef<Record<string, unknown>>[]>(
    () =>
      columns.map((column) => ({
        accessorKey: column,
        header: ({ column: tableColumn }) => (
          <button className="flex items-center gap-1 text-left" onClick={() => tableColumn.toggleSorting()}>
            <span>{humanizeLabel(column)}</span>
            <ArrowUpDown className="h-3.5 w-3.5 text-slate-400" />
          </button>
        ),
        cell: ({ getValue, row }) => {
          const value = getValue();
          if (column === "client_name" || column === "client_slug") {
            const original = row.original;
            const mark = <FaviconCellMark row={original} />;
            if (column === "client_name" && original.client_slug) {
              return (
                <span className="flex min-w-0 items-center gap-2">
                  {mark}
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-slate-900">{String(value ?? original.client_name ?? original.client_slug)}</span>
                    <span className="block truncate text-xs text-slate-500">{String(original.client_slug)}</span>
                  </span>
                </span>
              );
            }
            return (
              <span className="flex min-w-0 items-center gap-2">
                {mark}
                <span className="truncate">{humanizeValue(value ?? original.client_slug ?? original.client_name ?? "—")}</span>
              </span>
            );
          }
          if (typeof value === "boolean") return humanizeValue(value);
          if (value === null || value === undefined || value === "") return "—";
          if (isTimestampColumn(column)) return formatMelbourneDateTime(value);
          if (column.endsWith("_amount_aud") || column.endsWith("_total_aud") || column === "cost_per_month_aud") return formatCurrency(value);
          if (column.endsWith("_rate") || column.endsWith("_ratio")) return formatRate(value);
          if (column.endsWith("_url")) {
            const href = String(value);
            return (
              <a className="font-medium text-blue-700 hover:text-blue-900" href={href} target="_blank" rel="noreferrer">
                {href}
              </a>
            );
          }
          if (column.endsWith("_mom") || column.endsWith("_yoy") || column === "mom" || column === "yoy") {
            const label = String(value);
            let className = "font-medium text-slate-500";
            if (label.startsWith("+")) className = "font-semibold text-emerald-700";
            if (label.startsWith("-")) className = "font-semibold text-rose-700";
            if (label === "new") className = "font-semibold text-blue-700";
            if (label === "0.0%") className = "font-medium text-slate-600";
            return <span className={className}>{label}</span>;
          }
          return humanizeValue(value);
        }
      })),
    [columns]
  );
  const table = useReactTable({ data: displayRows, columns: defs, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });

  if (!rows.length) return <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">{emptyLabel}</div>;

  return (
    <div className="overflow-hidden rounded-md border border-slate-200">
      <div className="max-h-[560px] overflow-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="sticky top-0 bg-slate-50">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-700">
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                tabIndex={onRowClick ? 0 : undefined}
                role={onRowClick ? "button" : undefined}
                aria-label={onRowClick ? rowAriaLabel?.(row.original) ?? "Open row details" : undefined}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                onKeyDown={onRowClick ? (event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onRowClick(row.original);
                  }
                } : undefined}
                className={onRowClick ? "cursor-pointer hover:bg-blue-50 focus:bg-blue-50 focus:outline-none" : "hover:bg-slate-50"}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="max-w-[320px] truncate px-3 py-2 text-slate-700" title={String(cell.getValue() ?? "")}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
