import React, { useState } from 'react';
import { X, Save, Trash2, Key, Settings as SettingsIcon } from 'lucide-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState('api-keys');
  const [geminiKey, setGeminiKey] = useState('***************************');
  const [isDarkMode, setIsDarkMode] = useState(() => document.documentElement.classList.contains('dark'));

  const toggleDarkMode = () => {
    if (isDarkMode) {
      document.documentElement.classList.remove('dark');
      setIsDarkMode(false);
    } else {
      document.documentElement.classList.add('dark');
      setIsDarkMode(true);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm transition-opacity animate-in fade-in duration-200">
      <div className="bg-white rounded-3xl shadow-2xl w-[800px] h-[500px] flex overflow-hidden border border-gray-100 animate-in zoom-in-95 duration-200">
        
        {/* Left Sidebar */}
        <div className="w-64 bg-gray-50 border-r border-gray-100 p-6 flex flex-col gap-2">
          <h3 className="text-lg font-bold text-gray-900 mb-4 px-2">Settings</h3>
          
          <button 
            onClick={() => setActiveTab('api-keys')}
            className={`text-left px-4 py-3 rounded-xl font-medium transition-colors flex items-center gap-3 ${activeTab === 'api-keys' ? 'bg-white text-[#007AFF] shadow-sm ring-1 ring-gray-900/5' : 'text-gray-500 hover:text-gray-900 hover:bg-gray-100'}`}
          >
            <Key size={18} />
            API Keys
          </button>
          
          <button 
            onClick={() => setActiveTab('preferences')}
            className={`text-left px-4 py-3 rounded-xl font-medium transition-colors flex items-center gap-3 ${activeTab === 'preferences' ? 'bg-white text-[#007AFF] shadow-sm ring-1 ring-gray-900/5' : 'text-gray-500 hover:text-gray-900 hover:bg-gray-100'}`}
          >
            <SettingsIcon size={18} />
            Preferences
          </button>
        </div>

        {/* Right Content Area */}
        <div className="flex-1 p-8 flex flex-col bg-white relative">
          <button 
            onClick={onClose} 
            className="absolute top-6 right-6 p-2 text-gray-400 hover:text-gray-900 hover:bg-gray-100 rounded-full transition-colors"
          >
            <X size={20} />
          </button>
          
          {activeTab === 'api-keys' && (
            <div className="flex-1 flex flex-col animate-in fade-in slide-in-from-right-4 duration-300">
              <h2 className="text-2xl font-bold text-gray-900 mb-2">API Keys & Secrets</h2>
              <p className="text-sm text-gray-500 mb-8">
                Manage your API keys for different model providers. (These are static mocks and do not affect the backend).
              </p>

              <div className="space-y-6">
                {/* Key Row 1 */}
                <div className="flex items-end gap-3">
                  <div className="flex-1">
                    <label className="block text-sm font-semibold text-gray-700 mb-1.5 ml-1">Gemini API Key</label>
                    <input 
                      type="password"
                      value={geminiKey}
                      onChange={(e) => setGeminiKey(e.target.value)}
                      className="w-full bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/20 focus:border-[#007AFF] transition-all font-mono"
                      placeholder="Enter key..."
                    />
                  </div>
                  <button 
                    onClick={onClose}
                    className="h-[50px] w-[50px] flex items-center justify-center bg-white border border-gray-200 rounded-xl text-gray-600 hover:text-[#007AFF] hover:border-[#007AFF]/30 shadow-sm transition-all" 
                    title="Save"
                  >
                    <Save size={20} />
                  </button>
                  <button 
                    onClick={() => setGeminiKey('')}
                    className="h-[50px] w-[50px] flex items-center justify-center bg-white border border-gray-200 rounded-xl text-gray-600 hover:text-red-500 hover:border-red-200 shadow-sm transition-all" 
                    title="Remove"
                  >
                    <Trash2 size={20} />
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'preferences' && (
            <div className="flex-1 flex flex-col animate-in fade-in slide-in-from-right-4 duration-300">
              <h2 className="text-2xl font-bold text-gray-900 mb-2">Preferences</h2>
              <p className="text-sm text-gray-500 mb-8">Adjust your workspace settings.</p>
              
               <div 
                 onClick={toggleDarkMode}
                 className="p-4 bg-gray-50 rounded-2xl border border-gray-100 flex items-center justify-between cursor-pointer hover:bg-gray-100 transition-colors"
                >
                 <div>
                    <h4 className="font-semibold text-gray-900">Dark Mode</h4>
                    <p className="text-sm text-gray-500">Toggle dark appearance</p>
                 </div>
                 <div className={`w-12 h-6 rounded-full transition-colors flex items-center px-1 ${isDarkMode ? 'bg-[#007AFF]' : 'bg-gray-300'}`}>
                    <div className={`w-4 h-4 rounded-full bg-white transition-transform ${isDarkMode ? 'translate-x-6' : 'translate-x-0'}`}></div>
                 </div>
               </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}