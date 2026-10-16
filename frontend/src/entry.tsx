import { createRoot } from "react-dom/client";
import RealApp from "./RealApp";
import "./style.css";
import "./real.css";

if (window.location.hash === "#demo") {
  // The stage 2 demonstration remains an explicit, separate entry point.
  void import("./main");
} else {
  createRoot(document.getElementById("root")!).render(
    <RealApp onDemo={() => { window.location.hash = "demo"; window.location.reload(); }} />
  );
}
