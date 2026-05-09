import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ConnectorConfig, SourceConfig, ToolDefinition } from "@/types/api";

interface StoreState {
  connector: ConnectorConfig | null;
  sources: SourceConfig[];
  tools: ToolDefinition[];
  selectedToolId: string | null;
  setConnector: (connector: ConnectorConfig | null) => void;
  selectTool: (toolId: string | null) => void;
}

export const useStore = create<StoreState>()(
  persist(
    (set) => ({
      connector: null,
      sources: [],
      tools: [],
      selectedToolId: null,
      setConnector: (connector) => set({ connector }),
      selectTool: (toolId) => set({ selectedToolId: toolId }),
    }),
    {
      name: "elliot-studio",
      partialize: (state) => ({ connector: state.connector }),
    }
  )
);
