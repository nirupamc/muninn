import { useScope } from "../../lib/scope";
export function BottomBar() { const { namespace } = useScope(); return <footer className="operations-footer"><span><i /> MEMORY SYSTEM ONLINE</span><span>M0—M7A OPERATIONAL</span><span>SCOPE <b>{namespace}</b></span></footer>; }
