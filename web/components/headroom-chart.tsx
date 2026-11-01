"use client";

import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTheme } from "./theme";
import {
  apiGet,
  formatMoney,
  formatPeriod,
  formatRatio,
  type PeriodDetail,
  type PeriodSummary,
} from "../lib/api";

export interface HeadroomPoint {
  label: string;
  period_end: string;
  ratio: number | null;
  without: number | null;
  limit: number | null;
  breach: boolean;
  ratioLabel?: string;
  withoutLabel?: string;
  limitLabel?: string;
}

function savingsLabel(savings: number): string {
  if (savings >= 1_000_000 && savings % 1_000_000 === 0) {
    return `$${savings / 1_000_000}M`;
  }
  return formatMoney(savings);
}

export async function loadHeadroomPoints(): Promise<HeadroomPoint[]> {
  const { periods } = await apiGet<{
    ticker: string;
    periods: PeriodSummary[];
  }>("/company/SNBR/periods");
  const sorted = [...periods].sort((a, b) =>
    a.period_end < b.period_end ? -1 : 1,
  );
  const details = await Promise.all(
    sorted.map((p) =>
      apiGet<PeriodDetail>(`/company/SNBR/period/${p.period_end}`).catch(
        () => null,
      ),
    ),
  );
  return sorted.map((p, i) => {
    const scenarios = p.scenarios ?? [];
    const full =
      scenarios.length > 0
        ? scenarios.reduce((a, b) => (b.savings > a.savings ? b : a))
        : null;
    const none =
      scenarios.length > 0
        ? scenarios.reduce((a, b) => (b.savings < a.savings ? b : a))
        : null;
    const ratio = full?.net_leverage.ratio_2dp ?? p.net_leverage.ratio_2dp;
    const sensitivity =
      details[i]?.sensitivity_without_proforma?.net_leverage.ratio_2dp ?? null;
    const without =
      sensitivity ?? none?.net_leverage.ratio_2dp ?? p.net_leverage.ratio_2dp;
    const limit = p.net_leverage.threshold;
    const breach =
      ratio !== null && limit !== null ? ratio > limit : p.net_leverage.pass === false;
    const isLast = i === sorted.length - 1;
    let ratioLabel: string | undefined;
    let withoutLabel: string | undefined;
    if (full && none) {
      ratioLabel = `${formatRatio(full.net_leverage.ratio_2dp)} with ${savingsLabel(full.savings)} of savings`;
      withoutLabel = `${formatRatio(none.net_leverage.ratio_2dp)} without`;
    } else if (sensitivity !== null) {
      const proforma =
        details[i]?.components.find((c) => c.name === "Pro forma cost savings")
          ?.value ?? 0;
      ratioLabel = `${formatRatio(ratio)}, passing only with ${savingsLabel(proforma)} of projected savings`;
      withoutLabel = `${formatRatio(without)} without`;
    }
    return {
      label: formatPeriod(p.period_end),
      period_end: p.period_end,
      ratio,
      without,
      limit,
      breach,
      ratioLabel,
      withoutLabel,
      limitLabel: isLast && limit !== null ? `Limit ${formatRatio(limit)}` : undefined,
    };
  });
}

const PALETTE = {
  dark: {
    ink: "#E6ECE9",
    muted: "#9AA9A3",
    rule: "#2A3A43",
    breach: "#E05A60",
    surface: "#16232C",
    page: "#101A21",
  },
  light: {
    ink: "#15222C",
    muted: "#4A5A63",
    rule: "#C7D1CD",
    breach: "#B3242D",
    surface: "#FFFFFF",
    page: "#F2F5F3",
  },
} as const;

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: HeadroomPoint }[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  return (
    <div className="border border-rule bg-surface px-3 py-2 text-[13px]">
      <p className="font-medium">{point.label}</p>
      <p>Ratio {formatRatio(point.ratio)}</p>
      <p>Without projected savings {formatRatio(point.without)}</p>
      <p>Limit {formatRatio(point.limit)}</p>
    </div>
  );
}

type LabelProps = {
  x?: number | string;
  y?: number | string;
  index?: number;
  payload?: HeadroomPoint;
};

export function HeadroomChart({ points }: { points: HeadroomPoint[] }) {
  const { theme } = useTheme();
  const colors = PALETTE[theme];

  const renderDot = (props: {
    cx?: number;
    cy?: number;
    payload?: HeadroomPoint;
  }) => {
    const { cx, cy, payload } = props;
    if (cx === undefined || cy === undefined || !payload?.ratio)
      return <g key={props.payload?.period_end} />;
    const fill = payload.breach ? colors.breach : colors.ink;
    const r = payload.breach ? 5 : 3.5;
    return (
      <circle
        key={payload.period_end}
        cx={cx}
        cy={cy}
        r={r}
        fill={fill}
        stroke={colors.surface}
        strokeWidth={1}
      />
    );
  };

  function directLabel(
    key: "ratioLabel" | "withoutLabel" | "limitLabel",
    fill: string,
    anchor: "start" | "middle" | "end",
  ) {
    function DirectLabel(props: LabelProps) {
      const index = props.index ?? -1;
      const point = props.payload ?? points[index];
      const text = point?.[key];
      const x = Number(props.x);
      const y = Number(props.y);
      if (!text || !point || Number.isNaN(x) || Number.isNaN(y)) return <g />;
      const isLast =
        index === points.length - 1 ||
        point.period_end === points[points.length - 1]?.period_end;
      // Offsets keep labels off the lines. The April ratio label sits
      // above and left of its point, clear of the savings line that
      // arrives from below left and the dashed line above it.
      const dy =
        key === "ratioLabel" ? (isLast ? -12 : 18) : key === "limitLabel" ? 16 : -10;
      const dx =
        key === "limitLabel" ? -64 : key === "ratioLabel" && isLast ? -10 : 0;
      const labelLines =
        text.length > 30 && text.includes(", ")
          ? [text.slice(0, text.indexOf(", ") + 1),
             text.slice(text.indexOf(", ") + 2)]
          : [text];
      return (
        <text
          x={x + dx}
          y={y + dy}
          textAnchor={isLast ? "end" : anchor}
          fill={fill}
          fontSize={12}
          paintOrder="stroke"
          stroke={colors.page}
          strokeWidth={4}
          strokeLinejoin="round"
        >
          {labelLines.map((lineText, li) => (
            <tspan key={li} x={x + dx} dy={li === 0 ? 0 : 14}>
              {lineText}
            </tspan>
          ))}
        </text>
      );
    }
    return DirectLabel;
  }

  return (
    <figure>
      <div className="h-[320px] w-full" role="img" aria-label={ariaSummary(points)}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 28, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={colors.rule} vertical={false} />
            <XAxis
              dataKey="label"
              height={50}
              tickMargin={24}
              tick={{ fill: colors.muted, fontSize: 13 }}
              axisLine={{ stroke: colors.rule }}
              tickLine={{ stroke: colors.rule }}
            />
            <YAxis
              domain={[4, (dataMax: number) => dataMax + 0.5]}
              tick={{ fill: colors.muted, fontSize: 13 }}
              axisLine={{ stroke: colors.rule }}
              tickLine={{ stroke: colors.rule }}
              tickFormatter={(v: number) => `${v.toFixed(2)}x`}
              width={64}
            />
            <Tooltip content={<ChartTooltip />} />
            <Line
              type="stepAfter"
              dataKey="limit"
              name="Covenant limit"
              stroke={colors.muted}
              strokeWidth={1.5}
              dot={{ r: 2.5, fill: colors.muted, strokeWidth: 0 }}
              isAnimationActive={false}
            >
              <LabelList
                dataKey="limit"
                content={directLabel("limitLabel", colors.muted, "middle")}
              />
            </Line>
            <Line
              type="linear"
              dataKey="without"
              name="Without projected savings"
              stroke={colors.muted}
              strokeWidth={1.5}
              strokeDasharray="6 4"
              dot={{ r: 2.5, fill: colors.muted, strokeWidth: 0 }}
              isAnimationActive={false}
            >
              <LabelList
                dataKey="without"
                content={directLabel("withoutLabel", colors.muted, "middle")}
              />
            </Line>
            <Line
              type="linear"
              dataKey="ratio"
              name="Ratio"
              stroke={colors.ink}
              strokeWidth={2}
              isAnimationActive={false}
              dot={renderDot}
            >
              <LabelList
                dataKey="ratio"
                content={directLabel("ratioLabel", colors.ink, "middle")}
              />
            </Line>
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

function ariaSummary(points: HeadroomPoint[]): string {
  const parts = points.map((p) => {
    const verdict = p.ratio !== null && p.limit !== null && p.ratio > p.limit
      ? "breach"
      : "pass";
    return `${p.label}: ratio ${formatRatio(p.ratio)} against a limit of ${formatRatio(p.limit)}, ${verdict}`;
  });
  return `Net leverage headroom chart. ${parts.join(". ")}`;
}
