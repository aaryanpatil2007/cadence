import { useEffect, useState } from "react";
import Dashboard from "./Dashboard";
import Enroll from "./Enroll";

export default function App() {
  const [route, setRoute] = useState(window.location.hash);
  useEffect(() => {
    const onHash = () => setRoute(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return route.startsWith("#/enroll") ? <Enroll /> : <Dashboard />;
}
