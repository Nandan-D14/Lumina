export type ChartType = 'bar' | 'pie' | 'line';

export type SourceType = "text" | "url" | "file";

export interface Source {
  type: SourceType;
  text?: string;
  url?: string;
  filename?: string;
  mime_type?: string;
  content_base64?: string;
}

export interface AnalyzeOptions {
  allow_web_research: boolean;
  allow_scraping: boolean;
  max_visualizations: number;
  persistence_mode: 'session' | 'persistent';
  gemini_api_key: string;
  user_id?: string;
}

export interface AnalyzeRequest {
  prompt: string;
  sources: Source[];
  options: AnalyzeOptions;
}

export interface Metric {
  label: string;
  value: string | number;
}

export interface Entity {
  name: string;
  type: string;
  value?: string | number;
}

export interface Table {
  name: string;
  columns: string[];
  rows: (string | number | null)[][];
}

export interface Visualization {
  id: string;
  title: string;
  kind: "bar" | "line" | "pie" | "table";
  reason: string;
  labels?: string[];
  values?: number[];
}

export interface Citation {
  title: string;
  url?: string;
  artifact_name?: string;
}

export interface Artifact {
  name: string;
  mime_type: string;
  version: number;
}

export interface InsightPackage {
  analysis_id: string;
  session_id?: string;
  persistence_mode?: 'session' | 'persistent';
  summary: string;
  advanced_html_report?: string;
  insights: string[];
  metrics: Metric[];
  entities: Entity[];
  tables: Table[];
  visualizations: Visualization[];
  citations: Citation[];
  artifacts: Artifact[];
}

// For localStorage history
export interface HistoryEntry {
  id: string;
  timestamp: string;
  prompt: string;
  result: InsightPackage;
};
