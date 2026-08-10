"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface MetricPoint {
  time: string;
  cpu: number;
  ram: number;
  network?: number;
}

interface CpuRamChartProps {
  data: MetricPoint[];
  isLive?: boolean;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="rounded-2xl px-5 py-4 text-xs"
      style={{
        background: "linear-gradient(180deg, #16161a 0%, #0b0b0d 100%)",
        border: "1px solid rgba(244,240,230,0.1)",
        boxShadow:
          "0 20px 40px -10px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06)",
      }}
    >
      <p className="mb-2.5 font-semibold font-mono text-paper/70 text-[11px] tracking-wider uppercase border-b pb-2" style={{ borderColor: "rgba(244,240,230,0.08)" }}>
        {label}
      </p>
      <div className="space-y-2">
        {payload.map((entry: any, i: number) => (
          <p
            key={i}
            className="flex items-center justify-between gap-6 font-mono"
          >
            <span className="flex items-center gap-2 text-paper/60">
              <span
                className="h-2 w-2 rounded-full"
                style={{
                  background: entry.color,
                  boxShadow: `0 0 8px ${entry.color}60`,
                }}
              />
              {entry.name}
            </span>
            <span className="font-bold" style={{ color: entry.color }}>
              {entry.value.toFixed(1)}
              {entry.name === "Network" ? " MB" : "%"}
            </span>
          </p>
        ))}
      </div>
    </div>
  );
};

export default function CpuRamChart({
  data,
  isLive = true,
}: CpuRamChartProps) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart
        data={data}
        margin={{ top: 10, right: 10, left: -10, bottom: 0 }}
      >
        <defs>
          <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffe600" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#ffe600" stopOpacity={0.01} />
          </linearGradient>
          <linearGradient id="ramGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#c8a8ff" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#c8a8ff" stopOpacity={0.01} />
          </linearGradient>
          <linearGradient id="netGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#e8462c" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#e8462c" stopOpacity={0.01} />
          </linearGradient>
        </defs>
        <CartesianGrid
          strokeDasharray="3 4"
          stroke="rgba(244,240,230,0.05)"
          vertical={false}
        />
        <XAxis
          dataKey="time"
          tick={{ fill: "#8a8780", fontSize: 10, fontFamily: "'JetBrains Mono', monospace", fontWeight: 500 }}
          tickLine={false}
          axisLine={false}
          tickMargin={10}
        />
        <YAxis
          tick={{ fill: "#8a8780", fontSize: 10, fontFamily: "'JetBrains Mono', monospace", fontWeight: 500 }}
          tickLine={false}
          axisLine={false}
          domain={[0, 100]}
          tickFormatter={(v) => `${v}`}
          tickMargin={10}
        />
        <Tooltip
          content={<CustomTooltip />}
          cursor={{
            stroke: "rgba(244,240,230,0.08)",
            strokeWidth: 1,
            strokeDasharray: "4 4",
          }}
        />
        <Legend
          wrapperStyle={{
            fontSize: 11,
            color: "#8a8780",
            paddingTop: "10px",
            fontFamily: "'JetBrains Mono', monospace",
          }}
          iconType="circle"
          iconSize={7}
        />
        <Area
          type="monotone"
          dataKey="cpu"
          name="CPU"
          stroke="#ffe600"
          strokeWidth={2}
          fill="url(#cpuGrad)"
          animationDuration={isLive ? 300 : 800}
          isAnimationActive={true}
        />
        <Area
          type="monotone"
          dataKey="ram"
          name="RAM"
          stroke="#c8a8ff"
          strokeWidth={2}
          fill="url(#ramGrad)"
          animationDuration={isLive ? 300 : 800}
          isAnimationActive={true}
        />
        <Area
          type="monotone"
          dataKey="network"
          name="Network"
          stroke="#e8462c"
          strokeWidth={2}
          fill="url(#netGrad)"
          animationDuration={isLive ? 300 : 800}
          isAnimationActive={true}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
