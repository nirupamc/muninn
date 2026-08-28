import { useScope } from "../../lib/scope";
export function BottomBar() { const { namespace } = useScope(); return <footer className="operations-footer"><span><i /> MEMORY SYSTEM ONLINE</span><span>M10-M14 OPERATIONAL</span><span>SCOPE <b>{namespace}</b></span></footer>; }
