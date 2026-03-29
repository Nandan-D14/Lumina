import React, { useState, useEffect, useRef } from 'react';
import { SidebarHistory } from './components/SidebarHistory';
import { InsightsDashboard } from './components/InsightsDashboard';
import { SettingsModal } from './components/SettingsModal';
import { HistoryEntry, InsightPackage, AnalyzeRequest, Source } from './types';
import { Search, UploadCloud, Globe, X, FileText, Settings2 } from 'lucide-react';

const LOCAL_STORAGE_KEY = 'lumina_history_v2';
const GEMINI_KEY_STORAGE_KEY = 'lumina_gemini_key';
const PERSISTENCE_MODE_KEY = 'lumina_persistence_mode';
const DISPLAY_MODEL_NAME = 'gemini-3-flash';

export default function App() {
  // State
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [currentId, setCurrentId] = useState<string | undefined>(undefined);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // Payload State
  const [promptText, setPromptText] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [allowWebSearch, setAllowWebSearch] = useState(false);
  const [geminiApiKey, setGeminiApiKey] = useState('');
  const [persistenceMode, setPersistenceMode] = useState<'session' | 'persistent'>('session');

  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liveSteps, setLiveSteps] = useState<string[]>([]);

  // File Input Ref
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load History
  useEffect(() => {
    const saved = localStorage.getItem(LOCAL_STORAGE_KEY);
    const savedKey = localStorage.getItem(GEMINI_KEY_STORAGE_KEY);
    const savedMode = localStorage.getItem(PERSISTENCE_MODE_KEY);
    if (saved) {
      try {
        setHistory(JSON.parse(saved));
      } catch (e) {
        console.error('Failed to parse history');
      }
    }
    if (savedKey) {
      setGeminiApiKey(savedKey);
    }
    if (savedMode === 'session' || savedMode === 'persistent') {
      setPersistenceMode(savedMode);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(GEMINI_KEY_STORAGE_KEY, geminiApiKey);
  }, [geminiApiKey]);

  useEffect(() => {
    localStorage.setItem(PERSISTENCE_MODE_KEY, persistenceMode);
  }, [persistenceMode]);

  const saveHistory = (newHistory: HistoryEntry[]) => {
    setHistory(newHistory);
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(newHistory.slice(0, 30)));
  };

  const handleDeleteEntry = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const newHistory = history.filter(h => h.id !== id);
    saveHistory(newHistory);
    if (currentId === id) {
      setCurrentId(undefined);
    }
  };

  const normalizeLiveStepMessage = (message: string): string => {
    const normalized = message.trim();
    if (!normalized) {
      return 'Running analysis step...';
    }

    if (/^querying\s+standard\s+engine/i.test(normalized)) {
      return `Querying analysis engine (${DISPLAY_MODEL_NAME})...`;
    }

    return normalized
      .replace(/openrouter_model/gi, DISPLAY_MODEL_NAME)
      .replace(/nvidia\/nemotron-3-super-120b-a12b:free/gi, DISPLAY_MODEL_NAME)
      .replace(/stepfun\/step-3\.5-flash:free/gi, DISPLAY_MODEL_NAME);
  };

  // Base64 Helper
  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        // Remove the data:mime/type;base64, prefix for the strict backend if needed, 
        // but typically 'content_base64' expects the raw base64 string without the scheme.
        const result = reader.result as string;
        const base64Data = result.split(',')[1];
        resolve(base64Data);
      };
      reader.onerror = (error) => reject(error);
    });
  };

  const handleAnalyze = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!promptText.trim() && !selectedFile) return;

    if (!geminiApiKey.trim()) {
      setError('Gemini API key is required. Click settings and add your key before running analysis.');
      return;
    }

    const effectivePrompt = promptText.trim() || (selectedFile ? `Analyze uploaded file: ${selectedFile.name}` : 'Analyze the provided source.');

    setIsAnalyzing(true);
    setLiveSteps([]);
    setError(null);
    setCurrentId(undefined); // Clear active history item to show loading

    try {
      // 1. Build Sources Array
      const sources: Source[] = [];
      
      // If there's a file, convert to base64 and add to sources
      if (selectedFile) {
        const base64 = await fileToBase64(selectedFile);
        sources.push({
          type: 'file',
          filename: selectedFile.name,
          mime_type: selectedFile.type || 'application/octet-stream',
          content_base64: base64
        });
      }

      // If they pasted a URL in the text box (simple detection)
      const urlMatches = promptText.match(/(https?:\/\/[^\s]+)/g);
      if (urlMatches) {
        urlMatches.forEach(url => {
          sources.push({ type: 'url', url });
        });
      } else if (promptText.trim() && !selectedFile) {
        // If it's just raw text and no file
        sources.push({ type: 'text', text: promptText });
      }

      const payload: AnalyzeRequest = {
        prompt: effectivePrompt,
        sources: sources,
        options: {
          allow_web_research: allowWebSearch,
          allow_scraping: true,
          max_visualizations: 3,
          persistence_mode: persistenceMode,
          gemini_api_key: geminiApiKey.trim(),
        }
      };

      const res = await fetch('/api/v1/analyze/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(`Analysis failed (${res.status})${errorText ? `: ${errorText}` : ''}`);
      }

      if (!res.body) throw new Error("No response body returned.");

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let done = false;
      let buffer = "";
      let insightData: InsightPackage | null = null;

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            try {
              const parsed = JSON.parse(trimmed);
              if (parsed.type === 'step') {
                const normalizedStep = normalizeLiveStepMessage(String(parsed.message || ''));
                setLiveSteps((prev) => {
                  if (prev[prev.length - 1] === normalizedStep) {
                    return prev;
                  }
                  return [...prev, normalizedStep];
                });
              } else if (parsed.type === 'error') {
                throw new Error(parsed.message);
              } else if (parsed.type === 'result') {
                insightData = parsed.data;
              }
            } catch (err) {
              if (err instanceof Error && err.message !== "Unexpected end of JSON input") {
                throw err;
              }
            }
          }
        }
      }

      if (buffer.trim()) {
        const parsed = JSON.parse(buffer.trim());
        if (parsed.type === 'result') insightData = parsed.data;
        else if (parsed.type === 'error') throw new Error(parsed.message);
      }

      if (!insightData) {
        throw new Error("Stream closed before final results were returned.");
      }

      const newEntry: HistoryEntry = {
        id: insightData.analysis_id || Date.now().toString(),
        timestamp: new Date().toISOString(),
        prompt: effectivePrompt,
        result: insightData,
      };

      saveHistory([newEntry, ...history]);
      setCurrentId(newEntry.id);
      
      // Clean up input
      setPromptText('');
      setSelectedFile(null);

    } catch (err: unknown) {
      console.error(err);
      setError(err instanceof Error ? err.message : 'Communication with the orchestrator failed. Ensure backend is running and reachable.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleSelectHistory = (entry: HistoryEntry) => {
    setCurrentId(entry.id);
  };

  const currentResult = history.find(h => h.id === currentId)?.result || null;

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[#FDFDFD]">
      {/* 1. Sidebar Map */}
      <SidebarHistory
        history={history} 
        onSelect={handleSelectHistory} 
        onDelete={handleDeleteEntry}
        currentId={currentId}
      />
      <div className="flex-1 flex flex-col h-full bg-[#f2f4f4] rounded-l-4xl shadow-[-10px_0_30px_-15px_rgba(0,0,0,0.05)] overflow-hidden relative border-l border-white">

        {/* Dynamic Header */}
        <header className="px-10 py-8 flex justify-between items-center z-10">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-gray-900">Intelligence Workspace</h2>
            <p className="text-sm font-medium text-gray-500 mt-1">Multi-Agent Cognitive Synthesis</p>
          </div>

          <button
            onClick={() => setIsSettingsOpen(true)}
            className="p-2 bg-white rounded-full shadow-sm text-gray-400 hover:text-[#007AFF] transition-colors border border-gray-100"
            title="Open Settings"
          >
            <Settings2 size={20} />
          </button>
        </header>

        {/* Scrollable Dashboard Area */}
        <div className="flex-1 overflow-y-auto px-10 pb-40">
           <InsightsDashboard 
            data={currentResult} 
            isLoading={isAnalyzing} 
            liveSteps={liveSteps} 
            onSampleClick={(prompt: string) => setPromptText(prompt)}
          />   
        </div>

        {/* Input Dock (Floating at Bottom) */}
        <div className="absolute bottom-8 left-10 right-10">
           <div className="apple-glass rounded-3xl p-3 shadow-[0_8px_30px_rgb(0,0,0,0.08)] mx-auto max-w-4xl border border-white">
              
              {/* File Attachment Pill */}
              {selectedFile && (
                <div className="mx-3 mt-2 mb-3 inline-flex items-center gap-2 bg-blue-50 text-[#007AFF] px-3 py-1.5 rounded-xl text-sm font-medium">
                  <FileText size={16} />
                  <span className="truncate max-w-50">{selectedFile.name}</span>
                  <button onClick={() => setSelectedFile(null)} className="ml-1 hover:text-blue-800 p-0.5 rounded-full hover:bg-blue-100">
                    <X size={14} />
                  </button>
                </div>
              )}

              <form onSubmit={handleAnalyze} className="flex gap-3">
                
                {/* File Upload Trigger */}
                <input 
                  type="file" 
                  ref={fileInputRef} 
                  className="hidden" 
                  accept=".csv,.json,.pdf,.txt"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                />
                
                <button 
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="p-4 rounded-2xl bg-gray-50 text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                  title="Upload Document"
                >
                  <UploadCloud size={22} />
                </button>

                {/* Main Input */}
                <input
                  type="text"
                  value={promptText}
                  onChange={(e) => setPromptText(e.target.value)}
                  placeholder="Paste a link, ask a question, or upload dataset..."
                  className="flex-1 bg-transparent border-0 outline-none text-gray-900 placeholder:text-gray-400 font-medium px-2 py-4 text-lg"
                  disabled={isAnalyzing}
                />

                {/* Web Research Toggle */}
                <button
                  type="button"
                  onClick={() => setAllowWebSearch(!allowWebSearch)}
                  className={`flex items-center gap-2 px-4 rounded-2xl font-medium text-sm transition-colors border ${
                    allowWebSearch 
                     ? 'bg-blue-50 border-blue-100 text-[#007AFF]' 
                     : 'bg-white border-gray-100 text-gray-400 hover:text-gray-600 hover:bg-gray-50'
                  }`}
                  title="Enable Google Grounding"
                >
                  <Globe size={18} />
                  <span className="hidden sm:inline">Web Search</span>
                </button>

                {/* Submit Action */}
                <button 
                  type="submit" 
                  disabled={isAnalyzing || (!promptText.trim() && !selectedFile)}
                  className="apple-button px-6 flex items-center gap-2 disabled:opacity-50 disabled:active:scale-100"
                >
                  <span className="font-semibold">{isAnalyzing ? 'Extracting...' : 'Synthesize'}</span>
                  {!isAnalyzing && <Search size={18} strokeWidth={3} className="opacity-80" />}
                </button>
              </form>
           </div>
           
           {/* Global Error SnackBar */}
           {error && (
             <div className="absolute -top-16 left-1/2 -translate-x-1/2 bg-red-50 text-red-600 px-4 py-2 rounded-xl text-sm font-medium border border-red-100 shadow-sm flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-red-600"></span>
                {error}
             </div>
           )}
        </div>
        
      </div>

      {/* Overlays / Modals */}
      <SettingsModal 
        isOpen={isSettingsOpen} 
        onClose={() => setIsSettingsOpen(false)} 
      />

    </div>
  );
}
