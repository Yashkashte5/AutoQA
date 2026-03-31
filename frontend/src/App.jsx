import { Routes, Route } from "react-router-dom";
import Home from "./pages/Home";
import Results from "./pages/Results";

export default function App() {
  return (
    <div className="app">
      <header className="header">
        <span className="logo">AutoQA</span>
        <span className="tagline">Agentic API Testing</span>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/results/:runId" element={<Results />} />
        </Routes>
      </main>
    </div>
  );
}