import { ReactNode, useState } from "react";

export type Column<T> = {
  key: string;
  label: string;
  num?: boolean;
  value?: (row: T) => number | string | null | undefined;
  render?: (row: T) => ReactNode;
  className?: (row: T) => string | undefined;
  title?: string;
};

export function SortableTable<T>({ rows, columns, rowKey, initialSort, initialDesc = true, maxHeight }: {
  rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string; initialSort?: string; initialDesc?: boolean; maxHeight?: number;
}) {
  const [sort, setSort] = useState<{ key: string | null; desc: boolean }>({ key: initialSort ?? null, desc: initialDesc });
  const column = columns.find((c) => c.key === sort.key);
  const read = (row: T, c: Column<T>) => (c.value ? c.value(row) : (row as Record<string, unknown>)[c.key]) as number | string | null | undefined;
  const sorted = column ? [...rows].sort((a, b) => {
    const x = read(a, column), y = read(b, column);
    if (x === y) return 0;
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    return (x < y ? -1 : 1) * (sort.desc ? -1 : 1);
  }) : rows;

  return (
    <div className="table-wrap" style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}>
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.num ? "num" : undefined} title={c.title}
                  aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : undefined}
                  onClick={() => setSort({ key: c.key, desc: sort.key === c.key ? !sort.desc : true })}>
                {c.label}{sort.key === c.key ? (sort.desc ? " ↓" : " ↑") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c) => (
                <td key={c.key} className={[c.num ? "num" : "", c.className?.(row) ?? ""].join(" ").trim() || undefined}>
                  {c.render ? c.render(row) : (read(row, c) ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
