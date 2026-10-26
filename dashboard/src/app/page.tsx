import { redirect } from "next/navigation";

// The v2.x live-signal landing page was deleted with the signal surface (todo 509 item 2);
// the trading dashboard is the entry point.
export default function Home() {
  redirect("/dashboard");
}
