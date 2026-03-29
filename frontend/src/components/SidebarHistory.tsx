import React from 'react';
import { History, LayoutTemplate, Clock, ChevronRight, Trash2 } from 'lucide-react';
import { HistoryEntry } from '../types';

interface SidebarHistoryProps {
  history: HistoryEntry[];
  onSelect: (entry: HistoryEntry) => void;
  onDelete?: (id: string, e: React.MouseEvent) => void;
  currentId?: string;
}

export function SidebarHistory({ history, onSelect, onDelete, currentId }: SidebarHistoryProps) {
  return (
    <div className="w-80 h-full apple-glass flex flex-col hide-scrollbar">
      <div className="p-6 pb-2 border-b border-gray-100/50">
        <div className="flex items-center gap-3 text-gray-900 mb-8">
          <div className="p-2 bg-blue-50 text-[#007AFF] rounded-xl">
            <LayoutTemplate size={22} className="opacity-90" />
          </div>
          <div>
            <h1 className="font-bold tracking-tight text-lg">Lumina</h1>
            <p className="text-xs text-gray-500 font-medium tracking-wide uppercase">Workspace</p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-gray-400 text-sm font-medium mb-4">
          <History size={15} />
          <span className="uppercase tracking-wider text-xs">Research Sessions</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 mt-2">
        {history.length === 0 ? (
          <p className="text-gray-400 text-sm p-4 text-center mt-4">
            Input a document to begin.
          </p>
        ) : (
          <div className="space-y-2 py-4">
            {history.map((entry) => {
              const d = new Date(entry.timestamp);
              const isSelected = currentId === entry.id;

              return (
                <button
                  key={entry.id}
                  onClick={() => onSelect(entry)}
                  className={`w-full text-left p-3 rounded-2xl border transition-all duration-200 group relative ${
                    isSelected 
                      ? 'bg-white border-gray-200 shadow-sm' 
                      : 'border-transparent hover:bg-white hover:border-gray-200/60'
                  }`}
                >
                  {isSelected && (
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-[#007AFF] rounded-r-full" />
                  )}
                  <div className="flex justify-between items-start mb-1 h-full">
                    <p className={`line-clamp-2 text-sm leading-relaxed pr-6 ${
                      isSelected ? 'text-gray-900 font-medium' : 'text-gray-600'
                    }`}>
                      {entry.prompt || entry.result.summary.slice(0, 60) + '...'}
                    </p>
                    <div className="absolute right-2 top-2 hidden group-hover:flex gap-1 z-10">
                        {onDelete && (
                            <button onClick={(e) => onDelete(entry.id, e)} className="p-1 hover:bg-red-50 text-gray-400 hover:text-red-500 rounded transition-colors" title="Delete">
                                <Trash2 size={14} />
                            </button>
                        )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-gray-400 font-medium">
                    <Clock size={12} />
                    {d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {d.toLocaleDateString([], { month: 'short', day: 'numeric' })}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
      
      <div className="p-4 mt-auto border-t border-gray-100/50">
          <div className="text-xs text-center text-gray-400">
            Powered by ADK Orchestrator
          </div>
      </div>
    </div>
  );
}
