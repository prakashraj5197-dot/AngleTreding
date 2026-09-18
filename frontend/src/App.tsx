import { Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Dashboard from "@/pages/Dashboard";
import Signals from "@/pages/Signals";
import OptionScanner from "@/pages/OptionScanner";
import MarketAnalysis from "@/pages/MarketAnalysis";
import Backtesting from "@/pages/Backtesting";
import PaperTrading from "@/pages/PaperTrading";
import Settings from "@/pages/Settings";

// One <Route> per page in src/pages; BrowserRouter already wraps this in main.tsx.
export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/signals" element={<Signals />} />
        <Route path="/option-scanner" element={<OptionScanner />} />
        <Route path="/market-analysis" element={<MarketAnalysis />} />
        <Route path="/backtesting" element={<Backtesting />} />
        <Route path="/paper-trading" element={<PaperTrading />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
      <Toaster richColors />
    </>
  );
}
