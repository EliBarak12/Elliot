import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ConnectorConfig } from "@/types/api";

interface StoreState {
  connector: ConnectorConfig | null;
  setConnector: (connector: ConnectorConfig | null) => void;
}

export const useStore = create<StoreState>()(
  persist(
    (set) => ({
      connector: null,
      setConnector: (connector) => set({ connector }),
    }),
    {
      name: "elliot-studio",
      partialize: (state) => ({ connector: state.connector }),
    }
  )
);
