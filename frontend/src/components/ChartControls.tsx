import React from 'react';
import { Settings2, BarChart3, LineChart, PieChart } from 'lucide-react';
import { Visualization } from '../types';

interface ChartControlsProps {
    onControlChange: (type: 'bar' | 'line' | 'pie') => void;
    currentType?: string;
}

export function ChartControls({ onControlChange, currentType = 'bar' }: ChartControlsProps) {
  return (
    <div className="flex flex-wrap gap-2 items-center bg-gray-50 p-1.5 rounded-2xl border border-gray-100 w-fit">
      
      {/* Type Toggles */}
      <div className="flex gap-1 relative">
         <div className="absolute inset-y-0 w-[1px] -left-1 bg-gray-200 my-1"></div>
         
         <button
          onClick={() => onControlChange('bar')}
          className={`p-1.5 rounded-xl transition-all ${
            currentType === 'bar' ? 'bg-white shadow-sm text-[#007AFF]' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
          }`}
          title="Bar Chart"
        >
          <BarChart3 size={16} />
        </button>
        <button
          onClick={() => onControlChange('line')}
          className={`p-1.5 rounded-xl transition-all ${
            currentType === 'line' ? 'bg-white shadow-sm text-[#007AFF]' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
          }`}
          title="Line Chart"
        >
          <LineChart size={16} />
        </button>
        <button
          onClick={() => onControlChange('pie')}
          className={`p-1.5 rounded-xl transition-all ${
            currentType === 'pie' ? 'bg-white shadow-sm text-[#007AFF]' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
          }`}
          title="Pie Chart"
        >
          <PieChart size={16} />
        </button>
      </div>

    </div>
  );
}
