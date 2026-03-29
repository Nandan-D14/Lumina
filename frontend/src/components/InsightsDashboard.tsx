import React, { useEffect, useMemo, useState } from 'react';
import { InsightPackage, Visualization } from '../types';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, Title, Tooltip, Legend, ArcElement } from 'chart.js';
import { Bar, Line, Pie } from 'react-chartjs-2';
import { ChartControls } from './ChartControls';
import { ExternalLink, Database, Layers, Sparkles } from 'lucide-react';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Title, Tooltip, Legend, ArcElement);

interface InsightsDashboardProps {
  data: InsightPackage | null;
  isLoading: boolean;
  liveSteps?: string[];
  onSampleClick?: (prompt: string) => void;
}

const TAILWIND_CDN_SCRIPT_RE = /<script\b[^>]*src=["']https?:\/\/cdn\.tailwindcss\.com[^"']*["'][^>]*><\/script>/gi;
const INLINE_SCRIPT_RE = /<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;

function prepareAdvancedReport(rawReport: string | null | undefined): { srcDoc: string | null; warnings: string[] } {
  if (!rawReport || !rawReport.trim()) {
    return { srcDoc: null, warnings: [] };
  }

  const warnings: string[] = [];
  let normalized = rawReport.trim();
  const withoutTailwind = normalized.replace(TAILWIND_CDN_SCRIPT_RE, '');

  if (withoutTailwind !== normalized) {
    warnings.push('Removed Tailwind CDN script from advanced report preview.');
    normalized = withoutTailwind;
  }

  INLINE_SCRIPT_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = INLINE_SCRIPT_RE.exec(normalized)) !== null) {
    const scriptBody = (match[1] || '').trim();
    if (!scriptBody) {
      continue;
    }
    try {
      // Parse only; do not execute.
      // eslint-disable-next-line no-new-func
      new Function(scriptBody);
    } catch {
      warnings.push('Advanced report JavaScript may be partially invalid. Rendering in best-effort mode.');
    }
  }

  return { srcDoc: normalized, warnings };
}

export function InsightsDashboard({ data, isLoading, liveSteps = [], onSampleClick }: InsightsDashboardProps) {
  const [chartOverride, setChartOverride] = useState<'bar' | 'line' | 'pie'>('bar');
  const [advancedReportWarning, setAdvancedReportWarning] = useState<string | null>(null);

  const chartVisualizations = useMemo(() => {
    if (!data) return [];
    return (data.visualizations || []).filter(
      (vis) => vis.kind !== 'table' && Array.isArray(vis.labels) && Array.isArray(vis.values) && vis.labels.length > 0 && vis.values.length > 0,
    );
  }, [data]);

  const preparedAdvancedReport = useMemo(
    () => prepareAdvancedReport(data?.advanced_html_report),
    [data?.advanced_html_report],
  );

  useEffect(() => {
    setAdvancedReportWarning(null);
  }, [preparedAdvancedReport.srcDoc]);

  if (isLoading) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center p-12">
        <div className="w-16 h-16 border-4 border-[#007AFF]/20 border-t-[#007AFF] rounded-full animate-spin mb-6"></div>
        <h3 className="text-xl font-medium text-gray-900 mb-2">Analyzing Inputs</h3>
        <p className="text-gray-500 max-w-sm text-center mb-6">
          Our ADK cognitive engine is extracting entities, resolving metrics, and assembling your insight package.
        </p>
        
        {liveSteps.length > 0 && (
          <div className="w-full max-w-md bg-white border border-gray-100 rounded-2xl p-4 shadow-sm h-48 overflow-y-auto mt-4 text-sm font-mono text-gray-600 space-y-2">
            {liveSteps.map((step, idx) => (
              <div key={idx} className="flex gap-2 items-start py-1 border-b border-gray-50 last:border-0 opacity-80 slide-in-bottom">
                <span className="text-[#007AFF] font-bold">&gt;</span>
                <span>{step}</span>
              </div>
            ))}
            <div className="animate-pulse flex gap-2 items-start py-1 opacity-50">
                <span className="text-[#007AFF] font-bold">&gt;</span>
                <span className="w-2 h-4 bg-[#007AFF] inline-block"></span>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center text-center p-12">
        <div className="p-4 bg-gray-50 rounded-2xl mb-6 border border-gray-100">
          <Layers size={32} className="text-gray-400" />
        </div>
        <h3 className="text-xl font-medium text-gray-900 mb-2">Workspace Empty</h3>
        <p className="text-gray-500 max-w-sm mb-8">
          Submit text, URLs, or files via the input pad to generate a structured analysis panel.
        </p>

        <div className="max-w-2xl w-full grid grid-cols-1 md:grid-cols-2 gap-4">
          <button 
            onClick={() => onSampleClick?.("Build an interactive stock history timeline of Nvidia over the last 5 years. I should be able to hover my mouse over the timeline to see the stock price at that time. Additionally, annotate the graph with interesting events -- earnings calls, analyst price target changes, insider trades, major news or product launches...anything that would be of interest to someone following the stock. Each annotation should have a little bubble I can hover over to see more information about that event. Make the whole thing themed very strongly with the company brand colors and logo. The webpage should have just one page, the interactive timeline (don't add any extra information or views).")}
            className="text-left p-4 rounded-2xl border border-gray-200 bg-white hover:border-[#007AFF] hover:bg-blue-50/50 transition-all group"
          >
            <h4 className="font-semibold text-gray-900 mb-2 group-hover:text-[#007AFF]">Nvidia Timeline 📈</h4>
            <p className="text-xs text-gray-500 line-clamp-3 leading-relaxed">
              Build an interactive stock history timeline of Nvidia over the last 5 years with hover price info and annotations for earnings calls, trades, and news tailored with brand colors.
            </p>
          </button>

          <button 
            onClick={() => onSampleClick?.("Create a website of the top 50 largest publicly traded companies by market cap that visualizes both the standard financial information they publish in their SEC filings but also the interesting non-financial information related to their core business. For example, a company like tesla would include visualizations for deployment of supercharger sites over time, energy storage deployed by year, in-house battery cell production by year, etc. There should be multiple interesting visuals for every company - don't be afraid to include some really niche ones that are either published by the company or analysts covering them. For stats that are relevant to multiple companies (e.g. deployment of data centers by year in GW), provide an option to compare that specific stat across multiple companies with them visualized on the same chart")}
            className="text-left p-4 rounded-2xl border border-gray-200 bg-white hover:border-[#007AFF] hover:bg-blue-50/50 transition-all group"
          >
            <h4 className="font-semibold text-gray-900 mb-2 group-hover:text-[#007AFF]">Top 50 Giants Explorer 🌐</h4>
            <p className="text-xs text-gray-500 line-clamp-3 leading-relaxed">
              Create a website of the top 50 largest publicly traded companies visualizing SEC financials alongside non-financial insights (e.g., Tesla superchargers).
            </p>
          </button>
            <button
              onClick={() => onSampleClick?.("Build me an interactive dashboard to visualize key macroeconomic data from FRED. I want it to focus on the 2 year, 10 year, fed funds effective rate, and 30 year mortgage rate. The dashboard should use shadcn UI combined with recharts. It should look like a bloomberg terminal. Use tailwindcss to style.")}
              className="text-left p-4 rounded-2xl border border-gray-200 bg-white hover:border-[#007AFF] hover:bg-blue-50/50 transition-all group"
            >
              <h4 className="font-semibold text-gray-900 mb-2 group-hover:text-[#007AFF]">Macro Terminal 📈</h4>
              <p className="text-xs text-gray-500 line-clamp-3 leading-relaxed">
                Build me an interactive dashboard to visualize key macroeconomic data from FRED. I want it to focus on the 2 year, 10 year, fed funds effective rate, and 30 year mortgage rate. The dashboard should use shadcn UI combined with recharts. It should look like a bloomberg terminal. Use tailwindcss to style.
              </p>
            </button>
            <button
              onClick={() => onSampleClick?.("Write an elegant full page web dashboard to analyze, pivot, and view a CSV file.")}
              className="text-left p-4 rounded-2xl border border-gray-200 bg-white hover:border-[#007AFF] hover:bg-blue-50/50 transition-all group"
            >
              <h4 className="font-semibold text-gray-900 mb-2 group-hover:text-[#007AFF]">CSV Analysis Pivot 📊</h4>
              <p className="text-xs text-gray-500 line-clamp-3 leading-relaxed">
                Write an elegant full page web dashboard to analyze, pivot, and view a CSV file.
              </p>
            </button>
          </div>
        </div>
    );
  }

  const renderChart = (vis: Visualization) => {
    if (!vis.labels || !vis.values) return null;
    
    // Auto-override to Pie if the ADK suggests pie internally, else allow manual override
    const typeToUse = vis.kind === 'pie' ? 'pie' : chartOverride;

    const chartData = {
      labels: vis.labels,
      datasets: [
        {
          label: vis.title,
          data: vis.values,
          backgroundColor: typeToUse === 'pie' 
            ? ['#007AFF', '#5856D6', '#FF9500', '#FF2D55', '#34C759']
            : 'rgba(0, 122, 255, 0.8)',
          borderColor: typeToUse === 'pie' ? '#ffffff' : '#007AFF',
          borderWidth: typeToUse === 'pie' ? 2 : 1,
          borderRadius: typeToUse === 'bar' ? 6 : 0,
        },
      ],
    };

    const options = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: typeToUse === 'pie', position: 'right' as const },
      },
      scales: typeToUse === 'pie' ? {} : {
        y: { 
          beginAtZero: true,
          grid: { color: '#f2f2f7', drawBorder: false }
        },
        x: {
          grid: { display: false }
        }
      },
    };

    return (
      <div className="h-64 mt-4 relative">
        {typeToUse === 'bar' && <Bar data={chartData} options={options} />}
        {typeToUse === 'line' && <Line data={chartData} options={options} />}
        {typeToUse === 'pie' && <Pie data={chartData} options={options} />}
      </div>
    );
  };

  const handleAdvancedReportLoad = (event: React.SyntheticEvent<HTMLIFrameElement>) => {
    try {
      const doc = event.currentTarget.contentDocument;
      if (!doc) {
        setAdvancedReportWarning('Advanced report loaded, but preview inspection is unavailable.');
        return;
      }

      // Give embedded scripts a short window to initialize charts.
      window.setTimeout(() => {
        try {
          const hasCanvas = !!doc.querySelector('canvas');
          const hasSvg = !!doc.querySelector('svg');
          const bodyText = (doc.body?.innerText || '').toLowerCase();
          const hasNoDataMarker = bodyText.includes('no chart-ready visualization data');

          if ((!hasCanvas && !hasSvg) || hasNoDataMarker) {
            setAdvancedReportWarning('Advanced report rendered without visible charts. Showing structured charts below when available.');
            return;
          }

          setAdvancedReportWarning(null);
        } catch {
          setAdvancedReportWarning('Advanced report loaded, but chart preview validation failed.');
        }
      }, 300);
    } catch {
      setAdvancedReportWarning('Advanced report loaded, but chart preview validation failed.');
    }
  };

  return (
    <div className="w-full space-y-6 pb-20 animate-in fade-in slide-in-from-bottom-4 duration-500">

      {/* Advanced Code Run (If present) */}
      {(data.advanced_html_report || preparedAdvancedReport.warnings.length > 0) && (
        <div className="apple-card p-6 flex flex-col gap-4 border border-blue-100 bg-blue-50/10">
          <div className="flex items-center gap-2">
            <Sparkles className="text-purple-500" size={20} />
            <h2 className="text-xl font-semibold tracking-tight">Advanced Live Analysis</h2>
          </div>
          <p className="text-sm text-gray-500">
            This module was dynamically generated and rendered live by the ADK pipeline.
          </p>
          {preparedAdvancedReport.srcDoc ? (
            <div className="w-full overflow-hidden rounded-xl bg-white border border-gray-100 shadow-inner">
              <iframe
                 srcDoc={preparedAdvancedReport.srcDoc}
                 className="w-full"
                 style={{ height: '700px' }}
                 sandbox="allow-scripts"
                 onLoad={handleAdvancedReportLoad}
              />
            </div>
          ) : (
            <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
              Advanced report preview was skipped due to invalid generated HTML/JS. Structured results are still rendered below.
            </div>
          )}
          {[...preparedAdvancedReport.warnings, ...(advancedReportWarning ? [advancedReportWarning] : [])].map((warning, idx) => (
            <div key={`${warning}-${idx}`} className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
              {warning}
            </div>
          ))}
        </div>
      )}

      {/* 1. Executive Summary */}
      <div className="apple-card p-8">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="text-[#007AFF]" size={20} />
          <h2 className="text-xl font-semibold tracking-tight">Executive Summary</h2>
        </div>
        <p className="text-lg text-gray-700 leading-relaxed font-medium mb-6">
          {data.summary}
        </p>
        
        {data.insights && data.insights.length > 0 && (
          <ul className="space-y-3">
            {data.insights.map((insight, idx) => (
              <li key={idx} className="flex gap-3 text-gray-600 leading-relaxed">
                <span className="text-[#007AFF] mt-1">•</span>
                {insight}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 2. Key Metrics Row */}
      {data.metrics && data.metrics.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {data.metrics.map((m, idx) => (
            <div key={idx} className="apple-card p-6 flex flex-col justify-between">
              <span className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-2">{m.label}</span>
              <span className="text-3xl font-bold tracking-tight text-gray-900">{m.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* 3. Visualizations & Tables Matrix */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Render Charts */}
        {chartVisualizations.map((vis) => (
          <div key={vis.id} className="apple-card p-6 flex flex-col">
            <div className="flex justify-between items-start mb-2">
              <div>
                <h3 className="font-semibold text-lg text-gray-900">{vis.title}</h3>
                <p className="text-sm text-gray-500 mt-1">{vis.reason}</p>
              </div>
              {vis.kind !== 'pie' && vis.kind !== 'table' && (
                <ChartControls 
                  currentType={chartOverride} 
                  onControlChange={(t) => setChartOverride(t)} 
                />
              )}
            </div>
            {renderChart(vis)}
          </div>
        ))}

        {data.tables && data.tables.slice(0, 2).map((table, tableIdx) => (
          <div key={`${table.name}-${tableIdx}`} className="apple-card p-6">
            <h3 className="font-semibold text-lg text-gray-900 mb-1">{table.name || `Table ${tableIdx + 1}`}</h3>
            <p className="text-sm text-gray-500 mb-3">Detailed extracted rows from uploaded source.</p>
            <div className="overflow-auto border border-gray-100 rounded-xl max-h-72">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    {table.columns.map((col, idx) => (
                      <th key={`${col}-${idx}`} className="text-left px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500 whitespace-nowrap">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.slice(0, 25).map((row, rowIdx) => (
                    <tr key={rowIdx} className="border-t border-gray-100">
                      {table.columns.map((_, colIdx) => (
                        <td key={colIdx} className="px-3 py-2 text-gray-700 whitespace-nowrap">
                          {String(row[colIdx] ?? '-')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}

        {/* Render Entities (as a card) */}
        {data.entities && data.entities.length > 0 && (
          <div className="apple-card p-6">
             <div className="flex items-center gap-2 mb-4">
              <Database className="text-gray-400" size={18} />
              <h3 className="font-semibold text-lg text-gray-900">Extracted Entities</h3>
            </div>
            <div className="space-y-3">
              {data.entities.map((e, i) => (
                <div key={i} className="flex justify-between items-center py-2 border-b border-gray-100 last:border-0">
                  <span className="font-medium text-gray-800">{e.name}</span>
                  <div className="flex gap-3 text-sm">
                    {e.value && <span className="text-gray-900">{e.value}</span>}
                    <span className="bg-gray-100 text-gray-500 px-2 py-0.5 rounded-md font-medium text-xs uppercase tracking-wide">
                      {e.type}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 4. Citations Pill */}
      {data.citations && data.citations.length > 0 && (
        <div className="mt-8 pt-6 border-t border-gray-200">
           <h4 className="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-3">Sources & Citations</h4>
           <div className="flex flex-wrap gap-2">
             {data.citations.map((c, i) => (
               <a 
                key={i} 
                href={c.url || '#'} 
                target="_blank" 
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-lg text-sm text-gray-600 transition-colors"
               >
                 {c.url && <ExternalLink size={14} />}
                 {c.title}
                 {c.artifact_name && <span className="text-xs opacity-60">({c.artifact_name})</span>}
               </a>
             ))}
           </div>
        </div>
      )}

    </div>
  );
}
